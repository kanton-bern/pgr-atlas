"""IFK-Berechnung: the intensity-frequency curves of one 5 m pixel, or of an
area (views/ifk_area.py; the view shows one or the other).

A click on a pixel of a finished (gold) kachel selects it; the view shows a
summary row (the pixel, its Anrisse, the highest return period, "Link
kopieren"), its three curves, their downloads and, as circles on the map,
the Anrisse that reach it. A circle's "Anriss öffnen" opens the Anriss view.
A link can select a pixel: /ifk?x=<E>&y=<N> (LV95 metres), and each pixel
click writes the link.

The map and everything below it are one fragment, so a pixel click reruns
only that part. The Experten-Modus sidebar (views/expert_mode.py) and the
area's sidebar (ifk_area.render_sidebar) are drawn by app.py, outside the
fragment.
"""

import json
import logging
from collections.abc import Mapping

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from shapely.geometry import Point
from streamlit.navigation.page import StreamlitPage
from streamlit.runtime.scriptrunner import get_script_run_ctx

import ifk_charts
import ifk_export
import ifk_prefetch
import language
import ui_text
from copy_link_component import copy_link_button
from downloads_cue_component import downloads_cue, downloads_section
from ifk_map_component import ifk_pixel_map
from kachel_coverage import pixel_in_coverage
from probe_core.data_lake import data_interface as data
from probe_core.derivate import ifk_and_raster
from raster_overlay import colormap_gradient_css
from ui_common import (
    anriss_query_params,
    check_in_canton,
    expert_chip,
    load_coverage,
    page_header,
    query_floats,
    shape_label,
    snap_to_pixel,
)
from views import expert_mode, ifk_area

VIEW_MODE = "IFK"

logger = logging.getLogger(__name__)


def pixel_from_query(params: Mapping[str, str]) -> tuple[float, float] | None:
    """The pixel a link asks for, snapped to the pixel lattice.

    Args:
        params: the URL's query params (st.query_params).

    Returns:
        None if the link has neither x nor y.

    Raises:
        ValueError: one of them is missing or not a number, or the point is
            outside Kanton Bern.
    """
    coords = query_floats(params, ("x", "y"))
    if coords is None:
        return None
    check_in_canton(*coords)
    return snap_to_pixel(coords[0]), snap_to_pixel(coords[1])


def pixel_query(pixel: tuple[float, float]) -> dict[str, str] | None:
    """The query params that make a link select `pixel`; None if a link can't
    hold it (outside Kanton Bern)."""
    params = {"x": f"{pixel[0]:.1f}", "y": f"{pixel[1]:.1f}"}
    try:
        pixel_from_query(params)
    except ValueError:
        return None
    return params


def return_query_params() -> dict[str, str] | None:
    """Query params for coming back from the Anriss view ("Anriss abwählen"):
    the selected pixel, if any."""
    pixel = st.session_state.get("_ifk_pending")
    return None if pixel is None else pixel_query(pixel)


def _rerun():
    """Reruns the fragment. A click handled during a full-app run (one that
    was already running when the click came) reruns the app instead:
    Streamlit only allows a fragment-scoped rerun in a fragment rerun."""
    run_context = get_script_run_ctx()
    in_fragment_run = run_context is not None and bool(run_context.fragment_ids_this_run)
    st.rerun(scope="fragment" if in_fragment_run else "app")


def _select(pixel, prefetch_client) -> bool:
    """Selects the pixel, in place of a selected area. Returns True if there
    was an area (ifk_area.clear)."""
    had_area = ifk_area.clear()
    st.session_state["_ifk_pending"] = pixel
    st.session_state["_ifk_prefetch_client"] = prefetch_client
    # A new pixel replaces the ghost square of a deselected one.
    st.session_state.pop("_ifk_deselected_pixel", None)
    language.set_query_params(pixel_query(pixel) or {})
    return had_area


def _select_from_link():
    """Selects a link's pixel unless it is already the selected one. Clicks and
    "Pixel abwählen" keep the URL in step, so they differ only when the page
    was opened from a link."""
    try:
        pixel = pixel_from_query(st.query_params)
    except ValueError:
        st.warning(ui_text.t("ifk.bad_pixel_link"))
        return
    if pixel is not None and pixel != st.session_state.get("_ifk_pending"):
        _select(pixel, prefetch_client=None)


