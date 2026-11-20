"""Raster-Karten: ad-hoc rasters computed for a drawn or uploaded area.

The sidebar picks the mode (A: return period at a threshold, one variable; B:
intensity at a return period, all three variables), shows the area's size and
limits, and starts the job. The area comes from the map (rectangle or polygon)
or from an uploaded file. The job runs on a background thread; a card above
the map shows its progress and "Abbrechen", then an outcome that is not a
plain success, as in the IFK view (ifk_area.prepare). The finished rasters
are drawn on the map and linked for download below it, as in every other
view, both served by derivate_bbox_server.py.

The map is not in a fragment: the sidebar shows the area's size and whether
it can be computed, so a new selection has to rerun the whole page anyway.
"""

import functools
import logging
import os
import threading
from pathlib import Path

import streamlit as st

import area_job
import area_upload
import language
import raster_export
import raster_jobs
import raster_overlay
import ui_text
import work_dirs
from downloads_cue_component import downloads_cue, downloads_section
from probe_core.derivate import ifk_and_raster
from raster_bbox_component import raster_bbox_map
from raster_overlay import VARIABLE_UNITS
from ui_common import (
    bbox_server_url,
    checked_selection,
    download_link_button,
    expert_chip,
    load_coverage,
    page_header,
    selection_caption,
)
from views import expert_mode

VIEW_MODE = "Raster-Karten"

logger = logging.getLogger(__name__)

_JOB = area_job.Keys(job="_raster_job", result="_raster_result", abort_button="raster_abort_btn")

# The mode picker's options, in its order: A (Wiederkehrperiode), B (Intensität).
_MODES = ("A", "B")

# Schwellenwert per variable: (default, step, format).
_THRESHOLD_INPUT = {
    "depth": (0.5, 0.01, "%.2f"),
    "velocity": (1.0, 0.01, "%.2f"),
    "pressure": (100.0, 1.0, "%.0f"),
}


def _register_raster_job(paths: list[str], request: dict) -> dict:
    """Registers a finished job with raster_jobs, so derivate_bbox_server.py
    serves its PNG, hover grid and GeoTIFF, and returns the overlay cache
    entry for it:
    {'paths', 'job_id', 'files': {var: path}, 'payloads': {var: descriptor},
    'active_var', 'lang': the language of the descriptors' texts}.

    A descriptor is raster_overlay.describe() plus 'job_id' and 'var'; the
    map component fetches /job/<job_id>/<var>.png|.f32 itself. It is None for
    a variable whose raster has no valid pixels."""
    files = {}
    for var in raster_jobs.VARIABLES:
        match = next((path for path in paths if os.path.basename(path).startswith(f"{var}_")), None)
        if match:
            files[var] = match
    meta = {
        "mode": request["mode"],
        "threshold": request["threshold"],
        "return_period": request["return_period"],
    }
    job_id = raster_jobs.register(files, meta)
    payloads = _describe_job(job_id, files, request)
    active_var = (
        request["variable"] if request["variable"] in payloads else next(iter(payloads), None)
    )
    return {
        "paths": paths,
        "job_id": job_id,
        "files": files,
        "payloads": payloads,
        "active_var": active_var,
        "lang": ui_text.language(),
    }


def _describe_job(job_id: str, files: dict[str, str], request: dict) -> dict:
    """The map's descriptor of each variable's raster, its legend in the
    session's language."""
    payloads = {}
    for var, path in files.items():
        payload = raster_overlay.describe(
            path, request["mode"], var, request["threshold"], request["return_period"]
        )
        if payload is not None:
            payload.update(job_id=job_id, var=var)
        payloads[var] = payload
    return payloads


def _raster_curves_path(request: dict) -> Path:
    """Where a request's exceedance curves are kept (work_dirs.RASTER_CURVES),
    named by probe-core's curves_cache_key: the same area and probabilities
    reuse them, whatever mode, threshold or return period is asked. Reads two
    ETags from S3."""
    expert = {
        name: value
        for name, value in request.get("expert_kwargs", {}).items()
        if name in ("p_h_mean", "p_h_max", "ablauf_override")
    }
    key = ifk_and_raster.curves_cache_key(request["selection"], **expert)
    return work_dirs.kind_dir(work_dirs.RASTER_CURVES) / f"{key}.parquet"


