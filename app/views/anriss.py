"""Anriss: one Anriss's simulation results, per scenario.

The sidebar picks the scenario (A, h, mu, xsi, tau0). The main area shows the
scenario's pixels on a map with the Umhüllende, then its Statistik (with its
lambda_Ereignis and return period), then the downloads. "Anriss abwählen" goes
back to the view the Anriss was opened from.

A link can open an Anriss: /anriss?id=<id_anriss>. Every switch to this view
passes that link (ui_common.anriss_query_params).
"""

import json
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st
from pyproj import Transformer
from shapely.geometry import Point
from streamlit.navigation.page import StreamlitPage

import anriss_export
import anriss_prefetch
import language
import ui_text
from anriss_map_component import anriss_result_map
from downloads_cue_component import downloads_cue, downloads_section
from probe_core.data_lake import data_interface as data
from probe_core.data_lake.data_lake_schema import GOLD_PIXEL_MAX_REACH_M
from probe_core.derivate import event_export, ifk_and_raster
from raster_overlay import VARIABLE_UNITS, colormap_gradient_css
from state import AnrissEntry
from ui_common import page_header
from views import ifk, overview

VIEW_MODE = "Specific Simulation"

logger = logging.getLogger(__name__)

_VARIABLES = ("depth", "velocity", "pressure")
_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
_PIXEL_SIZE = event_export.PIXEL_SIZE

# Margin (metres, LV95) added around the Umhüllende bbox when framing the
# map on open -- keeps the envelope from touching the viewport edge.
_MAP_VIEWPORT_BUFFER_M = 30

# How close a scenario's furthest pixel must get to GOLD_PIXEL_MAX_REACH_M
# before the 800 m circle is on by default -- "nearly touches", not just
# "exactly at the clipped edge".
_REACH_CIRCLE_NEAR_MARGIN_M = 50

# Float-equality tolerance for matching a scenario's mu against the selected
# value (both float64, so exact == is unreliable).
_MU_MATCH_TOL = 1e-4

# "Ad-hoc Umhüllende berechnen" (the envelope over every scenario of the
# Anriss, computed in the app from the gold data) -- hidden since the
# precomputed Umhüllende covers it; set True to show the button again.
_SHOW_ADHOC_HULL_BUTTON = False

# The precomputed hull reads (_start_hull_read), one per Anriss opened. This
# module is imported once per process, so the pool is shared by all sessions.
_hull_reads = ThreadPoolExecutor(max_workers=4, thread_name_prefix="anriss-hull")

# "Anriss abwählen": the link of the view the Anriss was opened from.
_RETURN_QUERY = {
    overview.VIEW_MODE: overview.return_query_params,
    ifk.VIEW_MODE: ifk.return_query_params,
}


class Scenario(NamedTuple):
    """The selected scenario; as a tuple it is the key of its cached results."""

    id_anriss: int
    area: int
    h: int
    mu: float
    xsi: int
    tau0: int


@dataclass
class _Loaded:
    """What the sidebar stage loaded, for the main area."""

    scenario: Scenario
    entry: AnrissEntry
    df_sim: pd.DataFrame | None  # the scenario's pixels; None if the Anriss didn't load
    view_target: str
    release_geojson: dict
    reach_circle_geojson: dict
    show_reach_circle: bool


def id_from_query(params: Mapping[str, str]) -> int | None:
    """The Anriss a link asks for (?id=).

    Returns:
        None if the link has no id.

    Raises:
        ValueError: the id is not a whole number of at least 1.
    """
    if "id" not in params:
        return None
    try:
        id_anriss = int(params["id"])
    except ValueError:
        raise ValueError(f"id={params['id']!r} is not a whole number") from None
    if id_anriss < 1:
        raise ValueError(f"id={id_anriss} is below 1")
    return id_anriss


def select_from_link() -> str | None:
    """Selects the Anriss a link names, unless it is the selected one already.
    Called by app.py before the sidebar, whose "Anriss" link shows the
    selection.

    Returns:
        The message for a bad link (the lookup form's one for an unknown id),
        or None.
    """
    try:
        id_anriss = id_from_query(st.query_params)
    except ValueError:
        return ui_text.t("anriss.bad_link")
    if id_anriss is None or id_anriss == st.session_state.selected_id_anriss:
        return None
    if not data.id_anriss_exists(id_anriss):
        return ui_text.lookup_unknown(id_anriss)
    st.session_state.hull_geojson = None
    st.session_state["_anriss_pending"] = id_anriss
    st.session_state.selected_id_anriss = id_anriss
    return None


@st.cache_data(show_spinner=False)
def get_event_params(id_anriss: int):
    return data.get_event_params(id_anriss)


