"""A long computation over an area, run on a background thread: the worker,
its state, and the fragment that shows the progress and "Abbrechen" in the
job card.

A synchronous call would block the script and the UI until it finished; on a
thread, "Abbrechen" stays clickable. This is for jobs the user wants to stop
(too slow against S3), a separate concern from the size limits
(ui_common.selection_limit_error), which keep a job from growing large enough to
exhaust the host's memory.

The thread writes only to `state` (plain Python): Streamlit calls aren't
thread-safe off the script thread. A view names its session keys with Keys,
starts the job with start() and draws progress_fragment() while it runs; the
finished job ends up in the session as {'value', 'error'} under Keys.result.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import streamlit as st

import raster_jobs
import ui_text

logger = logging.getLogger(__name__)

# A job's error: cancelled by the user (a warning), or failed (an error, logged).
ABORTED = "aborted"
FAILED = "failed"

# The job card's container key. One job per view, so one key.
CARD_KEY = "pgr_job_card"


class Aborted(Exception):
    """Raised from the build's progress callback to unwind out of its kachel
    loop when the user hits "Abbrechen". Caught in the worker thread, never
    meant to escape it."""


@dataclass(frozen=True)
class Keys:
    """One view's session keys: the running job ({'abort_event', 'state'}),
    the finished job's result ({'value', 'error'}) and the abort button."""

    job: str
    result: str
    abort_button: str


def format_duration_s(seconds) -> str:
    """Rough human-readable duration for the estimated-runtime captions (see
    ifk_and_raster.estimate_raster_seconds)."""
    if seconds < 90:
        return ui_text.t("unit.seconds", value=ui_text.in_locale(f"{seconds:.0f}"))
    return ui_text.t("unit.minutes", value=ui_text.in_locale(f"{seconds / 60:.1f}"))


def new_state() -> dict:
    return {
        "done": False,
        "progress": 0.0,
        "value": None,
        "error": None,
        "started_at": time.time(),
        "kacheln_done": 0,
        "kacheln_total": 0,
        "elapsed_at_last_progress": 0.0,
    }


def report_progress(state: dict, abort: threading.Event, done, total, _msg):
    """The build's progress callback (done of total kacheln), on the worker
    thread. probe-core's message is German and the worker has no session to
    take the language from: step_text() writes the step in the fragment."""
    if abort.is_set():
        raise Aborted()
    state["progress"] = done / total if total else 0.0
    state["kacheln_done"] = done
    state["kacheln_total"] = total
    # Time taken to COMPLETE `done` kacheln, without the partial time of the
    # kachel in flight: the remaining-time estimate is built from this.
    state["elapsed_at_last_progress"] = time.time() - state["started_at"]


def fail(state: dict):
    """Ends a job that failed before it could run."""
    state["error"] = FAILED
    state["done"] = True


def run(
    build: Callable[[], object],
    state: dict,
    abort: threading.Event,
    *,
    needs_slot: bool,
    failure_message: str,
):
    """The worker thread's body: runs build() and stores what it returns in
    state['value'].

    Args:
        build: the computation; it reports through report_progress, which
            raises Aborted once `abort` is set.
        needs_slot: True for a build that reads gold. Only one of those runs
            per process (raster_jobs.MAX_RUNNING), the rest wait; a build
            from kept results needs no slot. The clock starts once the job
            runs, so the estimate leaves out the wait.
        failure_message: logged with the exception if build() fails.
    """
    state["queued"] = needs_slot
    if needs_slot and not raster_jobs.acquire_run_slot(abort):
        state["error"] = ABORTED
        state["done"] = True
        return
    state["queued"] = False
    state["started_at"] = time.time()
    try:
        state["value"] = build()
    except Aborted:
        state["error"] = ABORTED
    except Exception:
        logger.exception(failure_message)
        state["error"] = FAILED
    finally:
        if needs_slot:
            raster_jobs.release_run_slot()
        state["done"] = True


def start(keys: Keys, target: Callable[[dict, threading.Event], None]):
    """Starts target(state, abort) on a background thread and stores the job
    under keys.job."""
    abort = threading.Event()
    state = new_state()
    st.session_state[keys.job] = {"abort_event": abort, "state": state}
    threading.Thread(target=target, args=(state, abort), daemon=True).start()


def abort_stale(keys: Keys):
    """Pops the job if one is running and signals its thread to stop. The
    thread is orphaned (nothing reads the job any more) but respects the abort
    event instead of running on. For wherever a job goes stale: a fresh
    submit, "Zurücksetzen", "Löschen" on the map, a changed request."""
    stale_job = st.session_state.pop(keys.job, None)
    if stale_job is not None:
        stale_job["abort_event"].set()


def duration_caption(state: dict, static_caption: str) -> str:
    """Elapsed and remaining time, from this job's own pace once a kachel is
    done (kachel density varies 1000x+ across the lake, so it beats the
    pre-job guess). The rate is elapsed_at_last_progress / kacheln_done, not
    the live elapsed time: progress stays flat while a kachel is in flight,
    so the live time would inflate the estimate for as long as that kachel
    takes. E.g. 3 of 5 kacheln in 1 minute leaves 40 s, however long the 4th
    has been running."""
    if state["kacheln_done"] == 0:
        return static_caption
    elapsed = time.time() - state["started_at"]
    rate_per_kachel = state["elapsed_at_last_progress"] / state["kacheln_done"]
    remaining = rate_per_kachel * (state["kacheln_total"] - state["kacheln_done"])
    return ui_text.t(
        "job.elapsed", elapsed=format_duration_s(elapsed), remaining=format_duration_s(remaining)
    )


def step_text(state: dict) -> str:
    """The step the job is on: starting, the kachel in flight, or writing the
    result once every kachel is done."""
    done, total = state["kacheln_done"], state["kacheln_total"]
    if total == 0:
        return ui_text.t("job.starting")
    if done < total:
        return ui_text.t("job.kachel", n=done + 1, total=total)
    return ui_text.t("job.writing")


def _abort_button(keys: Keys, job: dict):
    if st.button(ui_text.t("job.abort"), key=keys.abort_button):
        job["abort_event"].set()


def card():
    """The job card, a bordered box: progress_fragment draws the running job
    in it, and a view may draw the finished job in one too. Draw it once per
    run: its key is fixed, so a second card in the same run is an error."""
    return st.container(border=True, key=CARD_KEY)


@st.fragment(run_every=0.5)
def progress_fragment(keys: Keys, static_caption: str):
    """Polls the job's state dict and redraws only the job card, so the page
    stays usable and "Abbrechen" stays live while the job runs.

    Args:
        static_caption: the pre-job estimate, shown until the job has
            finished a kachel.
    """
    job = st.session_state.get(keys.job)
    if job is None:
        return
    state = job["state"]
    if state["done"]:
        st.session_state[keys.result] = {"value": state["value"], "error": state["error"]}
        st.session_state.pop(keys.job, None)
        st.rerun()  # scope="app": the view draws the finished result
    with card():
        if job["abort_event"].is_set():
            # Cancellation is checked once per kachel, so the kachel in flight
            # still finishes: say so instead of leaving the progress bar up.
            # No button: a second click would do nothing.
            st.warning(ui_text.t("job.aborting", step=step_text(state)))
        elif state.get("queued"):
            st.info(ui_text.t("job.queued"))
            _abort_button(keys, job)
        else:
            st.progress(
                state["progress"],
                text=f"{step_text(state)} ({duration_caption(state, static_caption)})",
            )
            _abort_button(keys, job)