def _drop_raster_dir():
    """Deletes this session's current result folder (its GeoTIFFs carry the
    selection, polygon included -- see work_dirs). Called when a new job
    replaces it and on both resets; a closed session's folder goes with
    work_dirs.sweep()."""
    work_dirs.remove(st.session_state.pop("_raster_dir", None))


def _discard_result():
    """Stops the job, deletes its result and empties the uploader: what
    "Zurücksetzen" and "Löschen" on the map both do, apart from the
    selection."""
    area_job.abort_stale(_JOB)
    _drop_raster_dir()
    for key in ("_raster_request", "_raster_result", "_raster_last_key", "_raster_overlay_cache"):
        st.session_state.pop(key, None)
    area_upload.reset_widget("_raster")


# ── Sidebar ──────────────────────────────────────────────────────────────────


def _mode_inputs() -> dict:
    """The mode and its parameters, as the request takes them: {'mode',
    'variable', 'threshold', 'return_period'}.

    Plain widgets, not an st.form: a mode flip (Schwellenwert vs.
    Wiederkehrperiode) and a variable change (the Schwellenwert unit) must
    show at once, not only after "Raster erzeugen"."""
    mode = st.sidebar.selectbox(
        ui_text.t("raster.mode"),
        _MODES,
        key=language.translated_options("_raster_mode"),
        format_func=_mode_label,
    )
    if mode == "A":
        # Mode A writes a raster of the selected variable only.
        variable = st.sidebar.selectbox(
            ui_text.t("raster.variable"),
            raster_jobs.VARIABLES,
            format_func=_variable_label,
            key=language.translated_options("_raster_var"),
        )
        return {
            "mode": "a",
            "variable": variable,
            "threshold": _threshold_input(variable),
            "return_period": None,
        }
    # Mode B writes depth, velocity and pressure from one set of curves, so
    # there is no Variable picker: the map's layer switcher picks between them.
    st.sidebar.caption(ui_text.t("raster.mode_b_note"))
    return_period = st.sidebar.number_input(
        ui_text.t("area.return_period_label"), value=1000, min_value=1, step=1, key="_raster_rp"
    )
    return {"mode": "b", "variable": "depth", "threshold": None, "return_period": return_period}


def _mode_label(mode: str) -> str:
    return ui_text.t(f"raster.mode_option.{mode.lower()}")


def _variable_label(variable: str) -> str:
    return ui_text.t(f"variable.{variable}")


def _threshold_input(variable: str) -> float:
    """One field per variable (own key), so switching to Druck doesn't carry
    over a 1.00 m depth as 1.00 kN/m². Streamlit drops a widget's state in any
    run it isn't drawn in, so each variable's last value is kept in
    _raster_thresholds and passed back as the starting value. Steps follow
    gold's resolution (whole cm, cm/s, kPa)."""
    default, step, fmt = _THRESHOLD_INPUT[variable]
    saved = st.session_state.setdefault("_raster_thresholds", {})
    saved[variable] = st.sidebar.number_input(
        ui_text.t("area.threshold_label", unit=VARIABLE_UNITS[variable]),
        value=saved.get(variable, default),
        min_value=0.0,
        step=step,
        format=fmt,
        key=f"_raster_threshold_{variable}",
    )
    return saved[variable]


