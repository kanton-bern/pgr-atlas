"""UI helpers used by more than one view."""

import html
import json
import math
from collections.abc import Sequence
from urllib.parse import urlsplit

import numpy as np
import streamlit as st
from pyproj import Transformer
from streamlit.delta_generator import DeltaGenerator
from streamlit.navigation.page import StreamlitPage

import area_job
import coverage_store
import ui_text
from probe_core.data_lake import data_interface as data
from probe_core.derivate import ifk_and_raster

# Kanton Bern in WGS84, with a margin: the box a link's map view or pixel must
# lie in (the same box as gebaeudeschatten_view._CANTON_BOUNDS).
CANTON_LAT_RANGE = (46.30, 47.35)
CANTON_LON_RANGE = (6.85, 8.46)


_PIXEL_M = 5.0
_HALF_PIXEL_M = _PIXEL_M / 2
_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
# LV95 around Switzerland (BOUNDS in frontend/src/shared/lv95.ts).
_LV95_X_RANGE = (2_460_000, 2_860_000)
_LV95_Y_RANGE = (1_050_000, 1_320_000)


def snap_to_pixel(v: float) -> float:
    """The centre of the gold pixel lattice nearest to an LV95 coordinate (the
    map's MapControls.LV95.snapToPixel)."""
    nearest_index = math.floor((v - _HALF_PIXEL_M) / _PIXEL_M + 0.5)
    return _PIXEL_M * nearest_index + _HALF_PIXEL_M


def check_in_canton(x: float, y: float):
    """Raises ValueError unless the LV95 point (x, y) lies in Kanton Bern
    (CANTON_LAT_RANGE, CANTON_LON_RANGE): what a link's coordinates must do."""
    # Far outside LV95's range the projection wraps around, so check that
    # first; the comparisons also reject nan.
    if not (
        _LV95_X_RANGE[0] <= x <= _LV95_X_RANGE[1] and _LV95_Y_RANGE[0] <= y <= _LV95_Y_RANGE[1]
    ):
        raise ValueError(f"x={x}, y={y} is not an LV95 coordinate in Switzerland")
    lon, lat = _TO_WGS84.transform(x, y)
    if not (
        CANTON_LAT_RANGE[0] <= lat <= CANTON_LAT_RANGE[1]
        and CANTON_LON_RANGE[0] <= lon <= CANTON_LON_RANGE[1]
    ):
        raise ValueError(f"x={x}, y={y} is outside Kanton Bern")


def query_floats(params, keys: tuple[str, ...]) -> list[float] | None:
    """The numbers a link gives under `keys`; None if it has none of them.

    Raises:
        ValueError: one of them is missing or not a number.
    """
    if not any(key in params for key in keys):
        return None
    values = []
    for key in keys:
        if key not in params:
            raise ValueError(f"{key} is missing")
        try:
            values.append(float(params[key]))
        except ValueError:
            raise ValueError(f"{key}={params[key]!r} is not a number") from None
    return values


# Generous LV95 (E, N) box around Switzerland; every selection lies in it.
LV95_PLAUSIBLE_BOUNDS = (2_000_000, 1_000_000, 3_200_000, 1_350_000)
# A drawn polygon has a handful of vertices, an uploaded one is simplified
# past 500 (area_upload.py); the ring also becomes the WKT of a SQL filter.
MAX_SELECTION_VERTICES = 5_000


def checked_selection(selection) -> dict | None:
    """The selection a map component sent, with float coordinates; None stays
    None ("Löschen").

    The value comes from the browser, so it is checked before anything
    computes with it: the views count the kacheln under its bounds (a ring far
    outside Switzerland would count without end), and probe-core writes the
    ring into a SQL filter.

    Raises:
        ValueError: not {'type': 'bbox'|'polygon', 'ring': [[E, N], ...]} with
            a closed ring of at most MAX_SELECTION_VERTICES finite LV95 points
            in Switzerland.
    """
    if selection is None:
        return None
    if not isinstance(selection, dict) or selection.get("type") not in ("bbox", "polygon"):
        raise ValueError("not a bbox or polygon selection")
    ring = selection.get("ring")
    if not isinstance(ring, list) or not 4 <= len(ring) <= MAX_SELECTION_VERTICES + 1:
        raise ValueError("the ring is not a list of 4 or more points, or has too many")
    xmin, ymin, xmax, ymax = LV95_PLAUSIBLE_BOUNDS
    points = []
    for point in ring:
        if not (
            isinstance(point, list)
            and len(point) == 2
            and all(
                isinstance(coordinate, (int, float)) and not isinstance(coordinate, bool)
                for coordinate in point
            )
        ):
            raise ValueError("a ring point is not a pair of numbers")
        east, north = float(point[0]), float(point[1])
        if not (xmin <= east <= xmax and ymin <= north <= ymax):  # also rejects nan and inf
            raise ValueError("a ring point is not an LV95 coordinate in Switzerland")
        points.append([east, north])
    if points[0] != points[-1]:
        raise ValueError("the ring is not closed")
    return {"type": selection["type"], "ring": points}