def _gold_to_display_df(df):
    """Raw gold columns (Fliesstiefe [cm], Fliessgeschwindigkeit [cm/s], Druck
    [kPa == kN/m²]) -> display columns (Fliesstiefe [m], Fliessgeschwindigkeit
    [m/s], Druck [kN/m²])."""
    return df.assign(
        depth=df["Fliesstiefe"] / 100.0,
        velocity=df["Fliessgeschwindigkeit"] / 100.0,
        pressure=df["Druck"].astype(float),
    )


def _variable_with_unit(variable: str) -> str:
    """'Fliesstiefe [m]': the variable's label and its unit."""
    return f"{ui_text.t(f'variable.{variable}')} [{VARIABLE_UNITS[variable]}]"


def _value_legend_payload(vmin, vmax, view_target, cmap="viridis"):
    """Value legend of the map ({'title', 'gradient', 'vmin_label',
    'vmid_label', 'vmax_label'}, see anriss_map_component) -- vmin/vmax are
    the bounds _continuous_cells_geojson colors by."""
    return {
        "title": _variable_with_unit(view_target),
        "gradient": colormap_gradient_css(plt.get_cmap(cmap)),
        "vmin_label": ui_text.in_locale(f"{vmin:.2f}"),
        "vmid_label": ui_text.in_locale(f"{(vmin + vmax) / 2:.2f}"),
        "vmax_label": ui_text.in_locale(f"{vmax:.2f}"),
    }


def _continuous_cells_geojson(df, value_col, cmap="viridis"):
    """The map's pixels as colored squares, and their legend.

    Returns (geojson, legend) -- the legend is built from the SAME vmin/vmax
    the colors are normalized by (every pixel with a value > 0), so a color
    on the map reads off the legend exactly. Both None if nothing to draw."""
    if df is None or df.empty:
        return None, None

    half_pixel = _PIXEL_SIZE / 2.0
    values = df[value_col].to_numpy(dtype=np.float32)
    valid = np.isfinite(values) & (values > 0)
    if not np.any(valid):
        return None, None

    vmin = float(np.nanmin(values[valid]))
    vmax = float(np.nanmax(values[valid]))
    span = max(vmax - vmin, 1e-12)  # a scenario of one value must not divide by zero
    colormap = plt.get_cmap(cmap)

    valid_df = df.loc[valid, ["x", "y", value_col]]
    xs = valid_df["x"].to_numpy()
    ys = valid_df["y"].to_numpy()

    shown_values = valid_df[value_col].to_numpy()
    ramp_position = np.clip((shown_values - vmin) / span, 0.0, 1.0)
    rgb_ints = (colormap(ramp_position)[:, :3] * 255).astype(np.uint32)
    packed = (rgb_ints[:, 0] << 16) | (rgb_ints[:, 1] << 8) | rgb_ints[:, 2]
    hex_colors = [f"#{rgb:06x}" for rgb in packed.tolist()]

    unit = VARIABLE_UNITS[value_col]
    value_labels = [
        f"{ui_text.in_locale(f'{value:.2f}')} {unit}" for value in shown_values.tolist()
    ]

    # SW, SE, NE, NW, SW per pixel: one closed ring each.
    west, east = xs - half_pixel, xs + half_pixel
    south, north = ys - half_pixel, ys + half_pixel
    x_corners = np.stack([west, east, east, west, west], axis=1)
    y_corners = np.stack([south, south, north, north, south], axis=1)
    lons, lats = _TO_WGS84.transform(x_corners.ravel(), y_corners.ravel())
    lons = lons.reshape(-1, 5)
    lats = lats.reshape(-1, 5)

    # 7 decimals (~1 cm) -- plenty for 5 m squares, and it keeps the payload
    # sent to the map on every rerun small.
    lons = np.round(lons, 7)
    lats = np.round(lats, 7)
    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [float(lons[pixel, corner]), float(lats[pixel, corner])]
                        for corner in range(5)
                    ]
                ],
            },
            "properties": {"fillColor": hex_colors[pixel], "value_label": value_labels[pixel]},
        }
        for pixel in range(len(xs))
    ]

    return (
        {"type": "FeatureCollection", "features": features},
        _value_legend_payload(vmin, vmax, value_col, cmap),
    )


def _circle_geojson(center, radius, id_anriss, **buffer_kwargs):
    """A circle around an LV95 point, as WGS84 GeoJSON."""
    circle = Point(*center).buffer(radius, **buffer_kwargs)
    circle_frame = gpd.GeoDataFrame(
        {"id_anriss": [id_anriss]}, geometry=[circle], crs=data.CRS_LV95
    )
    return json.loads(circle_frame.to_crs("EPSG:4326").to_json())


