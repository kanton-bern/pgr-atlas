"""area_job: the step and time estimate next to a running job's progress bar. The
worker thread itself is tested through Raster-Karten's job
(test_raster_karten_view.py)."""

import threading
import time

import pytest

import area_job


def test_before_the_first_kachel_the_estimate_is_the_pre_job_one():
    assert area_job.duration_caption(area_job.new_state(), "static") == "static"


def test_the_remaining_time_comes_from_the_finished_kacheln_only():
    # 3 of 5 kacheln in 60 s: 40 s left, however long the 4th has been running.
    state = {
        **area_job.new_state(),
        "started_at": time.time() - 300,
        "kacheln_done": 3,
        "kacheln_total": 5,
        "elapsed_at_last_progress": 60.0,
    }
    caption = area_job.duration_caption(state, "static")
    assert "40s" in caption and "5.0 min" in caption


@pytest.mark.parametrize(
    ("done", "total", "text"),
    [(0, 0, "Starte…"), (0, 4, "Kachel 1/4"), (3, 4, "Kachel 4/4"), (4, 4, "Schreibe Ergebnis…")],
)
def test_the_step_names_the_kachel_in_flight(done, total, text):
    state = {**area_job.new_state(), "kacheln_done": done, "kacheln_total": total}
    assert area_job.step_text(state) == text


def test_the_step_is_in_the_session_language_not_probe_cores(french_session):
    """probe-core's own message ("Kachel 1/4") is German whatever the session's language."""
    state = area_job.new_state()
    area_job.report_progress(state, threading.Event(), 0, 4, "Kachel 1/4")
    assert area_job.step_text(state) == "[FR] Kachel 1/4"


@pytest.mark.parametrize(
    ("seconds", "text"), [(0, "0s"), (89, "89s"), (90, "1.5 min"), (600, "10.0 min")]
)
def test_durations_switch_to_minutes_at_90_seconds(seconds, text):
    assert area_job.format_duration_s(seconds) == text