def selection_footprint(selection: dict) -> tuple[float, float, float, float, float]:
    """(xmin, ymin, xmax, ymax, area_m2) of the gold pixels a selection takes,
    measured along their edges -- what the map draws and measures
    (frontend/src/shared/pixel-footprint.ts, the same scanline). A
    rectangle takes every pixel centre on or inside it, a polygon every centre
    strictly inside (ifk_and_raster._selection_where_sql). No pixel: the
    ring's bounds and 0 m²."""
    ring = np.asarray(selection["ring"], dtype=float)
    xs, ys = ring[:, 0], ring[:, 1]
    if selection["type"] == "bbox":
        # Pixel indices of the first and last centre inside the rectangle.
        first_column = math.ceil((xs.min() - _HALF_PIXEL_M) / _PIXEL_M)
        last_column = math.floor((xs.max() - _HALF_PIXEL_M) / _PIXEL_M)
        first_row = math.ceil((ys.min() - _HALF_PIXEL_M) / _PIXEL_M)
        last_row = math.floor((ys.max() - _HALF_PIXEL_M) / _PIXEL_M)
        if first_column > last_column or first_row > last_row:
            return xs.min(), ys.min(), xs.max(), ys.max(), 0.0
        n_pixels = (last_column - first_column + 1) * (last_row - first_row + 1)
        return (
            _PIXEL_M * first_column,
            _PIXEL_M * first_row,
            _PIXEL_M * (last_column + 1),
            _PIXEL_M * (last_row + 1),
            _PIXEL_M * _PIXEL_M * n_pixels,
        )
    # Each ring edge runs from (edge_x0, edge_y0) to (edge_x1, edge_y1).
    edge_x0, edge_y0, edge_x1, edge_y1 = xs, ys, np.roll(xs, -1), np.roll(ys, -1)
    edge_y_low, edge_y_high = np.minimum(edge_y0, edge_y1), np.maximum(edge_y0, edge_y1)
    n_pixels, columns, rows = 0, [], []
    for row in range(
        math.floor((ys.min() - _HALF_PIXEL_M) / _PIXEL_M) + 1,
        math.ceil((ys.max() - _HALF_PIXEL_M) / _PIXEL_M),
    ):
        row_center_y = _PIXEL_M * row + _HALF_PIXEL_M
        # Half-open in y, so a vertex on the scanline counts once.
        crossing = (edge_y_low <= row_center_y) & (edge_y_high > row_center_y)
        x0, y0 = edge_x0[crossing], edge_y0[crossing]
        x1, y1 = edge_x1[crossing], edge_y1[crossing]
        crossing_xs = np.sort(x0 + (row_center_y - y0) * (x1 - x0) / (y1 - y0))
        # Between each pair of crossings: the pixel centres strictly inside.
        first = np.floor((crossing_xs[0::2] - _HALF_PIXEL_M) / _PIXEL_M) + 1
        last = np.ceil((crossing_xs[1::2] - _HALF_PIXEL_M) / _PIXEL_M) - 1
        runs = last >= first
        if runs.any():
            n_pixels += int((last[runs] - first[runs] + 1).sum())
            columns += [first[runs].min(), last[runs].max()]
            rows.append(row)
    if not n_pixels:
        return xs.min(), ys.min(), xs.max(), ys.max(), 0.0
    return (
        _PIXEL_M * min(columns),
        _PIXEL_M * rows[0],
        _PIXEL_M * (max(columns) + 1),
        _PIXEL_M * (rows[-1] + 1),
        _PIXEL_M * _PIXEL_M * n_pixels,
    )