def _compute_adhoc_hull(df_all_scenarios, cached, id_anriss) -> str | None:
    """Fills st.session_state.hull_geojson/_path, which the map draws as
    'Umhüllende (Ad-hoc)' and "Derivate & Export" offers as a download.
    Reuses the all-scenarios read cached for the parameter dropdowns
    (AnrissEntry.all_scenarios) -- no separate S3 round trip.

    Returns:
        Why it couldn't be computed, or None."""
    if df_all_scenarios is not None:
        with st.spinner(ui_text.t("anriss.spinner_adhoc_hull")):
            hull_geojson, hull_path = event_export.export_event_envelope_geojson(
                df_all_scenarios, id_anriss
            )
            st.session_state.hull_geojson = hull_geojson
            st.session_state.hull_geojson_path = hull_path
        return None
    if cached["gold_not_ready"] is not None:
        return ui_text.t(
            "anriss.adhoc_hull_not_ready", kacheln=cached["gold_not_ready"].pending_kacheln
        )
    return ui_text.t("anriss.adhoc_hull_not_indexed", id=id_anriss)


def _parameter_inputs(id_anriss):
    """The scenario selectboxes; returns the Scenario and the event
    parameters of its area A (h differs slightly between areas)."""
    event_meta = get_event_params(int(id_anriss))
    left_column, right_column = st.sidebar.columns(2)
    area = left_column.selectbox(
        "A [m²]", sorted(event_meta["A"].unique()), key=f"area_{id_anriss}"
    )
    event_meta = event_meta[event_meta["A"] == area]
    # h stays gold's cm (it keys the scenario); only the label shows m.
    thickness_cm = right_column.selectbox(
        "h [m]",
        sorted(event_meta["h"].unique()),
        key=language.translated_options(f"h_{id_anriss}"),
        format_func=lambda cm: ui_text.in_locale(f"{cm / 100:.2f}"),
    )
    mu = left_column.selectbox(
        ui_text.PARAM_LABELS["mu"],
        sorted(event_meta["mu"].unique()),
        key=language.translated_options(f"mu_{id_anriss}"),
        format_func=lambda value: ui_text.in_locale(f"{value:g}"),
    )
    xsi = right_column.selectbox(
        ui_text.PARAM_LABELS["xsi"], sorted(event_meta["xsi"].unique()), key=f"xsi_{id_anriss}"
    )
    tau0 = left_column.selectbox(
        ui_text.PARAM_LABELS["tau0"], sorted(event_meta["tau0"].unique()), key=f"tau0_{id_anriss}"
    )
    scenario = Scenario(
        int(id_anriss), int(area), int(thickness_cm), float(mu), int(xsi), int(tau0)
    )
    return scenario, event_meta


def _update_lambda_ereignis(scenario: Scenario, event_meta):
    """lambda_Ereignis of the selected scenario (a client request).

    One scalar per scenario, the same for every pixel of the flow, so it
    comes from a one-row frame built from event_meta's d/mu/xsi/tau0 through
    enrich_with_probabilities (the probability join compute_ifk_default and
    the Rohdaten export use), not from a full gold read. Cached per scenario,
    so switching back and forth doesn't repeat the S3 read."""
    if st.session_state.get("_lambda_ereignis_key") == tuple(scenario):
        return
    st.session_state["_lambda_ereignis_key"] = tuple(scenario)
    match = event_meta[
        (event_meta["h"] == scenario.h)
        & (np.abs(event_meta["mu"] - scenario.mu) < _MU_MATCH_TOL)
        & (event_meta["xsi"] == scenario.xsi)
        & (event_meta["tau0"] == scenario.tau0)
    ]
    try:
        scenario_row = pd.DataFrame(
            [
                {
                    "id_anriss": scenario.id_anriss,
                    "mu": scenario.mu,
                    "xsi": scenario.xsi,
                    "tau0": scenario.tau0,
                    "h": scenario.h,
                    "d": float(match["d"].iloc[0]),
                }
            ]
        )
        enriched_row = ifk_and_raster.enrich_with_probabilities(scenario_row)
        st.session_state["_lambda_ereignis_value"] = float(enriched_row["lambda_ereignis"].iloc[0])
        st.session_state["_lambda_ereignis_failed"] = False
    except Exception:
        logger.exception("lambda_Ereignis failed for %s", scenario)
        st.session_state["_lambda_ereignis_value"] = None
        st.session_state["_lambda_ereignis_failed"] = True


