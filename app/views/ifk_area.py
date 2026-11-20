"""IFK-Berechnung for an area: the intensity-frequency curves of a drawn or
uploaded rectangle or polygon, next to the pixel's in views/ifk.py.

The rule (probe-core's ifk_and_raster): a simulation counts once for the
area, with its largest intensity over all pixels inside, each variable on its
own. An area's curve therefore lies at or above the curve of every pixel in it.

Two steps. The job (area_job, with progress and "Abbrechen") reads gold and
keeps one row per simulation reaching the area; those maxima hold no
probability, so they are kept per area in a folder all sessions share. The
curves are then computed from them in seconds, again on every Experten-Modus
edit.

The sidebar part (render_sidebar) is drawn by app.py, outside the IFK view's
fragment: a fragment can't draw into the sidebar. A new area therefore reruns
the whole page. A link can select a rectangle:
/ifk?xmin=<E>&ymin=<N>&xmax=<E>&ymax=<N> (LV95 metres); a drawn rectangle
writes the link, a polygon has none.
"""

import functools
import json
import logging
import os
import shutil
import threading
import uuid
from collections.abc import Mapping
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import streamlit as st

import area_job
import area_upload
import ifk_charts
import ifk_export
import language
import raster_jobs
import ui_text
import work_dirs
from downloads_cue_component import downloads_section
from probe_core.derivate import ifk_and_raster
from ui_common import (
    bbox_server_url,
    check_in_canton,
    checked_selection,
    download_link_button,
    query_floats,
    selection_caption,
    selection_limit_error,
    snap_to_pixel,
)
from views import expert_mode

logger = logging.getLogger(__name__)

# Session keys. The selection's is area_upload's "<prefix>_selection".
_PREFIX = "_ifk_area"
SELECTION = f"{_PREFIX}_selection"
_JOB = area_job.Keys(
    job=f"{_PREFIX}_job", result=f"{_PREFIX}_result", abort_button="ifk_area_abort_btn"
)
# The area "IFK berechnen" was clicked for; the job and the result belong to it.
_REQUEST = f"{_PREFIX}_request"
# The curves computed from the job's maxima, per Experten-Modus state (_ifk).
_IFK = f"{_PREFIX}_ifk"
# This session's folder for the Rohdaten files.
_DIR = f"{_PREFIX}_dir"
# The selection and the link's query the view last acted on.
_SEEN = f"{_PREFIX}_seen"
_LINK_SEEN = f"{_PREFIX}_link_seen"
_NONCE = f"{_PREFIX}_component_nonce"
# The pixel's keys (views/ifk.py): a new area replaces the pixel.
_PIXEL_KEYS = ("_ifk_pending", "_ifk_deselected_pixel")

_QUERY_KEYS = ("xmin", "ymin", "xmax", "ymax")
_CSV_BOM = b"\xef\xbb\xbf"
_ROHDATEN_FORMATS = {
    "csv": ("CSV", "text/csv"),
    "parquet": ("Parquet", "application/vnd.apache.parquet"),
}
# Vertices per quarter circle of an Anriss in the outline: 16 per circle.
_OUTLINE_QUAD_SEGS = 4


# ── Link ─────────────────────────────────────────────────────────────────────


def area_from_query(params: Mapping[str, str]) -> dict | None:
    """The rectangle a link asks for, its corners snapped to pixel centres
    like a drawn one.

    Returns:
        None if the link has none of xmin, ymin, xmax, ymax.

    Raises:
        ValueError: one of them is missing or not a number, a corner is
            outside Kanton Bern, or the rectangle is inside out.
    """
    bounds = query_floats(params, _QUERY_KEYS)
    if bounds is None:
        return None
    xmin, ymin, xmax, ymax = bounds
    check_in_canton(xmin, ymin)
    check_in_canton(xmax, ymax)
    if xmin > xmax or ymin > ymax:
        raise ValueError(f"xmin={xmin}, ymin={ymin} is not below xmax={xmax}, ymax={ymax}")
    ring = ifk_and_raster.rect_ring(*(snap_to_pixel(v) for v in bounds))
    return checked_selection({"type": "bbox", "ring": ring})