def _anriss_legend_payload(vmin_log, vmax_log, cmap="YlOrRd"):
    """Colour-scale legend of the contributing-Anriss circles. vmin_log and
    vmax_log are the log10(lambda_ereignis_sum) bounds the circles are
    coloured by, so the legend always matches the map. lambda_ereignis_sum is
    a tiny rate (around 1e-9), hence the power-of-ten labels."""
    vmid_log = (vmin_log + vmax_log) / 2
    return {
        "gradient": colormap_gradient_css(plt.get_cmap(cmap)),
        "vmin_label": ui_text.fmt_ch(10**vmin_log, digits=3),
        "vmid_label": ui_text.fmt_ch(10**vmid_log, digits=3),
        "vmax_label": ui_text.fmt_ch(10**vmax_log, digits=3),
    }


def _anriss_events_geojson(df, cmap="YlOrRd"):
    """The contributing Anrisse (compute_ifk_default's anriss_events) as
    true-scale circles, radius sqrt(A/pi), reprojected to WGS84 here.

    Colours (log-scale lambda_ereignis_sum) are computed here too; the map
    only reads the stored fillColor, so no coordinate or colour maths happens
    in JS.

    Returns (geojson, legend), both None if nothing has a positive
    lambda_ereignis_sum."""
    if df is None or df.empty:
        return None, None
    rates = df["lambda_ereignis_sum"].to_numpy(dtype=np.float64)
    valid = rates > 0
    if not np.any(valid):
        return None, None

    log_rates = np.log10(np.where(valid, rates, np.nan))
    vmin, vmax = float(np.nanmin(log_rates[valid])), float(np.nanmax(log_rates[valid]))
    span = max(vmax - vmin, 1e-12)  # one Anriss alone must not divide by zero
    ramp_position = np.clip((log_rates - vmin) / span, 0.0, 1.0)
    ramp_position = np.where(valid, ramp_position, 0.0)
    rgb_ints = (plt.get_cmap(cmap)(ramp_position)[:, :3] * 255).astype(np.uint32)
    packed = (rgb_ints[:, 0] << 16) | (rgb_ints[:, 1] << 8) | rgb_ints[:, 2]
    hex_colors = [f"#{rgb:06x}" for rgb, is_valid in zip(packed.tolist(), valid) if is_valid]

    valid_df = df.loc[valid].reset_index(drop=True)
    radii = np.sqrt(valid_df["anrissflaeche"].to_numpy(dtype=np.float64) / np.pi)
    circles = [
        Point(x, y).buffer(radius) for x, y, radius in zip(valid_df["x"], valid_df["y"], radii)
    ]
    circles_wgs84 = gpd.GeoDataFrame(
        {
            "id_anriss": valid_df["id_anriss"].astype(int),
            "anrissflaeche": valid_df["anrissflaeche"],
            "lambda_ereignis_sum": valid_df["lambda_ereignis_sum"],
            "fillColor": hex_colors,
        },
        geometry=circles,
        crs=data.CRS_LV95,
    ).to_crs("EPSG:4326")
    return json.loads(circles_wgs84.to_json()), _anriss_legend_payload(vmin, vmax, cmap)


def _computed_or_none(pixel, prefetched):
    """The production result for `pixel`, or None if it fails: it is only the
    comparison line, so it must not take the Experten-Modus curve down."""
    try:
        if prefetched is not None:
            return prefetched.result()
        return ifk_and_raster.compute_ifk_default(*pixel)
    except Exception:
        logger.exception("IFK production computation failed for pixel %s", pixel)
        return None


