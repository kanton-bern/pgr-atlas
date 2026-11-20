"""Raster-Karten: its job on the worker thread (area_job.run), and the
selection checks of ui_common."""

import math
import threading

import pytest
from shapely.geometry import Point, Polygon

import area_job
import raster_jobs
from probe_core.derivate import ifk_and_raster
from ui_common import checked_selection, selection_footprint, selection_size_label
from views import raster_karten as rk

_REQ = {
    "mode": "a",
    "variable": "depth",
    "threshold": 0.5,
    "return_period": None,
    "selection": {"type": "bbox", "ring": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]},
}


@pytest.fixture()
def job(tmp_path, monkeypatch):
    """_run_job with a fake build and run slots that count: `build` is what
    build_raster_for_bbox does (it gets the call's kwargs), `curves_exist`
    makes it a curves-cache hit."""
    calls = {"acquired": 0, "released": 0, "build": None, "kwargs": None}
    curves = tmp_path / "curves.parquet"
    monkeypatch.setattr(rk, "_raster_curves_path", lambda request: curves)

    def acquire(abort):
        calls["acquired"] += 1
        return not abort.is_set()

    def release():
        calls["released"] += 1

    def build(selection, mode, **kwargs):
        calls["kwargs"] = kwargs
        return calls["build"](kwargs)

    monkeypatch.setattr(raster_jobs, "acquire_run_slot", acquire)
    monkeypatch.setattr(raster_jobs, "release_run_slot", release)
    monkeypatch.setattr(ifk_and_raster, "build_raster_for_bbox", build)

    def run(build_fn, request=_REQ, abort=None, curves_exist=False):
        if curves_exist:
            curves.touch()
        calls["build"] = build_fn
        state = area_job.new_state()
        rk._run_job(request, state, str(tmp_path), abort or threading.Event())
        return state, calls

    return run


def test_a_finished_job_stores_its_paths_and_gives_its_slot_back(job):
    state, calls = job(lambda kwargs: ["/out/depth_a.tif"])
    assert state["done"] and state["error"] is None
    assert state["value"] == ["/out/depth_a.tif"]
    assert not state["queued"]
    assert (calls["acquired"], calls["released"]) == (1, 1)


def test_a_curves_cache_hit_runs_without_a_slot(job):
    state, calls = job(lambda kwargs: [], curves_exist=True)
    assert state["done"] and state["value"] == []
    assert (calls["acquired"], calls["released"]) == (0, 0)


@pytest.mark.parametrize(("threshold", "passed"), [(0.0, 0.0), (None, 1.0), (0.3, 0.3)])
def test_the_threshold_is_passed_as_given_and_defaults_only_when_missing(job, threshold, passed):
    _, calls = job(lambda kwargs: [], request={**_REQ, "threshold": threshold})
    assert calls["kwargs"]["threshold"] == passed
    assert calls["kwargs"]["return_period"] == 300


def test_abort_during_the_build_stops_it_at_the_next_kachel(job):
    abort = threading.Event()
    reached = []

    def build(kwargs):
        kwargs["progress_callback"](1, 4, "Kachel 1/4")
        reached.append(1)
        abort.set()
        kwargs["progress_callback"](2, 4, "Kachel 2/4")
        reached.append(2)

    state, calls = job(build, abort=abort)
    assert reached == [1]
    assert state["done"] and state["error"] == area_job.ABORTED
    assert (state["kacheln_done"], state["kacheln_total"], state["progress"]) == (1, 4, 0.25)
    assert calls["released"] == 1


def test_abort_while_queued_never_builds(job):
    abort = threading.Event()
    abort.set()
    state, calls = job(lambda kwargs: pytest.fail("built after abort"), abort=abort)
    assert state["done"] and state["error"] == area_job.ABORTED
    assert calls["released"] == 0


def test_a_failing_build_logs_its_error_and_gives_its_slot_back(job, caplog):
    def build(kwargs):
        raise RuntimeError("S3 down")

    state, calls = job(build)
    assert state["done"] and state["error"] == area_job.FAILED
    assert calls["released"] == 1
    (record,) = caplog.records
    assert record.getMessage().startswith("Raster build failed (mode a, depth, threshold 0.5")
    assert "S3 down" in caplog.text