def selection_size_label(xmin, ymin, xmax, ymax, area_m2) -> str:
    """'719 m × 406 m · 291'914 m²' -- the pixel footprint's width × height and
    area (selection_footprint), same as the map's readout (frontend/src/shared/
    selection-geometry.ts's sizeReadout)."""

    def length_label(length_m):
        if length_m >= 1000:
            km = ui_text.in_locale(f"{length_m / 1000:.2f}")
            return ui_text.t("map.selection.length_km", value=km)
        return ui_text.t("map.selection.length_m", value=ui_text.in_locale(f"{length_m:.0f}"))

    return ui_text.t(
        "map.selection.selection_size_rect",
        width=length_label(xmax - xmin),
        height=length_label(ymax - ymin),
        area=ui_text.fmt_ch(round(area_m2)),
    )


def shape_label(selection: dict) -> str:
    """ "Rechteck", or "Polygon (n Eckpunkte)" for a polygon."""
    if selection["type"] == "polygon":
        return ui_text.t("area.shape_polygon_vertices", n_vertices=len(selection["ring"]) - 1)
    return ui_text.t("area.shape_rectangle")


def selection_caption(selection: dict) -> bool:
    """Shows the selection's size in the sidebar, and why it is too large to
    compute if it is (selection_limit_error); returns True in that case."""
    xmin, ymin, xmax, ymax = ifk_and_raster.selection_bounds(selection)
    n_kacheln = len(ifk_and_raster.kacheln_for_bbox(xmin, ymin, xmax, ymax))
    *footprint, area_m2 = selection_footprint(selection)
    st.sidebar.caption(
        ui_text.t(
            "area.selection_size",
            shape=shape_label(selection),
            size=selection_size_label(*footprint, area_m2),
            n_kacheln=n_kacheln,
        )
    )
    error = selection_limit_error(selection)
    if error is not None:
        st.sidebar.error(error)
    return error is not None


def selection_limit_error(selection: dict) -> str | None:
    """Why the selection is too large to compute, or None if it isn't.

    Cheap (no I/O), and mirrors the checks probe-core's builds make themselves
    (check_raster_size, RasterBboxTooLargeError), so an oversized selection
    never starts a job. Gold is read per whole 1 km kachel, so the kachel
    count drives the cost and the limit, and can be well above the area itself
    when a selection straddles kachel boundaries."""
    xmin, ymin, xmax, ymax = ifk_and_raster.selection_bounds(selection)
    n_kacheln = len(ifk_and_raster.kacheln_for_bbox(xmin, ymin, xmax, ymax))
    max_kacheln = ifk_and_raster.max_raster_kacheln()
    if n_kacheln > max_kacheln:
        area_km2 = selection_footprint(selection)[-1] / 1e6
        return ui_text.raster_too_many_kacheln(area_km2, n_kacheln, max_kacheln)
    return _too_many_rows(selection)


def _too_many_rows(selection: dict) -> str | None:
    """The rows read, not the kacheln, set a job's time: kacheln hold 0 to
    ~510 M rows (estimate_raster_rows, from one cached S3 listing)."""
    estimated_rows = ifk_and_raster.estimate_raster_rows(selection)
    max_rows = ifk_and_raster.raster_max_rows()
    if estimated_rows <= max_rows:
        return None
    return ui_text.t(
        "raster.too_many_rows",
        est_mio=ui_text.fmt_ch(round(estimated_rows / 1e6)),
        max_mio=ui_text.fmt_ch(round(max_rows / 1e6)),
        duration=area_job.format_duration_s(ifk_and_raster.estimate_raster_seconds(selection)),
    )


def bbox_server_url(bbox_server: dict, path: str) -> str:
    """URL of `path` on derivate_bbox_server.py as the browser reaches it:
    same origin behind the ingress (its path_prefix), otherwise the page's
    host on the sidecar's own port. Mirrors httpBase in
    frontend/src/shared/urls.ts.

    Args:
        bbox_server: port and path_prefix of derivate_bbox_server.py.
        path: the route, starting with "/".
    """
    if bbox_server["path_prefix"]:
        return f"{bbox_server['path_prefix']}{path}"
    page = urlsplit(st.context.url)
    return f"{page.scheme}://{page.hostname}:{bbox_server['port']}{path}"