def _submit_button(inputs: dict, disabled: bool):
    """ "Raster erzeugen": stores the request the main area runs."""
    submitted = st.sidebar.button(
        ui_text.t("raster.submit"),
        disabled=disabled,
        key="_raster_submit_btn",
        width="stretch",
        type="primary",
    )
    if not submitted or st.session_state.get("_raster_selection") is None:
        return
    # Clears the previous result even for an unchanged request: the request-key
    # check in the main area only fires on a change, so a resubmit right after
    # "Abbrechen" would keep showing the stale abort.
    area_job.abort_stale(_JOB)
    st.session_state.pop("_raster_result", None)
    st.session_state["_raster_request"] = {
        **inputs,
        "selection": st.session_state["_raster_selection"],
        # Snapshotted at submit: a later Experten-Modus edit doesn't change a
        # running or finished job. No per-Anriss overrides: build_raster_for_bbox
        # has no such parameter.
        "expert_kwargs": expert_mode.override_kwargs(),
    }


def _reset_button():
    """ "Zurücksetzen". The map's nonce and the upload state stay: both are
    compared by an identity that changes with each new draw or upload, so a
    still-attached file keeps counting as processed and the reset sticks."""
    if (
        st.session_state.get("_raster_selection") is None
        and st.session_state.get("_raster_result") is None
    ):
        return
    if st.sidebar.button(ui_text.t("area.reset"), key="raster_reset_btn", width="stretch"):
        _discard_result()
        st.session_state.pop("_raster_selection", None)
        st.rerun()


def _sidebar():
    st.sidebar.markdown("---")
    inputs = _mode_inputs()
    st.sidebar.markdown(
        f"<div class='pgr-field-label'>{ui_text.t('area.heading')}</div>", unsafe_allow_html=True
    )
    selection = st.session_state.get("_raster_selection")
    too_large = False
    if selection is None:
        st.sidebar.caption(ui_text.t("area.hint"))
    else:
        too_large = selection_caption(selection)
    # The estimated duration shows next to the progress bar once the job runs
    # (area_job.progress_fragment), where it is useful to read.
    area_upload.expander("_raster")
    _submit_button(inputs, disabled=selection is None or too_large)
    _reset_button()


# ── Job ──────────────────────────────────────────────────────────────────────


def _overlay_cache(request: dict | None) -> dict | None:
    """The finished result's overlay cache entry (_register_raster_job), or
    None without one. Registered once per result, not on every rerun, and
    again if the job expired from raster_jobs. The map fetches the PNG and
    hover grid from derivate_bbox_server.py itself, so its args carry only
    the small descriptors. Mode B has a descriptor per variable, and the map
    switches between them client-side
    (frontend/src/raster_bbox_map/overlays.ts)."""
    result = st.session_state.get("_raster_result")
    if not (request and result and not result.get("error") and result.get("value")):
        return None
    cache = st.session_state.get("_raster_overlay_cache")
    if (
        cache is None
        or cache["paths"] != result["value"]
        or raster_jobs.get(cache["job_id"]) is None
    ):
        cache = _register_raster_job(result["value"], request)
        st.session_state["_raster_overlay_cache"] = cache
    elif cache["lang"] != ui_text.language():
        # The same job, so the map keeps its raster; only the legend texts change.
        cache["payloads"] = _describe_job(cache["job_id"], cache["files"], request)
        cache["lang"] = ui_text.language()
    return cache


def _drop_result_of_other_request(request: dict | None):
    """A new request (another area or parameters) replaces the result and
    stops a job still running for the previous one."""
    if request is None:
        return
    req_key = (
        request["mode"],
        request["variable"],
        request["threshold"],
        request["return_period"],
        request["selection"],
    )
    if st.session_state.get("_raster_last_key") != req_key:
        st.session_state["_raster_last_key"] = req_key
        st.session_state.pop("_raster_result", None)
        area_job.abort_stale(_JOB)


def _job_context(request: dict) -> str:
    """A failed job's request for the log, without its (long) polygon ring."""
    return (
        f"mode {request['mode']}, {request['variable']}, threshold {request['threshold']}, "
        f"return period {request['return_period']}, {request['selection']['type']}, "
        f"expert {sorted(request.get('expert_kwargs', {}))}"
    )