def _result(pixel):
    """The pixel's IFK result {'data', 'failed', 'original'}, computed once
    per pixel and override state (the Experten-Modus signature: an edit on the
    same pixel must recompute).

    'original' is the production result next to an Experten-Modus one (None
    without overrides, or if it failed). It depends on the pixel only, so it
    is kept under '_ifk_original' across override edits."""
    expert_sig = expert_mode.cache_signature()
    if st.session_state.get("_ifk_last_pixel") != pixel:
        st.session_state.pop("_ifk_original", None)
    if (
        st.session_state.get("_ifk_last_pixel") != pixel
        or st.session_state.get("_ifk_last_expert_sig") != expert_sig
    ):
        st.session_state["_ifk_last_pixel"] = pixel
        st.session_state["_ifk_last_expert_sig"] = expert_sig
        st.session_state.pop("_ifk_result", None)
    if "_ifk_result" not in st.session_state:
        kwargs = expert_mode.override_kwargs(include_anriss=True)
        # The map popup already started the production computation for this
        # pixel (ifk_prefetch). Without overrides it is the result, with
        # overrides it is the original to compare with.
        prefetched = ifk_prefetch.take(st.session_state.get("_ifk_prefetch_client") or "", *pixel)
        with st.spinner(ui_text.t("ifk.spinner")):
            try:
                if kwargs:
                    data = ifk_and_raster.compute_ifk_default(*pixel, **kwargs)
                    if "_ifk_original" not in st.session_state:
                        st.session_state["_ifk_original"] = _computed_or_none(pixel, prefetched)
                    original = st.session_state["_ifk_original"]
                else:
                    data = (
                        prefetched.result()
                        if prefetched is not None
                        else ifk_and_raster.compute_ifk_default(*pixel)
                    )
                    # Kept for when Experten-Modus is switched on for this pixel.
                    st.session_state["_ifk_original"] = data
                    original = None
                st.session_state["_ifk_result"] = {
                    "data": data,
                    "failed": False,
                    "original": original,
                }
            except Exception:
                logger.exception("IFK computation failed for pixel %s", pixel)
                st.session_state["_ifk_result"] = {"data": None, "failed": True, "original": None}
    return st.session_state["_ifk_result"]


def _no_curves_note(pixel, curves):
    """Above the map, so a pixel outside the
    finished area doesn't need a scroll to see why nothing came back. Inside a
    finished kachel the data is complete: empty curves mean no simulated
    process reaches the pixel, not a missing tile."""
    if not all(curve.empty for curve in curves.values()):
        return
    if pixel_in_coverage(load_coverage()[1], *pixel):
        st.info(ui_text.ifk_no_process(*pixel))
    else:
        st.info(ui_text.ifk_no_kachel(*pixel))


def _map(pixel, circles, outline, servers: dict, default_center: tuple[float, float]):
    """Draws the map and returns its click value (None without a click).

    Args:
        circles: (geojson, legend) of the selected pixel's Anrisse.
        outline: the outline of the selected area's Anrisse.

    It starts at the view of the last "Anriss öffnen" click, so "Anriss
    abwählen" comes back to the same place, else at the manifest's centre. A
    selected pixel sets its own zoom (frontend/src/overview_ifk/map.ts)."""
    anriss_circles_geojson, anriss_legend = circles
    last_view = st.session_state.get("_ifk_last_view") or {}
    return ifk_pixel_map(
        center_lat=last_view.get("lat", default_center[0]),
        center_lon=last_view.get("lon", default_center[1]),
        coverage_version=load_coverage()[0],
        selected_pixel=pixel,
        selected_selection=st.session_state.get(ifk_area.SELECTION),
        area_too_large=ifk_area.selection_too_large(),
        anriss_circles_geojson=anriss_circles_geojson,
        anriss_outline_geojson=outline,
        anriss_legend=anriss_legend,
        pmtiles_port=servers["pmtiles_port"],
        pmtiles_path_prefix=servers["pmtiles_path_prefix"],
        initial_zoom=last_view.get("zoom"),
        initial_active_areas=st.session_state.get("_ifk_last_areas"),
        highlight_id_anriss=st.session_state.get("_ifk_last_selected_id"),
        highlight_pixel=st.session_state.get("_ifk_deselected_pixel"),
    )