def download_link_button(label: str, url: str, key: str, **kwargs):
    """`st.link_button` to a sidecar download, marked for the download gate.

    The button sits in a container keyed `pgr_download_<key>`, which Streamlit
    renders as the class `st-key-pgr_download_<key>`. The client-side download
    disclaimer finds the link by that class.

    Args:
        label: the button text.
        url: the sidecar download URL.
        key: unique, stable name of this download on its page.
        **kwargs: passed on to `st.link_button`.
    """
    with st.container(key=f"pgr_download_{key}"):
        return st.link_button(label, url, **kwargs)


def page_header_html(title: str, hint: str, chips: Sequence[str] = ()) -> str:
    """The header's markup: the title as the page's only h1, the context
    chips beside it, and one line of instruction below. Text is escaped."""
    chip_html = "".join(f'<span class="pgr-chip">{html.escape(chip)}</span>' for chip in chips)
    return (
        '<div class="pgr-page-head"><div class="pgr-page-title-row">'
        f'<h1 class="pgr-page-title">{html.escape(title)}</h1>{chip_html}</div>'
        f'<p class="pgr-page-hint">{html.escape(hint)}</p></div>'
    )


def page_header(title: str, hint: str, chips: Sequence[str] = ()) -> DeltaGenerator:
    """The header at the top of every view: title, context chips and
    one line of instruction. Drawn on every run, selection or not, so the map
    below it never moves.

    Returns:
        The header row, for a control at its right end (the Datenstand of Simulierte Ereignisse).
    """
    row = st.container(
        key="pgr_page_header",
        horizontal=True,
        vertical_alignment="center",
        gap="medium",
        wrap=False,
    )
    with row:
        # st.html, not st.markdown: a markdown heading gets an anchor link.
        st.html(page_header_html(title, hint, chips))
    return row


def expert_chip() -> list[str]:
    """The header chip while the Experten-Modus is on, else none."""
    return [ui_text.t("header.chip_expert")] if st.session_state.get("_expert_active") else []


@st.cache_data(show_spinner=False)
def load_coverage():
    """Finalized gold-kachel squares (S3-backed, see app.py's
    _refresh_gold_manifest), WGS84 — "show the finalized gold tiles only".

    Returns (version, geojson). The body is also published to
    coverage_store as "gold", from where pmtiles_server.py serves it as
    /coverage.geojson?v=<version>: the map components get only the version
    and fetch the GeoJSON once over HTTP, instead of receiving it on every
    rerun. The dict stays for Python-side checks (pixel_in_coverage).

    Cached for the process lifetime, like the manifest it is derived from
    (refreshed once at startup, see app.py's _get_gold_manifest_cache). If
    the manifest ever refreshes periodically, give this the same ttl: an
    outer cache without a matching refresh keeps serving the coverage built
    from the old manifest."""
    body = data.load_kachel_coverage().to_crs("EPSG:4326").to_json()
    return coverage_store.publish("gold", body), json.loads(body)


def anriss_query_params(id_anriss: int) -> dict[str, str]:
    """The query params of the Anriss view's link to an Anriss (/anriss?id=...),
    passed wherever a view switches to it."""
    return {"id": str(int(id_anriss))}


def anriss_lookup_form(anriss_page: StreamlitPage):
    """ "Anriss öffnen" by ID, in the sidebar under the navigation on every
    view; opens `anriss_page` for a known ID. 61.3M anrisse at MAXI
    scale -- no preloaded options list (a selectbox would have to ship every
    ID to the browser). A single indexed lookup via id_anriss_exists() instead."""
    with st.sidebar.form("anriss_lookup", clear_on_submit=False, border=False):
        input_id_anriss = st.number_input(
            ui_text.t("lookup.label"),
            min_value=1,
            step=1,
            value=None,
            placeholder=ui_text.t("lookup.placeholder"),
            key="_anriss_input",
            format="%d",
        )
        lookup_submitted = st.form_submit_button(ui_text.t("lookup.submit"), width="stretch")
    if lookup_submitted and input_id_anriss is not None:
        if data.id_anriss_exists(int(input_id_anriss)):
            st.session_state.hull_geojson = None
            st.session_state.selected_id_anriss = int(input_id_anriss)
            st.switch_page(anriss_page, query_params=anriss_query_params(input_id_anriss))
        else:
            st.sidebar.error(ui_text.lookup_unknown(int(input_id_anriss)))