def _start_hull_read(entry: AnrissEntry, id_anriss: int):
    """Starts the precomputed hull's S3 read unless one runs or the hull is
    there. It runs off the script thread: the page doesn't wait for it,
    and _hull_read_poll reruns the page once it's done. A read the map popup
    already started (anriss_prefetch) is used instead of a new one."""
    if not entry.needs_hull_fetch():
        return
    prefetched = anriss_prefetch.take(id_anriss, "hull")
    if prefetched is not None:
        entry.hull_read = prefetched
    else:
        entry.hull_read = _hull_reads.submit(data.get_anriss_hull_fragment, id_anriss)


def _store_hull_read(entry: AnrissEntry, id_anriss: int):
    """Moves a finished hull read's result into the entry; a running read stays."""
    read = entry.hull_read
    if read is None or not read.done():
        return
    entry.hull_read = None
    entry.hull_fetched = True
    try:
        entry.hull, entry.hull_failed = read.result(), False
    except data.HullFragmentNotIndexedError:
        entry.hull, entry.hull_failed = None, False
    except Exception:
        logger.exception("Precomputed hull read failed for Anriss %s", id_anriss)
        entry.hull, entry.hull_failed = None, True


@st.fragment(run_every=0.5)
def _hull_read_poll(entry: AnrissEntry, id_anriss: int):
    """ "Umhüllende wird geladen…" while the hull read runs. Once it's done, the
    page reruns if there's something to draw or say. An Anriss not in the hull
    index yet changes nothing, so it doesn't rerun: its read is retried on the
    next rerun, and a rerun here would retry it in a loop."""
    if entry.hull_read is None:
        return
    if not entry.hull_read.done():
        st.caption(ui_text.t("anriss.hull_loading"))
        return
    _store_hull_read(entry, id_anriss)
    if entry.hull is not None or entry.hull_failed:
        st.rerun()


def _scenarios(df=None, gold_not_ready=None, hull_not_indexed=None, failed=False) -> dict:
    return {
        "df": df,
        "gold_not_ready": gold_not_ready,
        "hull_not_indexed": hull_not_indexed,
        "failed": failed,
    }


def _fetch_scenarios(entry: AnrissEntry, id_anriss, status):
    """One S3 read per Anriss, every scenario at once (AnrissEntry.all_scenarios):
    filtering it per dropdown change is cheaper than a read per scenario.

    SIM_ANRISS (sorted by id_anriss) is tried first, then the SIM_SPATIAL
    kachel scan if the Anriss isn't in it yet; `status` lists the steps taken.
    A read the map popup already started (anriss_prefetch) is waited for
    instead of repeated; which of the two it took isn't known here."""
    try:
        prefetched = anriss_prefetch.take(int(id_anriss), "sim")
        if prefetched is not None:
            status.write(ui_text.t("anriss.step_sim_prefetched"))
            raw_df = prefetched.result()
        else:
            status.write(ui_text.t("anriss.step_sim"))
            raw_df = anriss_prefetch.load_sim_data(
                id_anriss, on_fallback=lambda: status.write(ui_text.t("anriss.step_fallback"))
            )
        entry.all_scenarios = _scenarios(df=_gold_to_display_df(raw_df))
    except data.GoldNotReadyError as e:
        entry.all_scenarios = _scenarios(gold_not_ready=e)
    except data.HullFragmentNotIndexedError as e:
        entry.all_scenarios = _scenarios(hull_not_indexed=e)
    except Exception:
        # Anything else (S3/network error, malformed gold data, ...) is shown,
        # instead of a page that looks stuck.
        logger.exception("Loading the scenarios of Anriss %s failed", id_anriss)
        entry.all_scenarios = _scenarios(failed=True)


def _scenario_rows(df_all, scenario: Scenario):
    mask = (
        (df_all["A"] == scenario.area)
        & (df_all["h"] == scenario.h)
        & (np.abs(df_all["mu"] - scenario.mu) < _MU_MATCH_TOL)
        & (df_all["xsi"] == scenario.xsi)
        & (df_all["tau0"] == scenario.tau0)
    )
    return df_all.loc[mask].reset_index(drop=True)


def _near_reach_limit(df_sim, release_xy) -> bool:
    """Whether the scenario's pixels come near GOLD_PIXEL_MAX_REACH_M. Gold
    pixels are clipped to that radius, so near it the flow may have been cut
    off rather than stopped on its own."""
    if df_sim.empty:
        return False
    dist = np.hypot(
        df_sim["x"].to_numpy(dtype=np.float64) - release_xy[0],
        df_sim["y"].to_numpy(dtype=np.float64) - release_xy[1],
    )
    return bool(dist.max() >= GOLD_PIXEL_MAX_REACH_M - _REACH_CIRCLE_NEAR_MARGIN_M)