def _handle_click(map_value, anriss_page: StreamlitPage):
    """A pixel click ({'x', 'y', 'nonce', 'view', 'prefetch_client'}) selects
    the pixel; a circle's "Anriss öffnen" ({'id_anriss', 'nonce', 'view',
    'active_areas'}) opens the Anriss, remembering the map's view for the way
    back (see frontend/src/overview_ifk/map.ts); a drawn area or "Löschen"
    ({'selection', 'nonce'}) goes to ifk_area.

    Streamlit returns the component's last value on every rerun, so the nonce
    tells a new click from the one already handled. "Pixel abwählen" clears
    the pixel server-side only: without the nonce the old click would select
    it again on the next rerun."""
    if map_value is None:
        return
    if "id_anriss" in map_value:
        _open_anriss(map_value, anriss_page)
    elif "selection" in map_value:
        ifk_area.handle_map_selection(map_value)
    else:
        _pick_pixel(map_value)


def _open_anriss(map_value, anriss_page: StreamlitPage):
    if st.session_state.get("_ifk_anriss_nonce") == map_value.get("nonce"):
        return
    st.session_state["_ifk_anriss_nonce"] = map_value.get("nonce")
    st.session_state["_ifk_last_view"] = map_value.get("view")
    st.session_state["_return_view"] = VIEW_MODE
    st.session_state["_ifk_last_areas"] = map_value.get("active_areas")
    st.session_state["_ifk_last_selected_id"] = int(map_value["id_anriss"])
    st.session_state["_anriss_pending"] = int(map_value["id_anriss"])
    st.session_state.selected_id_anriss = int(map_value["id_anriss"])
    st.switch_page(anriss_page, query_params=anriss_query_params(map_value["id_anriss"]))


def _pick_pixel(map_value):
    if st.session_state.get("_ifk_pixel_nonce") == map_value.get("nonce"):
        return
    st.session_state["_ifk_pixel_nonce"] = map_value.get("nonce")
    had_area = _select(
        (float(map_value["x"]), float(map_value["y"])), map_value.get("prefetch_client")
    )
    if had_area:
        st.rerun()  # the whole page: the sidebar still shows the area
    _rerun()


def _deselect_button(slot, pixel):
    with slot:
        if st.button(ui_text.t("ifk.deselect"), key="btn_pixel_abwaehlen"):
            # The map keeps a ghost square where the pixel was, until a new
            # pixel is picked.
            st.session_state["_ifk_deselected_pixel"] = pixel
            st.session_state.pop("_ifk_pending", None)
            language.set_query_params({})
            _rerun()


def result_summary(result: dict) -> tuple[int, float | None]:
    """What a pixel's result covers: (number of contributing Anrisse, highest
    return period in years).

    An Anriss contributes if its events have a positive summed rate (in
    Experten-Modus a rate can be set to zero); the map's circles are the same
    Anrisse. The highest return period is the largest finite one over the
    three curves: that of the rarest intensity simulated at the pixel, where
    the curves end. None if no curve has one."""
    anrisse = result["anriss_events"]
    contributing = anrisse.loc[anrisse["lambda_ereignis_sum"] > 0, "id_anriss"].nunique()
    periods = np.concatenate(
        [curve["return_period"].to_numpy(dtype=np.float64) for curve in result["curves"].values()]
    )
    finite = periods[np.isfinite(periods)]
    highest = float(finite.max()) if finite.size else None
    return int(contributing), highest


def _summary_row(pixel, result):
    """One row above the curves: the pixel, its contributing Anrisse,
    the highest return period and "Link kopieren"."""
    contributing, highest = result_summary(result)
    with st.container(
        key="ifk_summary", horizontal=True, vertical_alignment="center", gap="medium"
    ):
        st.markdown(ui_text.ifk_summary_pixel(*pixel), width="content")
        st.markdown(ui_text.ifk_summary_anrisse(contributing), width="content")
        if highest is not None:
            st.markdown(
                ui_text.ifk_summary_return_period(highest),
                help=ui_text.t("ifk.summary_return_period_help"),
                width="content",
            )
        query = pixel_query(pixel)
        if query is not None:
            copy_link_button(
                query,
                {
                    "label": ui_text.t("ifk.summary_copy_link"),
                    "copied": ui_text.t("ifk.summary_link_copied"),
                    "failed": ui_text.t("ifk.summary_copy_failed"),
                },
                key="ifk_copy_link",
            )


