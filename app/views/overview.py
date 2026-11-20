"""Simulierte Ereignisse: every Anriss on one map, and how much of the lake is done.

A click on "Anriss öffnen" in the map's popup opens the Anriss view. A link
can set where the map starts: /?z=<zoom>&lat=<lat>&lon=<lon> (WGS84).
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

import streamlit as st
from streamlit.navigation.page import StreamlitPage

import ui_text
from overview_component import maplibre_overview
from ui_common import (
    CANTON_LAT_RANGE,
    CANTON_LON_RANGE,
    anriss_query_params,
    load_coverage,
    page_header,
)

VIEW_MODE = "Overview (All Events)"

# Served from S3 by pmtiles_server.py. The tileset has two layers (see
# overview_preprocessing.py): "anrisse" (points, low zoom) and
# "anrisse_circles" (circle polygons, high zoom).
PMTILES_FILENAME = "overview_anrisse_maxi.pmtiles"
SOURCE_LAYER = "anrisse_circles"

# What a link's map view may hold: the map's zoom range (MIN_ZOOM/MAX_ZOOM in
# frontend/src/overview/map.ts) and a centre in Kanton Bern.
_ZOOM_RANGE = (7.0, 19.0)
_VIEWPORT_PARAMS = {
    "z": ("zoom", _ZOOM_RANGE),
    "lat": ("lat", CANTON_LAT_RANGE),
    "lon": ("lon", CANTON_LON_RANGE),
}


@dataclass(frozen=True)
class Stats:
    """The numbers the view shows, read once at app.py's cold start."""

    manifest: dict  # data.catalog_overview_stats(): planned counts and the map centre
    gold: dict  # data.gold_coverage_stats(): counts with finalized gold data
    sim_count: int
    gold_kacheln: int
    total_kacheln: int
    as_of: datetime | None  # when the newest gold file was written; None without gold


def viewport_from_query(params: Mapping[str, str]) -> dict | None:
    """The map view a link asks for, as the map's {lat, lon, zoom}.

    Args:
        params: the URL's query params (st.query_params).

    Returns:
        None if the link has none of z, lat and lon.

    Raises:
        ValueError: one of them is missing, not a number, or out of range.
    """
    if not any(key in params for key in _VIEWPORT_PARAMS):
        return None
    view = {}
    for key, (name, (low, high)) in _VIEWPORT_PARAMS.items():
        if key not in params:
            raise ValueError(f"{key} is missing")
        try:
            value = float(params[key])
        except ValueError:
            raise ValueError(f"{key}={params[key]!r} is not a number") from None
        if not low <= value <= high:  # also rejects nan
            raise ValueError(f"{key}={value} is outside {low}..{high}")
        view[name] = value
    return view


def viewport_query(view: dict) -> dict[str, str]:
    """The query params that make a link open the map at `view` ({lat, lon, zoom})."""
    return {"z": f"{view['zoom']:.2f}", "lat": f"{view['lat']:.5f}", "lon": f"{view['lon']:.5f}"}


def return_query_params() -> dict[str, str] | None:
    """Query params for coming back from the Anriss view ("Anriss abwählen"):
    the map view at the last "Anriss öffnen" click, so the URL shows where the
    user was. None without a click, or if that view is one a link can't hold
    (a centre outside Kanton Bern)."""
    last_view = st.session_state.get("_overview_last_view")
    if last_view is None:
        return None
    params = viewport_query(last_view)
    try:
        viewport_from_query(params)
    except ValueError:
        return None
    return params


def _start_view() -> dict | None:
    """Where the map starts: the view at the last "Anriss öffnen" click in
    this session, else a link's view, else None (the map's own saved view or
    default)."""
    last_view = st.session_state.get("_overview_last_view")
    if last_view is not None:
        return last_view
    try:
        return viewport_from_query(st.query_params)
    except ValueError:
        st.warning(ui_text.t("overview.bad_viewport_link"))
        return None


def _map(stats: Stats, servers: dict):
    """Draws the map and returns its click value (None without a click)."""
    # The Prozessquellen layer is its own PMTiles source, fetched by the
    # component from pmtiles_server.py: inlining it as GeoJSON cost 10-30 s per
    # rerun.
    view = _start_view() or {}
    return maplibre_overview(
        center_lat=view.get("lat", stats.manifest["center_lat"]),
        center_lon=view.get("lon", stats.manifest["center_lon"]),
        pmtiles_port=servers["pmtiles_port"],
        pmtiles_path_prefix=servers["pmtiles_path_prefix"],
        coverage_version=load_coverage()[0],
        pmtiles_filename=PMTILES_FILENAME,
        source_layer=SOURCE_LAYER,
        initial_zoom=view.get("zoom"),
        initial_active_areas=st.session_state.get("_overview_last_areas"),
        highlight_id_anriss=st.session_state.get("_overview_last_selected_id"),
    )