def _write_geotiffs(df_sim):
    for var in _VARIABLES:
        st.session_state.tiff_bytes[var] = anriss_export.label_geotiff(
            event_export.event_layer_geotiff_bytes(df_sim, var), var
        )


def _build_geotiffs(df_sim, status):
    """The scenario's GeoTIFF downloads: a step of `status` on the Anriss's
    first load, else a spinner of their own (a scenario change)."""
    if status is not None:
        status.write(ui_text.t("anriss.step_map_layers"))
        _write_geotiffs(df_sim)
    else:
        with st.spinner(ui_text.t("anriss.spinner_map_layers")):
            _write_geotiffs(df_sim)


def _hull_sidebar(entry: AnrissEntry, id_anriss: int):
    # Whether the Umhüllende is there shows on the map (and in its layer box);
    # only a failed read, and a read still running, need saying.
    if entry.hull is None and entry.hull_failed:
        st.sidebar.error(ui_text.t("anriss.hull_error"))
    if entry.hull_read is not None:
        with st.sidebar:
            _hull_read_poll(entry, id_anriss)
    # Shown on the run after the click: the click's own rerun would clear it.
    flash = st.session_state.pop("_anriss_flash", None)
    if flash:
        st.sidebar.error(flash)
    if _SHOW_ADHOC_HULL_BUTTON and st.sidebar.button(
        ui_text.t("anriss.adhoc_hull_button"), width="stretch"
    ):
        st.session_state["_anriss_flash"] = _compute_adhoc_hull(
            entry.all_scenarios["df"], entry.all_scenarios, id_anriss
        )
        st.rerun()


def _load_scenario(entry: AnrissEntry, scenario: Scenario, release_xy):
    """Reads the Anriss if it isn't loaded yet and picks the scenario's pixels.

    The read shows its steps in one status in the main area (M16). It goes
    away once the Anriss is loaded; if the Anriss didn't load, it stays,
    collapsed, above the message that says why.

    Returns:
        (df_sim, show_reach_circle); df_sim is None if the Anriss didn't load.
    """
    slot, status = st.empty(), None
    if entry.needs_scenarios_fetch():
        status = slot.status(ui_text.t("anriss.loading"))
        _fetch_scenarios(entry, scenario.id_anriss, status)
    # A hull read that is done by now still frames the map (_map_bounds).
    _store_hull_read(entry, scenario.id_anriss)

    df_all = entry.all_scenarios["df"]
    df_sim, show_reach_circle = None, False
    if df_all is not None:
        df_sim = _scenario_rows(df_all, scenario)
        show_reach_circle = _near_reach_limit(df_sim, release_xy)
        if not df_sim.empty and st.session_state.tiff_bytes.get("depth") is None:
            _build_geotiffs(df_sim, status)
    if status is not None and df_all is None:
        status.update(label=ui_text.t("anriss.not_loaded"), state="error", expanded=False)
    elif status is not None:
        slot.empty()
    return df_sim, show_reach_circle


def _sidebar(id_anriss) -> _Loaded:
    """The sidebar, and the loading behind it (with its status in the main
    area, as before the map)."""
    st.sidebar.markdown("---")
    st.sidebar.markdown(ui_text.t("anriss.parameters"))
    scenario, event_meta = _parameter_inputs(id_anriss)
    _update_lambda_ereignis(scenario, event_meta)

    entry = st.session_state.anriss_cache.get(id_anriss)
    release_xy = (float(event_meta["x_anriss"].iloc[0]), float(event_meta["y_anriss"].iloc[0]))
    if scenario.area not in entry.release_geojson:
        entry.release_geojson[scenario.area] = _circle_geojson(
            release_xy, np.sqrt(event_meta["A"].iloc[0] / np.pi), id_anriss
        )
    # Depends only on the release point. quad_segs=64 (default 8, a visibly
    # faceted 32-gon at ~800 m) only smooths the outline.
    if entry.reach_circle_geojson is None:
        entry.reach_circle_geojson = _circle_geojson(
            release_xy, GOLD_PIXEL_MAX_REACH_M, id_anriss, quad_segs=64
        )
    _start_hull_read(entry, scenario.id_anriss)

    # Picked in the map's own variable switcher; kept across Anrisse.
    view_target = st.session_state.setdefault("_anriss_view_target", "depth")
    if st.session_state.get("_last_param_key") != tuple(scenario):
        st.session_state.tiff_bytes = {var: None for var in _VARIABLES}
        st.session_state["_last_param_key"] = tuple(scenario)
    df_sim, show_reach_circle = _load_scenario(entry, scenario, release_xy)

    _hull_sidebar(entry, scenario.id_anriss)
    return _Loaded(
        scenario,
        entry,
        df_sim,
        view_target,
        entry.release_geojson[scenario.area],
        entry.reach_circle_geojson,
        show_reach_circle,
    )