def _render_result(pixel, ifk):
    if ifk["failed"]:
        st.error(ui_text.t("ifk.error"))
        return
    result = ifk["data"]
    expert = bool(result.get("expert_mode"))
    if expert:
        st.warning(ui_text.t("ifk.expert_warning"))
    if all(curve.empty for curve in result["curves"].values()):
        return  # _no_curves_note says why, above the map
    _summary_row(pixel, result)
    for column, variable in zip(st.columns(3), ifk_and_raster.INTENSITY_VARS):
        with column:
            original = ifk["original"]["curves"][variable] if ifk.get("original") else None
            file_stem = ifk_export.curve_file_stem(variable, *pixel, expert)
            ifk_charts.curve(result["curves"][variable], variable, file_stem, original)
    st.markdown("---")
    # compute_ifk_default's per-(id_anriss, parameter combination) table, with
    # every factor up to lambda_Ereignis.
    ereignisse = result["ereignisse"]
    # One row: the Rohdaten and, in Experten-Modus, the probabilities that
    # produced all three curves.
    with downloads_section(), st.container(horizontal=True):
        st.download_button(
            ui_text.t("ifk.rohdaten"),
            ifk_export.rohdaten_csv_bytes(ereignisse),
            file_name=ifk_export.rohdaten_file_name(*pixel, expert),
            mime="text/csv",
            key="ifk_rohdaten_csv",
            on_click="ignore",
        )
        if expert:
            st.download_button(
                ui_text.t("expert.config_download"),
                expert_mode.config_json_bytes(),
                file_name=ifk_export.wahrscheinlichkeiten_file_name(*pixel),
                mime="application/json",
                key="ifk_expert_config",
                on_click="ignore",
            )
    if st.session_state.get("_expert_active") and not ereignisse.empty:
        if expert_mode.anriss_factor_editor(
            ereignisse, key=f"_expert_anriss_editor_{pixel[0]}_{pixel[1]}"
        ):
            _rerun()


def _chips(pixel) -> list[str]:
    """The header chip of the selected pixel or area; none without one."""
    if pixel is not None:
        return [ui_text.chip_pixel(*pixel)]
    area = st.session_state.get(ifk_area.SELECTION)
    return [ui_text.t("header.chip_area", shape=shape_label(area))] if area is not None else []


@st.fragment
def render(servers: dict, default_center: tuple[float, float], anriss_page: StreamlitPage):
    """The view's main area: the header, the map and the curves of the
    selected pixel or area. It is a fragment, so a pixel click reruns only this
    part. app.py draws the sidebar (expert_mode.render_sidebar,
    ifk_area.render_sidebar).

    Args:
        servers: pmtiles_port and pmtiles_path_prefix of the tile sidecar,
            and bbox_server, the port and path_prefix of
            derivate_bbox_server.py (it serves an area's Rohdaten).
        default_center: (lat, lon) the map starts at without a remembered view.
        anriss_page: the Anriss view's page, opened from a circle's popup.
    """
    _select_from_link()
    pixel = st.session_state.get("_ifk_pending")
    page_header(ui_text.t("nav.ifk"), ui_text.t("header.ifk_hint"), _chips(pixel) + expert_chip())
    # The deselect button's place, always created: inserting the button right
    # before the map only once a pixel is selected made Streamlit remount the
    # map's iframe on that one rerun, resetting the user's pan and zoom
    # (confirmed in Playwright). The button is filled in after the map.
    button_slot = st.empty()
    ifk, circles, area_ifk = None, (None, None), None
    if pixel is None:
        area_ifk = ifk_area.prepare()
    else:
        # Computed before the map, so the circles of the pixel show on the same
        # render as the click that picked it.
        ifk = _result(pixel)
        if ifk["data"] is not None:
            circles = _anriss_events_geojson(ifk["data"]["anriss_events"])
            _no_curves_note(pixel, ifk["data"]["curves"])
    outline = area_ifk["outline"] if area_ifk else None
    _handle_click(_map(pixel, circles, outline, servers, default_center), anriss_page)
    if pixel is not None:
        _deselect_button(button_slot, pixel)
    if pixel is not None:
        _render_result(pixel, ifk)
    else:
        ifk_area.render_result(area_ifk, servers["bbox_server"])
    downloads_cue()