def _handle_click(map_value, anriss_page: StreamlitPage):
    """Opens the clicked Anriss, remembering the map's view, legend filter and
    the Anriss, so "Anriss abwählen" returns to the same map.

    map_value is {'id_anriss', 'nonce', 'view', 'active_areas'} after the "Anriss
    öffnen" popup click (frontend/src/overview/map.ts). Streamlit returns the
    same value on every rerun, so the nonce tells a new click from the one
    already handled: without it, coming back here would open the same Anriss
    again. The IFK and Raster-Karten maps do the same."""
    if map_value is None or st.session_state.get("_overview_anriss_nonce") == map_value.get(
        "nonce"
    ):
        return
    st.session_state["_overview_anriss_nonce"] = map_value.get("nonce")
    st.session_state["_overview_last_view"] = map_value.get("view")
    st.session_state["_return_view"] = VIEW_MODE
    st.session_state["_overview_last_areas"] = map_value.get("active_areas")
    st.session_state["_overview_last_selected_id"] = int(map_value["id_anriss"])
    st.session_state["_anriss_pending"] = int(map_value["id_anriss"])
    st.session_state.selected_id_anriss = int(map_value["id_anriss"])
    st.switch_page(anriss_page, query_params=anriss_query_params(map_value["id_anriss"]))


def stat_progress(available: int, total: int) -> tuple[str, float | None]:
    """How far a count is: ("vollständig", None) once available reaches the
    total, else ("von y (z %)", the fraction for the progress bar). The
    percentage rounds down, so an incomplete count never reads 100 %."""
    if available >= total:
        return ui_text.t("overview.stats_complete"), None
    fraction = max(available, 0) / total
    percent = math.floor(fraction * 1000) / 10
    text = ui_text.t(
        "overview.stats_partial",
        total=ui_text.fmt_ch(total),
        percent=ui_text.fmt_ch(percent, digits=1),
    )
    return text, fraction


def _stat(label: str, available: int, total: int):
    """One count: what is computed, then "vollständig" or "von <total>" and
    how far it is. Each number shows once."""
    st.metric(label, ui_text.fmt_ch(available))
    text, fraction = stat_progress(available, total)
    if fraction is None:
        st.caption(text)
    else:
        st.progress(fraction, text=text)


def _counts(stats: Stats) -> list[tuple[str, int, int]]:
    """(label, computed, planned) in the order the data nests:
    Prozessquellen hold Anrisse in Grössenklassen, each with its Simulationen;
    the Kacheln are the area they cover."""
    planned, gold = stats.manifest, stats.gold
    return [
        (ui_text.t("overview.metric_pq"), gold["pq_count"], planned["pq_count"]),
        (ui_text.t("overview.metric_anrisse"), gold["anriss_count"], planned["anriss_count"]),
        (ui_text.t("overview.metric_areas"), gold["area_count"], planned["area_count"]),
        (ui_text.t("overview.metric_sims"), gold["sim_count"], stats.sim_count),
        (ui_text.t("overview.metric_kacheln"), stats.gold_kacheln, stats.total_kacheln),
    ]


def stats_summary(stats: Stats) -> str:
    """The one line that opens the Datenstand: "Datenstand · vollständig"
    once every count is complete, else "Datenstand · unvollständig"."""
    complete = all(available >= total for _, available, total in _counts(stats))
    state = (
        ui_text.t("overview.stats_complete") if complete else ui_text.t("overview.stats_incomplete")
    )
    return ui_text.t("overview.stats_summary", state=state)


def _render_stats(header_row, stats: Stats):
    """The Datenstand at the right end of the header: one line that
    is visible without scrolling and opens the counts over the map, so the
    map doesn't move."""
    counts = _counts(stats)
    with header_row.popover(stats_summary(stats), key="overview_stats"):
        st.caption(ui_text.overview_stats_caption(stats.as_of))
        # Read left to right, row by row: three counts, then two. Sized by
        # .st-key-overview_stats_counts in app.css.
        with st.container(key="overview_stats_counts"):
            for row in (counts[:3], counts[3:]):
                for column, (label, available, total) in zip(st.columns(3), row):
                    with column:
                        _stat(label, available, total)


def render(stats: Stats, servers: dict, anriss_page: StreamlitPage):
    """The view: the header with the Datenstand, and the map.

    Args:
        stats: the numbers from app.py's cold start.
        servers: pmtiles_port and pmtiles_path_prefix of the tile sidecar.
        anriss_page: the Anriss view's page, opened by a click.
    """
    header_row = page_header(ui_text.t("nav.overview"), ui_text.t("header.overview_hint"))
    _render_stats(header_row, stats)
    _handle_click(_map(stats, servers), anriss_page)