def _back_button(pages: Mapping[str, StreamlitPage]):
    """ "Anriss abwählen" goes back to the view the Anriss was opened from
    (_return_view, set by its click handler), else to Simulierte Ereignisse (e.g. after
    the Anriss-ID lookup). That view restores its map as it was at the click
    (pan/zoom, Anrissfläche filter, the Anriss highlighted), and the URL gets
    that view's link. A static label with a back arrow, not "Zurück zu
    {view}": the client preferred it."""
    target = st.session_state.get("_return_view", overview.VIEW_MODE)
    if st.button(ui_text.t("anriss.deselect"), key="btn_zurueck"):
        st.session_state.selected_id_anriss = None
        st.switch_page(pages[target], query_params=_RETURN_QUERY[target]())


def _load_problem(cached: dict, id_anriss: int) -> bool:
    """Shows why the Anriss didn't load; False if it did."""
    if cached["hull_not_indexed"] is not None:
        st.warning(ui_text.t("anriss.hull_not_indexed", id=id_anriss))
    elif cached["gold_not_ready"] is not None:
        st.warning(ui_text.anriss_gold_not_ready(cached["gold_not_ready"].pending_kacheln))
    elif cached["failed"]:
        st.error(ui_text.t("anriss.load_error", id=id_anriss))
    else:
        return False
    return True


def _map_bounds(hull, df_sim):
    """The map's frame, computed once per Anriss so it stays put across
    scenarios: the Umhüllende's bbox (every scenario pooled) plus a margin,
    else the scenario's own extent."""
    if hull is not None:
        margin_m = _MAP_VIEWPORT_BUFFER_M
        xs = np.array([hull["xmin"], hull["xmax"]]) + [-margin_m, margin_m]
        ys = np.array([hull["ymin"], hull["ymax"]]) + [-margin_m, margin_m]
    else:
        xs = df_sim["x"].to_numpy(dtype=np.float64)
        ys = df_sim["y"].to_numpy(dtype=np.float64)
    # All 4 corners: LV95 -> WGS84 isn't axis-aligned, so two opposite
    # corners can miss the true min/max.
    x_corners, y_corners = np.meshgrid(xs, ys)
    corner_lons, corner_lats = _TO_WGS84.transform(x_corners.ravel(), y_corners.ravel())
    return [
        [float(np.min(corner_lats)), float(np.min(corner_lons))],
        [float(np.max(corner_lats)), float(np.max(corner_lons))],
    ]


def _overlays(loaded: _Loaded):
    """Outline layers, bottom first. The 800 m circle is always in the layer
    box but only on by default when the scenario's pixels come near it; bold,
    since it's opt-in."""
    hull = loaded.entry.hull
    return [
        {
            "id": "hull",
            "label": ui_text.t("anriss.layer_hull"),
            "geojson": hull["hull_geojson"] if hull else None,
            "color": "#0d47a1",
            "width": 2,
            "dash": None,
            "visible": True,
        },
        {
            "id": "hull_adhoc",
            "label": ui_text.t("anriss.layer_hull_adhoc"),
            "geojson": st.session_state.hull_geojson,
            "color": "#ff8f00",
            "width": 2,
            "dash": [3, 3],
            "visible": True,
        },
        {
            "id": "release",
            "label": ui_text.t("anriss.layer_release"),
            "geojson": loaded.release_geojson,
            "color": "#000000",
            "width": 2,
            "dash": None,
            "visible": True,
        },
        {
            "id": "reach",
            "label": ui_text.t("anriss.layer_reach", reach_m=GOLD_PIXEL_MAX_REACH_M),
            "geojson": loaded.reach_circle_geojson,
            "color": "#e53935",
            "width": 3,
            "dash": [10 / 3, 2],
            "opacity": 0.9,
            "visible": loaded.show_reach_circle,
        },
    ]