def area_query(selection: dict | None) -> dict[str, str] | None:
    """The query params that make a link select `selection`; None if a link can't
    hold it (a polygon, or a rectangle outside Kanton Bern)."""
    if selection is None or selection["type"] != "bbox":
        return None
    bounds = ifk_and_raster.selection_bounds(selection)
    params = {key: f"{value:.1f}" for key, value in zip(_QUERY_KEYS, bounds)}
    try:
        area_from_query(params)
    except ValueError:
        return None
    return params


def _set_query(selection: dict | None):
    """Puts the area in the URL (nothing for a polygon or no area) and notes
    it as seen, so _select_from_link doesn't select it again."""
    params = area_query(selection) or {}
    language.set_query_params(params)
    st.session_state[_LINK_SEEN] = params


def _select_from_link():
    """Selects a link's rectangle when the URL's area changed since the view
    last looked: the page was opened from a link. The view's own URL changes
    go through _set_query and don't count."""
    params = {key: st.query_params[key] for key in _QUERY_KEYS if key in st.query_params}
    if params == st.session_state.get(_LINK_SEEN, {}):
        return
    st.session_state[_LINK_SEEN] = params
    try:
        selection = area_from_query(params)
    except ValueError:
        st.warning(ui_text.t("ifk_area.bad_link"))
        return
    if selection is not None:
        st.session_state[SELECTION] = selection


# ── Selection ────────────────────────────────────────────────────────────────


def _discard_result():
    """Stops the job and drops everything computed for the previous area."""
    area_job.abort_stale(_JOB)
    work_dirs.remove(st.session_state.pop(_DIR, None))
    for key in (_REQUEST, _JOB.result, _IFK):
        st.session_state.pop(key, None)


def _sync_selection():
    """Acts on a changed area, wherever it came from (the map, an upload, a
    link): the previous area's job and result go, and so does a selected
    pixel, since the view shows one or the other."""
    selection = st.session_state.get(SELECTION)
    if selection == st.session_state.get(_SEEN):
        return
    st.session_state[_SEEN] = selection
    _discard_result()
    if selection is not None:
        for key in _PIXEL_KEYS:
            st.session_state.pop(key, None)
        _set_query(selection)


def clear() -> bool:
    """Drops the area and its result: a pixel was picked. Returns True if
    there was an area, whose sidebar part then has to be redrawn."""
    had_area = st.session_state.pop(SELECTION, None) is not None
    st.session_state[_SEEN] = None
    _discard_result()
    if had_area:
        area_upload.reset_widget(_PREFIX)
    return had_area


def selection_too_large() -> bool:
    """True if the selected area is over the limits the sidebar names, so the
    map's area popup disables its button."""
    selection = st.session_state.get(SELECTION)
    return selection is not None and selection_limit_error(selection) is not None


def handle_map_selection(value: dict):
    """A drawn area, "Löschen" or the area popup's "IFK berechnen" from the
    map ({'selection': ...|None, 'nonce', 'compute': True for the popup}).
    The popup sends its area along: a click right after drawing can come
    before the drawn area's own value was handled. The component repeats its
    last value on every rerun, so the nonce tells a new one apart. Reruns the
    page: the sidebar shows the area."""
    if value["nonce"] == st.session_state.get(_NONCE):
        return
    st.session_state[_NONCE] = value["nonce"]
    try:
        new_selection = checked_selection(value["selection"])
    except ValueError as error:
        logger.warning("Map selection refused: %s", error)
        return
    compute = bool(value.get("compute")) and new_selection is not None
    if new_selection != st.session_state.get(SELECTION):
        st.session_state[SELECTION] = new_selection
        if new_selection is None:
            area_upload.reset_widget(_PREFIX)
        # Now, not on the rerun: there the old URL would count as a link.
        _set_query(new_selection)
    elif not compute:
        return
    if compute and selection_limit_error(new_selection) is None:
        # Now, not on the rerun: there the new area would drop the request.
        _sync_selection()
        _request(new_selection)
    st.rerun()