def test_a_failing_curves_lookup_ends_the_job(job, monkeypatch, caplog):
    def fail(request):
        raise OSError("no ETag")

    monkeypatch.setattr(rk, "_raster_curves_path", fail)
    state, calls = job(lambda kwargs: pytest.fail("built without curves"))
    assert state["done"] and state["error"] == area_job.FAILED
    assert calls["acquired"] == 0
    assert "Raster curves failed" in caplog.text and "no ETag" in caplog.text


def test_the_size_label_shows_the_box_and_the_area():
    assert selection_size_label(0, 0, 719, 406, 291_914) == "719 m × 406 m · 291'914 m²"
    # Kilometres from 1000 m on.
    assert selection_size_label(0, 0, 1500, 999, 1_498_500) == "1.50 km × 999 m · 1'498'500 m²"
    assert selection_size_label(0, 0, 1000, 1000, 1e6) == "1.00 km × 1.00 km · 1'000'000 m²"


def _ring(points):
    return [[2600000 + x, 1200000 + y] for x, y in points + points[:1]]


def test_selection_footprint_takes_a_rectangles_centres_on_its_edge():
    selection = {
        "type": "bbox",
        "ring": _ring([(2.5, 2.5), (102.5, 2.5), (102.5, 52.5), (2.5, 52.5)]),
    }
    assert selection_footprint(selection) == (2600000, 1200000, 2600105, 1200055, 105 * 55)


def test_selection_footprint_takes_a_polygons_centres_strictly_inside():
    # Same numbers as the map's readout (pixel-footprint.test.ts): 19 x 9 pixels.
    selection = {
        "type": "polygon",
        "ring": _ring([(2.5, 2.5), (102.5, 2.5), (102.5, 52.5), (2.5, 52.5)]),
    }
    assert selection_footprint(selection) == (2600005, 1200005, 2600100, 1200050, 95 * 45)


def test_selection_footprint_counts_a_triangles_pixels():
    points = [(1, 1), (48, 3), (7, 44)]
    selection = {"type": "polygon", "ring": _ring(points)}
    inside = Polygon(selection["ring"])
    pixels = [
        (2600000 + x + 2.5, 1200000 + y + 2.5) for x in range(0, 50, 5) for y in range(0, 50, 5)
    ]
    expected = sum(inside.contains(Point(p)) for p in pixels)
    assert selection_footprint(selection)[4] == expected * 25


def test_selection_footprint_of_a_sliver_is_empty():
    selection = {"type": "polygon", "ring": _ring([(0, 0), (50, 1), (0, 2)])}
    assert selection_footprint(selection) == (2600000, 1200000, 2600050, 1200002, 0.0)


_RING = [[2600000, 1200000], [2600100, 1200000], [2600100, 1200050], [2600000, 1200000]]


def test_a_map_selection_is_kept_with_float_coordinates():
    selection = checked_selection({"type": "polygon", "ring": _RING, "extra": 1})
    assert selection == {"type": "polygon", "ring": _RING}
    assert all(isinstance(v, float) for point in selection["ring"] for v in point)
    assert checked_selection(None) is None


@pytest.mark.parametrize(
    "selection",
    [
        "polygon",
        {"type": "circle", "ring": _RING},
        {"type": "polygon"},
        {"type": "polygon", "ring": _RING[:2] + _RING[:1]},
        {"type": "polygon", "ring": _RING[:3]},  # not closed
        {"type": "polygon", "ring": [[2600000, 1200000, 0], *_RING[1:]]},
        {"type": "polygon", "ring": [["2600000", 1200000], *_RING[1:3], ["2600000", 1200000]]},
        {"type": "polygon", "ring": [[True, 1200000], *_RING[1:]]},
        {"type": "polygon", "ring": [[math.nan, 1200000], *_RING[1:]]},
        # Bounds like these made the kachel count run without end.
        {"type": "bbox", "ring": [[0, 0], [1e12, 0], [1e12, 1e12], [0, 0]]},
        {"type": "polygon", "ring": [_RING[0]] * 5002},
    ],
)
def test_a_malformed_map_selection_is_refused(selection):
    with pytest.raises(ValueError):
        checked_selection(selection)