def _map(loaded: _Loaded, servers: dict):
    entry, view_target = loaded.entry, loaded.view_target
    if entry.map_bounds is None:
        entry.map_bounds = _map_bounds(entry.hull, loaded.df_sim)
    cells_geojson, cells_legend = _continuous_cells_geojson(
        loaded.df_sim, view_target, cmap="viridis"
    )
    # Keyed per Anriss: a new Anriss remounts the map (framed on map_bounds),
    # a scenario or variable change only swaps the data, keeping pan/zoom.
    picked = anriss_result_map(
        bounds=entry.map_bounds,
        cells_geojson=cells_geojson,
        # The language too: the hover texts are in it.
        cells_version=f"{tuple(loaded.scenario)}|{view_target}|{ui_text.language()}",
        cells_label=ui_text.t(f"variable.{view_target}"),
        legend=cells_legend,
        overlays=_overlays(loaded),
        variables=[{"key": v, "label": _variable_with_unit(v)} for v in _VARIABLES],
        active_variable=view_target,
        pmtiles_port=servers["pmtiles_port"],
        pmtiles_path_prefix=servers["pmtiles_path_prefix"],
        key=f"anriss_map_{st.session_state.selected_id_anriss}",
    )
    # Streamlit keeps returning the last pick on later reruns; it only counts
    # when it differs from what's shown.
    if picked and picked.get("variable") != view_target:
        st.session_state["_anriss_view_target"] = picked["variable"]
        st.rerun()


def _geotiff_downloads(scenario: Scenario) -> list[dict]:
    if not st.session_state.tiff_bytes.get("depth"):
        return []
    stem = anriss_export.simulation_file_stem(*scenario)
    return [
        dict(
            label=ui_text.download_label(
                _variable_with_unit(var), "GeoTIFF", len(st.session_state.tiff_bytes[var])
            ),
            data=st.session_state.tiff_bytes[var],
            file_name=anriss_export.geotiff_file_name(stem, var),
            mime="image/tiff",
        )
        for var in _VARIABLES
    ]


def _rohdaten(entry: AnrissEntry, id_anriss: int) -> dict:
    """The Rohdaten table, built on first use and kept with the Anriss."""
    if entry.rohdaten is None:
        # Built eagerly (fast enough not to need a
        # "vorbereiten" click): an extra S3 read (probability_lookup) and a
        # join over every scenario, paid once per Anriss.
        with st.spinner(ui_text.t("anriss.spinner_rohdaten")):
            try:
                enriched = ifk_and_raster.enrich_with_probabilities(entry.all_scenarios["df"])
                entry.rohdaten = {"df": enriched, "failed": False}
            except Exception:
                logger.exception("Rohdaten export failed for Anriss %s", id_anriss)
                entry.rohdaten = {"df": None, "failed": True}
    return entry.rohdaten


def _rohdaten_download(rohdaten: dict, id_anriss: int) -> list[dict]:
    if rohdaten["failed"]:
        return []
    csv = anriss_export.rohdaten_csv_bytes(rohdaten["df"])
    return [
        dict(
            label=ui_text.download_label(ui_text.t("anriss.rohdaten_download"), "CSV", len(csv)),
            data=csv,
            file_name=anriss_export.rohdaten_file_name(id_anriss),
            mime="text/csv",
            key=f"rohdaten_dl_{id_anriss}",
        )
    ]


def _hull_downloads(entry: AnrissEntry, id_anriss: int) -> list[dict]:
    """The precomputed Umhüllende the map draws, as a GeoPackage (LV95) and as
    a GeoJSON (WGS84). No download while it is still loading (_hull_read_poll reruns
    the page once it's there) or if the Anriss has none."""
    if entry.hull is None:
        return []
    geopackage = anriss_export.umhuellende_geopackage_bytes(id_anriss, entry.hull)
    geojson = anriss_export.umhuellende_geojson_bytes(id_anriss, entry.hull)
    return [
        dict(
            label=ui_text.download_label(
                ui_text.t("anriss.hull_download_geopackage"), "GeoPackage", len(geopackage)
            ),
            data=geopackage,
            file_name=anriss_export.umhuellende_file_name(id_anriss, "gpkg"),
            mime="application/geopackage+sqlite3",
            key=f"hull_geopackage_dl_{id_anriss}",
        ),
        dict(
            label=ui_text.download_label(
                ui_text.t("anriss.hull_download_geojson"), "GeoJSON", len(geojson)
            ),
            data=geojson,
            file_name=anriss_export.umhuellende_file_name(id_anriss, "geojson"),
            mime="application/geo+json",
            key=f"hull_geojson_dl_{id_anriss}",
        ),
    ]


def _adhoc_hull_download(id_anriss: int) -> list[dict]:
    """Only after "Ad-hoc Umhüllende berechnen" (_SHOW_ADHOC_HULL_BUTTON)."""
    if not st.session_state.hull_geojson:
        return []
    hull_path = st.session_state.hull_geojson_path
    if hull_path and Path(hull_path).exists():
        hull_bytes, hull_mime = Path(hull_path).read_bytes(), "application/geo+json"
    else:
        hull_bytes, hull_mime = json.dumps(st.session_state.hull_geojson), "application/json"
    return [
        dict(
            label=ui_text.download_label(
                ui_text.t("anriss.adhoc_hull_download"), "GeoJSON", len(hull_bytes)
            ),
            data=hull_bytes,
            file_name=anriss_export.adhoc_umhuellende_file_name(id_anriss),
            mime=hull_mime,
        )
    ]