# ── Sidebar ──────────────────────────────────────────────────────────────────


def _request(selection: dict):
    """Stores the request the main area runs: "IFK des Gebiets berechnen" in
    the sidebar or "IFK berechnen" in the map's area popup."""
    # Also for an unchanged area: a resubmit right after "Abbrechen" would
    # otherwise keep showing the abort.
    _discard_result()
    st.session_state[_REQUEST] = {"selection": selection}


def _submit_button(selection: dict | None, disabled: bool):
    """ "IFK des Gebiets berechnen"."""
    submitted = st.sidebar.button(
        ui_text.t("ifk_area.submit"),
        disabled=disabled,
        key="_ifk_area_submit_btn",
        width="stretch",
        type="primary",
    )
    if submitted and selection is not None:
        _request(selection)


def _reset_button(selection: dict | None):
    if selection is None:
        return
    if st.sidebar.button(ui_text.t("area.reset"), key="ifk_area_reset_btn", width="stretch"):
        st.session_state.pop(SELECTION, None)
        area_upload.reset_widget(_PREFIX)
        _set_query(None)
        st.rerun()


def render_sidebar():
    """The area's part of the sidebar: its size and limits, the file upload,
    "IFK des Gebiets berechnen" and "Zurücksetzen". Called by app.py before
    the view's fragment."""
    _select_from_link()
    _sync_selection()
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        f"<div class='pgr-field-label'>{ui_text.t('area.heading')}</div>",
        unsafe_allow_html=True,
    )
    selection = st.session_state.get(SELECTION)
    too_large = False
    if selection is None:
        st.sidebar.caption(ui_text.t("area.hint"))
    else:
        too_large = selection_caption(selection)
    area_upload.expander(_PREFIX)
    _submit_button(selection, disabled=selection is None or too_large)
    _reset_button(selection)


# ── Job: the simulations' maxima over the area ───────────────────────────────


def _maxima_path(selection: dict) -> Path:
    """Where an area's maxima are kept (work_dirs.IFK_AREA_MAXIMA), named by
    probe-core's area_maxima_cache_key: any session asking for the same area
    reuses them, whatever its Experten-Modus state."""
    key = ifk_and_raster.area_maxima_cache_key(selection)
    return work_dirs.kind_dir(work_dirs.IFK_AREA_MAXIMA) / f"{key}.parquet"


def _build_maxima(selection: dict, maxima: Path, progress_callback) -> str:
    if not maxima.exists():
        ifk_and_raster.build_area_event_maxima(selection, str(maxima), progress_callback)
    return str(maxima)


def _run_job(selection: dict, state: dict, abort: threading.Event):
    """The worker thread (area_job.run): kept maxima need no run slot."""
    maxima = _maxima_path(selection)
    progress_callback = functools.partial(area_job.report_progress, state, abort)
    area_job.run(
        lambda: _build_maxima(selection, maxima, progress_callback),
        state,
        abort,
        needs_slot=not maxima.exists(),
        failure_message=f"IFK area maxima failed ({selection['type']} {ifk_export.area_slug(selection)})",
    )


def _job_section(selection: dict):
    if _JOB.job not in st.session_state:
        area_job.start(_JOB, lambda state, abort: _run_job(selection, state, abort))
    # The estimate is the rasters': the same gold rows are read.
    area_job.progress_fragment(
        _JOB,
        ui_text.t(
            "raster.estimate",
            duration=area_job.format_duration_s(ifk_and_raster.estimate_raster_seconds(selection)),
        ),
    )


# ── Curves, outline and Rohdaten from the maxima ─────────────────────────────


def anriss_outline_geojson(anriss_events: pd.DataFrame) -> dict | None:
    """One outline around the true-scale circles (radius sqrt(A/pi)) of all
    contributing Anrisse, in WGS84: an area can have 100'000 of them, too many
    to draw each. None if no Anriss has a positive lambda_ereignis_sum."""
    contributing = anriss_events[anriss_events["lambda_ereignis_sum"] > 0]
    if contributing.empty:
        return None
    radii = np.sqrt(contributing["anrissflaeche"].to_numpy(dtype=np.float64) / np.pi)
    centres = shapely.points(contributing["x"].to_numpy(), contributing["y"].to_numpy())
    outline = shapely.union_all(shapely.buffer(centres, radii, quad_segs=_OUTLINE_QUAD_SEGS))
    return json.loads(gpd.GeoSeries([outline], crs="EPSG:2056").to_crs("EPSG:4326").to_json())


