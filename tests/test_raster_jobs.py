import threading
from pathlib import Path

import pytest

import raster_jobs
from tests.test_derivate_bbox_server import FakeClock


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(raster_jobs, "_jobs", {})
    monkeypatch.setattr(raster_jobs, "_downloads", {})
    monkeypatch.setattr(raster_jobs, "_files", {})
    fake = FakeClock()
    monkeypatch.setattr(raster_jobs, "time", fake)
    return fake


def test_registered_job_is_returned_by_id():
    job_id = raster_jobs.register({"depth": "/tmp/depth_1.tif"}, {"mode": "a"})

    job = raster_jobs.get(job_id)
    assert job.paths == {"depth": Path("/tmp/depth_1.tif")}
    assert job.meta == {"mode": "a"}


def test_ids_are_unguessable_and_url_safe():
    ids = {raster_jobs.register({}, {"mode": "a"}) for _ in range(20)}

    assert len(ids) == 20
    assert all(
        len(job_id) >= 43 and all(character.isalnum() or character in "-_" for character in job_id)
        for job_id in ids
    )


def test_unknown_id_is_none():
    raster_jobs.register({}, {"mode": "a"})

    assert raster_jobs.get("nope") is None


def test_job_expires_after_the_ttl(clock):
    job_id = raster_jobs.register({}, {"mode": "a"})

    clock.now += raster_jobs.JOB_TTL_S - 1
    assert raster_jobs.get(job_id) is not None
    clock.now += 1
    assert raster_jobs.get(job_id) is None


def test_oldest_job_is_evicted_past_the_cap(clock):
    ids = []
    for _ in range(raster_jobs.MAX_JOBS + 1):
        ids.append(raster_jobs.register({}, {"mode": "a"}))
        clock.now += 1

    assert raster_jobs.get(ids[0]) is None
    assert all(raster_jobs.get(job_id) is not None for job_id in ids[1:])
    assert len(raster_jobs._jobs) == raster_jobs.MAX_JOBS


def test_unknown_variable_is_rejected():
    with pytest.raises(ValueError, match="secret"):
        raster_jobs.register({"../secret": "/etc/passwd"}, {"mode": "a"})


def test_meta_is_copied():
    meta = {"mode": "a"}
    job_id = raster_jobs.register({}, meta)
    meta["mode"] = "b"

    assert raster_jobs.get(job_id).meta == {"mode": "a"}


SELECTION = {"type": "bbox", "ring": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]}


def test_registered_download_is_returned_by_id():
    download_id = raster_jobs.register_download("kacheln", [["a/kachel_1.tif", "k/1"]])

    download = raster_jobs.get_download(download_id)
    assert download.kind == "kacheln"
    assert download.items == (("a/kachel_1.tif", "k/1"),)
    assert download.selection is None


def test_crop_download_keeps_a_copy_of_its_selection():
    selection = dict(SELECTION)
    download_id = raster_jobs.register_download("crop", [("hit_rate", "depth")], selection)
    selection["type"] = "polygon"

    assert raster_jobs.get_download(download_id).selection == SELECTION


def test_download_expires_after_the_ttl(clock):
    download_id = raster_jobs.register_download("kacheln", [])

    clock.now += raster_jobs.JOB_TTL_S
    assert raster_jobs.get_download(download_id) is None


def test_downloads_never_evict_jobs(clock):
    job_id = raster_jobs.register({}, {"mode": "a"})
    for _ in range(raster_jobs.MAX_JOBS + 1):
        raster_jobs.register_download("kacheln", [])
        clock.now += 1

    assert raster_jobs.get(job_id) is not None
    assert len(raster_jobs._downloads) == raster_jobs.MAX_JOBS


def test_a_job_id_is_not_a_download_id():
    job_id = raster_jobs.register({}, {"mode": "a"})

    assert raster_jobs.get_download(job_id) is None


def test_bad_download_requests_are_rejected():
    with pytest.raises(ValueError, match="'zip'"):
        raster_jobs.register_download("zip", [])
    with pytest.raises(ValueError, match="selection"):
        raster_jobs.register_download("crop", [("hit_rate", "depth")])


def test_a_second_job_waits_for_the_running_one():
    running, waiting = threading.Event(), threading.Event()
    assert raster_jobs.acquire_run_slot(running)
    got = []
    waiter = threading.Thread(
        target=lambda: got.append(raster_jobs.acquire_run_slot(waiting, poll_s=0.01))
    )
    waiter.start()
    waiter.join(0.2)
    assert waiter.is_alive()  # still queued
    raster_jobs.release_run_slot()
    waiter.join(2)
    assert got == [True]
    raster_jobs.release_run_slot()


def test_a_job_cancelled_while_queued_never_gets_a_slot():
    running, waiting = threading.Event(), threading.Event()
    assert raster_jobs.acquire_run_slot(running)
    got = []
    waiter = threading.Thread(
        target=lambda: got.append(raster_jobs.acquire_run_slot(waiting, poll_s=0.01))
    )
    waiter.start()
    waiting.set()
    waiter.join(2)
    assert got == [False]
    raster_jobs.release_run_slot()
    assert raster_jobs.acquire_run_slot(threading.Event())  # the slot is free again
    raster_jobs.release_run_slot()


def test_a_registered_file_is_returned_by_id_until_it_expires(clock):
    file_id = raster_jobs.register_file("/tmp/rohdaten.csv", "ifk_gebiet_rohdaten.csv", "text/csv")

    entry = raster_jobs.get_file(file_id)
    assert (entry.path, entry.download_name, entry.content_type) == (
        Path("/tmp/rohdaten.csv"),
        "ifk_gebiet_rohdaten.csv",
        "text/csv",
    )
    assert raster_jobs.get(file_id) is None  # a registry of its own
    clock.now += raster_jobs.JOB_TTL_S
    assert raster_jobs.get_file(file_id) is None