def _downloads(loaded: _Loaded):
    """Every download in one grid of three columns, the same width each,
    then what they hold."""
    id_anriss = loaded.scenario.id_anriss
    st.header(ui_text.t("anriss.export_heading"), anchor=False)
    rohdaten = _rohdaten(loaded.entry, id_anriss)
    buttons = [
        *_geotiff_downloads(loaded.scenario),
        *_rohdaten_download(rohdaten, id_anriss),
        *_hull_downloads(loaded.entry, id_anriss),
        *_adhoc_hull_download(id_anriss),
    ]
    for start in range(0, len(buttons), 3):
        for column, button in zip(st.columns(3), buttons[start : start + 3]):
            column.download_button(**button, width="stretch", on_click="ignore")
    if rohdaten["failed"]:
        st.error(ui_text.t("anriss.rohdaten_error"))
    st.caption(ui_text.t("anriss.export_caption"))
    with st.expander(ui_text.t("anriss.rohdaten_model")):
        st.markdown(
            ui_text.t("anriss.rohdaten_units")
            + f"| {ui_text.t('anriss.rohdaten_header_column')} "
            + f"| {ui_text.t('anriss.rohdaten_header_meaning')} |\n|---|---|\n"
            + "\n".join(
                f"| `{column}` | {ui_text.t(f'anriss.rohdaten_meaning.{key}')} |"
                for column, key in anriss_export.ROHDATEN_COLUMNS
            )
        )


def _stats(df_sim, view_target):
    """The scenario's key numbers: its values on the map, then its
    rate and return period."""
    st.header(ui_text.t("anriss.stats_heading"), anchor=False)
    label = _variable_with_unit(view_target)
    max_column, mean_column, points_column, rate_column, return_period_column = st.columns(5)
    max_column.metric(
        ui_text.t("anriss.metric_max", label=label),
        ui_text.in_locale(f"{df_sim[view_target].max():.2f}"),
    )
    mean_column.metric(
        ui_text.t("anriss.metric_mean", label=label),
        ui_text.in_locale(f"{df_sim[view_target].mean():.2f}"),
    )
    points_column.metric(ui_text.t("anriss.metric_points"), ui_text.fmt_ch(len(df_sim)))
    lambda_ereignis = st.session_state.get("_lambda_ereignis_value")
    if st.session_state.get("_lambda_ereignis_failed") or not lambda_ereignis:
        rate_column.caption(ui_text.t("anriss.lambda_error"))
        return
    rate, return_period = ui_text.anriss_rate(lambda_ereignis)
    rate_column.metric(ui_text.t("anriss.metric_rate"), rate)
    return_period_column.metric(ui_text.t("area.return_period_label"), return_period)


def _main(loaded: _Loaded, pages: Mapping[str, StreamlitPage], servers: dict):
    _back_button(pages)
    df_sim = loaded.df_sim
    if not _load_problem(loaded.entry.all_scenarios, loaded.scenario.id_anriss):
        if loaded.view_target in _VARIABLES and df_sim is not None and not df_sim.empty:
            _map(loaded, servers)
        else:
            st.write(ui_text.t("anriss.no_data"))
    if df_sim is None:
        return
    if not df_sim.empty:
        _stats(df_sim, loaded.view_target)
    with downloads_section():
        _downloads(loaded)
    downloads_cue()


def render(pages: Mapping[str, StreamlitPage], servers: dict, link_error: str | None):
    """The view: the header, the scenario sidebar, the map, the numbers and
    the downloads.

    Args:
        pages: app.py's pages by view, which "Anriss abwählen" goes back to.
        servers: pmtiles_port and pmtiles_path_prefix of the tile sidecar.
        link_error: select_from_link's message for a bad link, or None.
    """
    id_anriss = st.session_state.selected_id_anriss
    page_header(
        ui_text.t("nav.anriss") if id_anriss is None else ui_text.nav_anriss(id_anriss),
        ui_text.t("header.anriss_hint"),
    )
    if link_error:
        st.error(link_error)
    if id_anriss is None:
        # Only after a bad link: without one, app.py opens Simulierte Ereignisse instead.
        # The sidebar's "Anriss öffnen" (app.py) picks another one.
        return
    _main(_sidebar(id_anriss), pages, servers)