def _run_job(request: dict, state: dict, out_dir: str, abort: threading.Event):
    """The worker thread (area_job.run): a curves cache hit only reads its
    small curves file and needs no run slot."""
    try:
        curves = _raster_curves_path(request)
    except Exception:
        logger.exception("Raster curves failed (%s)", _job_context(request))
        area_job.fail(state)
        return
    progress_callback = functools.partial(area_job.report_progress, state, abort)
    area_job.run(
        lambda: _build(request, curves, out_dir, progress_callback),
        state,
        abort,
        needs_slot=not curves.exists(),
        failure_message=f"Raster build failed ({_job_context(request)})",
    )


def _build(request: dict, curves: Path, out_dir: str, progress_callback) -> list[str]:
    # `is None`, not `or`: a threshold of 0.0 is a valid choice.
    threshold = 1.0 if request["threshold"] is None else request["threshold"]
    return_period = 300 if request["return_period"] is None else request["return_period"]
    return ifk_and_raster.build_raster_for_bbox(
        request["selection"],
        request["mode"],
        variable=request["variable"],
        threshold=threshold,
        return_period=return_period,
        progress_callback=progress_callback,
        out_dir=out_dir,
        curves_path=str(curves),
        **request.get("expert_kwargs", {}),
    )


def _start_job(request: dict):
    _drop_raster_dir()
    out_dir = str(work_dirs.new_dir(work_dirs.RASTER_JOBS))
    st.session_state["_raster_dir"] = out_dir
    area_job.start(_JOB, lambda state, abort: _run_job(request, state, out_dir, abort))


def _job_card(request: dict | None):
    """The part above the map, as in the IFK view (ifk_area.prepare): the
    running job's progress, then its outcome. Drawn only when it has
    something to say -- a plain success draws nothing, so the map comes back
    to where it was and its downloads are below it (_downloads).

    area_job.card() has one fixed key, so it is drawn once per run: either by
    _outcome or by the progress fragment, never by both."""
    if request is None:
        return
    if "_raster_result" in st.session_state:
        _outcome(request)
        return
    if "_raster_job" not in st.session_state:
        _start_job(request)
    # The pre-job estimate from the gold rows the selection reads, until the
    # job has finished a kachel. One cached S3 listing.
    area_job.progress_fragment(
        _JOB,
        ui_text.t(
            "raster.estimate",
            duration=area_job.format_duration_s(
                ifk_and_raster.estimate_raster_seconds(request["selection"])
            ),
        ),
    )


# ── Map and result ───────────────────────────────────────────────────────────


def _handle_selection(map_value: dict | None):
    """A new map selection ({'selection': ...|None, 'nonce'}, see sendSelection
    in frontend/src/raster_bbox_map/map.ts).

    The component returns None until it first sends a value, and repeats its
    last value on every rerun, so the nonce tells a new interaction apart.
    Comparing the bare selection instead misread an untouched map (None) as
    "Löschen" and wiped a just-uploaded selection. A selection of None is
    "Löschen": it also drops the result and empties the uploader (client
    feedback: the old raster stayed on the map). The map keeps its view."""
    if map_value is None or map_value["nonce"] == st.session_state.get(
        "_raster_selection_component_nonce"
    ):
        return
    st.session_state["_raster_selection_component_nonce"] = map_value["nonce"]
    try:
        new_selection = checked_selection(map_value["selection"])
    except ValueError as error:
        logger.warning("Map selection refused: %s", error)
        return
    if new_selection == st.session_state.get("_raster_selection"):
        return
    st.session_state["_raster_selection"] = new_selection
    if new_selection is None:
        _discard_result()
    st.rerun()


def _outcome(request: dict):
    """The finished job's outcome above the map: the Experten-Modus caveat,
    which holds for every outcome, and anything that is not a plain success.
    A success without the caveat draws no card at all -- its downloads are
    below the map, and an empty bordered box would push the map down for
    nothing."""
    result = st.session_state["_raster_result"]
    expert = bool(request.get("expert_kwargs"))
    if not expert and not result["error"] and result["value"]:
        return
    with area_job.card():
        if expert:
            st.warning(ui_text.t("raster.expert_warning", contact=ui_text.FEEDBACK_CONTACT))
        if result["error"] == area_job.ABORTED:
            st.warning(ui_text.t("raster.aborted"))
        elif result["error"] == area_job.FAILED:
            st.error(ui_text.t("raster.error"))
        elif not result["value"]:
            st.info(ui_text.t("raster.no_pixels"))