def _job_dir() -> Path:
    if _DIR not in st.session_state:
        st.session_state[_DIR] = str(work_dirs.new_dir(work_dirs.IFK_JOBS))
    return Path(st.session_state[_DIR])


def _write_rohdaten(selection: dict, maxima: str, n_ereignisse: int, kwargs: dict) -> dict | None:
    """Writes the events behind the curves to this session's folder and
    returns {'path', 'name', 'format', 'content_type', 'n'}; None without
    events. CSV (with a BOM, for Excel) up to AREA_ROHDATEN_CSV_MAX_ROWS
    events, Parquet above."""
    if n_ereignisse == 0:
        return None
    extension = "csv" if n_ereignisse <= ifk_export.AREA_ROHDATEN_CSV_MAX_ROWS else "parquet"
    path = _job_dir() / f"rohdaten_{uuid.uuid4().hex}.{extension}"
    ifk_and_raster.write_area_ereignisse(
        maxima, str(path), column_names=ifk_export.area_rohdaten_column_names(), **kwargs
    )
    if extension == "csv":
        _prepend_bom(path)
    label, content_type = _ROHDATEN_FORMATS[extension]
    name = ifk_export.area_rohdaten_file_name(selection, bool(kwargs), extension)
    return {
        "path": str(path),
        "name": name,
        "format": label,
        "content_type": content_type,
        "n": n_ereignisse,
    }


def _prepend_bom(path: Path):
    body = path.with_suffix(".body")
    os.replace(path, body)
    with open(path, "wb") as out, open(body, "rb") as source:
        out.write(_CSV_BOM)
        shutil.copyfileobj(source, out)
    body.unlink()


def _production(maxima: str, previous: dict | None) -> dict | None:
    """The production result next to an Experten-Modus one: the previous
    one of the same maxima, else computed. None if it fails: it is only the
    comparison line, so it must not take the Experten-Modus curve down."""
    if previous and previous["key"][0] == maxima and previous.get("production"):
        return previous["production"]
    try:
        return ifk_and_raster.compute_ifk_for_area(maxima)
    except Exception:
        logger.exception("IFK production computation failed for area maxima %s", maxima)
        return None


def _compute(selection: dict, maxima: str, previous: dict | None) -> dict:
    """{'data', 'production', 'original', 'outline', 'rohdaten', 'failed'}.
    'production' is the result without overrides, kept across Experten-Modus
    edits; 'original' is it next to an Experten-Modus result, else None."""
    kwargs = expert_mode.override_kwargs()
    try:
        data = ifk_and_raster.compute_ifk_for_area(maxima, **kwargs)
        production = _production(maxima, previous) if kwargs else data
        return {
            "data": data,
            "production": production,
            "original": production if kwargs else None,
            "outline": anriss_outline_geojson(data["anriss_events"]),
            "rohdaten": _write_rohdaten(selection, maxima, data["n_ereignisse"], kwargs),
            "failed": False,
        }
    except Exception:
        logger.exception("IFK computation failed for area maxima %s", maxima)
        return {"data": None, "production": None, "original": None, "outline": None,
                "rohdaten": None, "failed": True}  # fmt: skip


def _ifk(selection: dict, maxima: str) -> dict:
    """The area's IFK result (_compute), computed once per maxima and
    Experten-Modus state: an edit recomputes from the kept maxima."""
    key = (maxima, expert_mode.cache_signature())
    cached = st.session_state.get(_IFK)
    if cached is None or cached["key"] != key:
        with st.spinner(ui_text.t("ifk_area.spinner")):
            computed = _compute(selection, maxima, cached)
        if cached and cached.get("rohdaten"):
            Path(cached["rohdaten"]["path"]).unlink(missing_ok=True)
        cached = {"key": key, **computed}
        st.session_state[_IFK] = cached
    return cached


