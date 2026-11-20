"""Tests for derivate_download: size estimates and opening a ZIP's files ahead.
The streamed ZIP itself is tested through its route in
test_derivate_bbox_server.py."""

import io
import threading
import time

import derivate_download
import raster_jobs
import work_dirs
from derivate_download import (
    Prefetcher,
    estimate_zip_bytes,
    list_object_sizes,
)


class _FakeS3:
    """The list_objects_v2 paginator of an S3 client, serving fixed pages."""

    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.calls = []

    def get_paginator(self, operation: str):
        assert operation == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.pages)


def test_list_object_sizes_reads_every_page(monkeypatch):
    s3 = _FakeS3(
        [
            {"Contents": [{"Key": "d/id_kachel=1/data.tif", "Size": 10}]},
            {"Contents": [{"Key": "d/id_kachel=2/data.tif", "Size": 20}]},
            {},
        ]
    )
    monkeypatch.setattr(derivate_download, "get_s3_client", lambda: s3)

    sizes = list_object_sizes("gold", "d")

    assert sizes == {"d/id_kachel=1/data.tif": 10, "d/id_kachel=2/data.tif": 20}
    assert s3.calls == [{"Bucket": "gold", "Prefix": "d/"}]


def test_estimate_sums_listed_sizes():
    sizes = {"a": 100, "b": 250, "c": 999}

    assert estimate_zip_bytes(["a", "b"], sizes) == 350


def test_estimate_counts_unlisted_key_as_largest_tile_of_the_bundle():
    sizes = {"a": 100, "b": 250, "c": 999}

    assert estimate_zip_bytes(["a", "b", "new"], sizes) == 600


def test_estimate_with_no_listed_key_uses_largest_listed_object():
    sizes = {"a": 100, "b": 250}

    assert estimate_zip_bytes(["new1", "new2"], sizes) == 500


def test_estimate_ignores_the_mosaic_in_the_listing():
    sizes = {
        "d/id_kachel=1/data.tif": 100,
        "d/id_kachel=2/data.tif": 250,
        "d/_mosaic/canton.tif": 365_000_000,
    }

    keys = ["d/id_kachel=1/data.tif", "d/id_kachel=2/data.tif", "d/id_kachel=3/data.tif"]
    assert estimate_zip_bytes(keys, sizes) == 600


def test_estimate_of_nothing_is_zero():
    assert estimate_zip_bytes([], {}) == 0


class _CountingS3:
    """get_object for any key, recording which keys were opened."""

    def __init__(self):
        self.opened = []
        self.bodies = []
        self._lock = threading.Lock()

    def get_object(self, Bucket, Key):
        body = io.BytesIO(b"tif")
        with self._lock:
            self.opened.append(Key)
            self.bodies.append(body)
        return {"ContentLength": 3, "Body": body}


def _kacheln(n):
    return raster_jobs.Download(
        "kacheln", tuple((f"{i}.tif", f"k/{i}") for i in range(n)), None, 0.0
    )


def test_prefetcher_opens_files_in_order_and_only_a_few_ahead(monkeypatch):
    s3 = _CountingS3()
    monkeypatch.setattr(derivate_download, "get_s3_client", lambda: s3)

    files = Prefetcher(_kacheln(10), ahead=2)
    first = files.next().result()
    first.close()
    files.close()

    assert first.name == "0.tif"
    assert len(s3.opened) <= 3, "the first file plus two ahead"


def test_prefetcher_close_closes_what_was_not_taken_and_deletes_the_crops(monkeypatch):
    s3 = _CountingS3()
    monkeypatch.setattr(derivate_download, "get_s3_client", lambda: s3)

    files = Prefetcher(_kacheln(3))
    deadline = time.monotonic() + 5
    while len(s3.opened) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    files.close()

    assert len(s3.bodies) == 3 and all(body.closed for body in s3.bodies)
    assert list(work_dirs.kind_dir(work_dirs.RASTER_JOBS).iterdir()) == []


def test_prefetcher_hands_out_every_file_then_none(monkeypatch):
    monkeypatch.setattr(derivate_download, "get_s3_client", _CountingS3)

    files = Prefetcher(_kacheln(5), ahead=2)
    names = []
    while (future := files.next()) is not None:
        entry = future.result()
        names.append(entry.name)
        entry.close()
    files.close()

    assert names == ["0.tif", "1.tif", "2.tif", "3.tif", "4.tif"]