def _result_label(request: dict, var: str) -> str:
    """What a result raster holds, as its legend on the map says it."""
    if request["mode"] == "a":
        return ui_text.overlay_label_return_period(
            _variable_label(var), request["threshold"], VARIABLE_UNITS[var]
        )
    return ui_text.overlay_label_intensity(_variable_label(var), request["return_period"])


def _downloads(request: dict | None, cache: dict | None, bbox_server: dict):
    """The finished result's downloads, below the map as in every other view:
    one GeoTIFF per computed variable, each with its file name, in a grid of
    three equally wide columns. Nothing without a successful result,
    including on the run that drops a stale one (_drop_result_of_other_request
    leaves `cache` behind for the map but clears the result)."""
    result = st.session_state.get("_raster_result")
    if not (request and cache and result and not result["error"] and result["value"]):
        return
    st.success(ui_text.t("raster.done", n_rasters=len(result["value"])))
    # derivate_bbox_server.py sends the file under the same name.
    for column, (var, path) in zip(st.columns(3), cache["files"].items()):
        with column:
            download_link_button(
                ui_text.raster_download(_result_label(request, var), os.path.getsize(path)),
                bbox_server_url(bbox_server, f"/job/{cache['job_id']}/{var}.tif"),
                key=f"raster_karten_{var}",
                width="stretch",
            )
            st.caption(ui_text.t("raster.download_file", name=raster_export.download_name(path)))
    if request.get("expert_kwargs"):
        # The submit-time snapshot, not the live sidebar state (see
        # expert_mode.config_json_bytes).
        st.download_button(
            ui_text.t("expert.config_download"),
            expert_mode.config_json_bytes(request["expert_kwargs"]),
            file_name=f"adhoc{ui_text.FILE_EXPERT_SUFFIX}_wahrscheinlichkeiten.json",
            mime="application/json",
            key="raster_expert_config",
            on_click="ignore",
        )


def render(servers: dict, bbox_server: dict, default_center: tuple[float, float]):
    """The view: its sidebar with the inputs, the job card above the map,
    the map, and the downloads below it.

    Args:
        servers: pmtiles_port and pmtiles_path_prefix of the tile sidecar.
        bbox_server: port and path_prefix of derivate_bbox_server.py, which
            serves the finished rasters.
        default_center: (lat, lon) the map starts at.
    """
    _sidebar()
    page_header(ui_text.t("nav.raster_karten"), ui_text.t("header.raster_hint"), expert_chip())
    request = st.session_state.get("_raster_request")
    # Before the request-key check below, as it always was: a changed request
    # still shows the old overlay on this one run.
    cache = _overlay_cache(request)
    overlays = cache["payloads"] if cache else None
    active_var = cache["active_var"] if cache else None
    _drop_result_of_other_request(request)
    _job_card(request)
    _handle_selection(
        raster_bbox_map(
            center_lat=default_center[0],
            center_lon=default_center[1],
            coverage_version=load_coverage()[0],
            selected_selection=st.session_state.get("_raster_selection"),
            raster_overlays=overlays,
            active_variable=active_var,
            derivate_bbox_server_port=bbox_server["port"],
            derivate_bbox_path_prefix=bbox_server["path_prefix"],
            pmtiles_port=servers["pmtiles_port"],
            pmtiles_path_prefix=servers["pmtiles_path_prefix"],
        )
    )
    active_payload = (overlays or {}).get(active_var)
    if active_payload and active_payload.get("hover_caption"):
        st.caption(active_payload["hover_caption"])
    with downloads_section():
        _downloads(request, cache, bbox_server)
    downloads_cue()