def _notes(selection: dict, ifk: dict):
    """Above the map, so they don't need a scroll: no simulation reaches the
    area, or part of it lies outside the finished kacheln."""
    if ifk["failed"]:
        return
    kacheln = ifk_and_raster.kacheln_for_bbox(*ifk_and_raster.selection_bounds(selection))
    finished = ifk_and_raster.gold_kachel_bytes()
    n_missing = sum(id_kachel not in finished for id_kachel in kacheln)
    if n_missing:
        st.info(ui_text.t("ifk_area.partly_outside", n_missing=n_missing, n_kacheln=len(kacheln)))
    if ifk["data"]["n_ereignisse"] == 0:
        st.info(ui_text.t("ifk_area.no_process"))


def prepare() -> dict | None:
    """The part above the map: the running job's progress, or the finished
    job's messages. Returns the area's result (_compute's dict) once there
    is one, else None."""
    request = st.session_state.get(_REQUEST)
    if request is None:
        return None
    result = st.session_state.get(_JOB.result)
    if result is None:
        _job_section(request["selection"])
        return None
    if result["error"] == area_job.ABORTED:
        st.warning(ui_text.t("ifk_area.aborted"))
        return None
    if result["error"] == area_job.FAILED:
        st.error(ui_text.t("ifk.error"))
        return None
    ifk = _ifk(request["selection"], result["value"])
    _notes(request["selection"], ifk)
    return ifk


# ── Result ───────────────────────────────────────────────────────────────────


def _rohdaten_url(rohdaten: dict, bbox_server: dict) -> str:
    """The Rohdaten file's link on derivate_bbox_server.py. Registered once
    per file, and again if the id expired from raster_jobs."""
    if raster_jobs.get_file(rohdaten.get("file_id", "")) is None:
        rohdaten["file_id"] = raster_jobs.register_file(
            rohdaten["path"], rohdaten["name"], rohdaten["content_type"]
        )
    return bbox_server_url(bbox_server, f"/file/{rohdaten['file_id']}")


def _downloads(selection: dict, ifk: dict, expert: bool, bbox_server: dict):
    with st.container(horizontal=True):
        rohdaten = ifk["rohdaten"]
        if rohdaten:
            download_link_button(
                ui_text.ifk_area_rohdaten(rohdaten["format"], rohdaten["n"]),
                _rohdaten_url(rohdaten, bbox_server),
                key="ifk_area_rohdaten",
            )
        if expert:
            st.download_button(
                ui_text.t("expert.config_download"),
                expert_mode.config_json_bytes(),
                file_name=ifk_export.area_wahrscheinlichkeiten_file_name(selection),
                mime="application/json",
                key="ifk_area_expert_config",
                on_click="ignore",
            )


def render_result(ifk: dict | None, bbox_server: dict):
    """The area's curves and downloads, below the map.

    Args:
        ifk: prepare()'s result; None draws nothing.
        bbox_server: port and path_prefix of derivate_bbox_server.py, which
            serves the Rohdaten file.
    """
    if ifk is None:
        return
    if ifk["failed"]:
        st.error(ui_text.t("ifk.error"))
        return
    result = ifk["data"]
    selection = st.session_state[_REQUEST]["selection"]
    expert = bool(result["expert_mode"])
    if expert:
        st.warning(ui_text.t("ifk.expert_warning"))
    if result["n_ereignisse"] == 0:
        return  # _notes says so, above the map
    st.markdown(ui_text.t("ifk_area.rule"))
    for column, variable in zip(st.columns(3), ifk_and_raster.INTENSITY_VARS):
        with column:
            original = ifk["original"]["curves"][variable] if ifk["original"] else None
            file_stem = ifk_export.area_curve_file_stem(variable, selection, expert)
            ifk_charts.curve(result["curves"][variable], variable, file_stem, original)
    st.markdown("---")
    with downloads_section():
        _downloads(selection, ifk, expert, bbox_server)
