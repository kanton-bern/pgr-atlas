import asyncio
import json
import socket
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest import mock

import numpy as np
import tornado.testing
from tornado.iostream import IOStream
from tornado.simple_httpclient import HTTPStreamClosedError

import derivate_bbox_server
import derivate_download
import raster_jobs
import raster_overlay
import work_dirs
from tests.raster_fixtures import write_geotiff

LOCAL_ORIGIN = "http://localhost:8501"
VALUE_QUERY = "/value.json?metric=affected_mask&band=1&e=2600000&n=1200000"
BBOX_BOGUS_SCALE = (
    "/bbox.png?metric=affected_mask&band=1&scale=bogus"
    "&west=7.5&south=46.4&east=7.6&north=46.5&width=256&height=256"
)
TTL = derivate_bbox_server._MOSAIC_CACHE_TTL_S


class FakeDataset:
    """Stands in for an open rasterio dataset and records misuse: a read after
    close, a close during a read, and two reads at once."""

    count = 1
    height = 10
    width = 10
    nodata = None

    def __init__(self, inside=True, read_s=0.0):
        self.inside = inside
        self.read_s = read_s
        self.closed = False
        self.active_reads = 0
        self.violations = []

    def index(self, e, n):
        return (0, 0) if self.inside else (-1, -1)

    def read(self, band, window=None, **kwargs):
        if self.closed:
            self.violations.append("read after close")
        self.active_reads += 1
        if self.active_reads > 1:
            self.violations.append("concurrent read")
        time.sleep(self.read_s)
        self.active_reads -= 1
        return np.array([[1.5]], dtype=np.float32)

    def close(self):
        if self.active_reads:
            self.violations.append("closed during a read")
        self.closed = True


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class _MosaicTestCase:
    """S3, rasterio.open and the module's clock replaced; the cache emptied."""

    def patch_boundaries(self, open_dataset):
        self.opened = []

        def fake_open(path):
            dataset = open_dataset(path)
            self.opened.append(dataset)
            return dataset

        self.clock = FakeClock()
        self.key_exists = mock.Mock(return_value=True)
        for target, value in (
            ("s3_key_exists", self.key_exists),
            ("s3_presigned_url", lambda bucket, key: f"https://s3.example/{key}?X-Amz-Signature=s"),
            ("time", self.clock),
        ):
            patcher = mock.patch.object(derivate_bbox_server, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(derivate_bbox_server.rasterio, "open", side_effect=fake_open)
        patcher.start()
        self.addCleanup(patcher.stop)
        derivate_bbox_server._mosaic_cache.clear()
        derivate_bbox_server._load_locks.clear()
        self.addCleanup(derivate_bbox_server._mosaic_cache.clear)
        self.addCleanup(derivate_bbox_server._load_locks.clear)


class ReadPacedExpiries:
    """Expires the mosaic by read progress, not wall time. In production a TTL
    (600 s) is far longer than any read waits for ds_lock, so one read sees at
    most one replacement. Expiring on a wall-clock interval would let a reader
    queued behind the others on a slow runner outlive two TTLs, which production
    never sees. So the next expiry waits until every reader has finished a read
    since the last one, and no read spans two expiries, however slow the
    runner. Reads are also held back by their number, so the run crosses
    `expiry_count` expiries."""

    def __init__(self, clock, reader_count, reads_per_expiry, expiry_count):
        self.clock = clock
        self.reads_per_expiry = reads_per_expiry
        self.expiry_count = expiry_count
        self.expiries = 0
        self.progress = threading.Condition()
        self.read_since_expiry = [False] * reader_count
        self.finished = [False] * reader_count

    def wait_before_read(self, read_number):
        with self.progress:
            self.progress.wait_for(lambda: self.expiries >= read_number // self.reads_per_expiry)

    def read_done(self, reader_index):
        with self.progress:
            self.read_since_expiry[reader_index] = True
            self.progress.notify_all()

    def reader_finished(self, reader_index):
        with self.progress:
            self.finished[reader_index] = True
            self.progress.notify_all()

    def _every_reader_read_or_finished(self):
        return all(
            read or finished for read, finished in zip(self.read_since_expiry, self.finished)
        )

    def run(self):
        for _ in range(self.expiry_count):
            with self.progress:
                self.progress.wait_for(self._every_reader_read_or_finished)
                self.clock.now += TTL
                self.expiries += 1
                self.read_since_expiry = [False] * len(self.read_since_expiry)
                self.progress.notify_all()


class ExpiryUnderLoadTest(_MosaicTestCase, tornado.testing.AsyncTestCase):
    def test_no_read_touches_a_closed_dataset_across_expiries(self):
        self.patch_boundaries(lambda path: FakeDataset(read_s=0.001))
        reader_count, reads_per_reader, reads_per_expiry = 8, 30, 3
        expiries = ReadPacedExpiries(
            self.clock, reader_count, reads_per_expiry, reads_per_reader // reads_per_expiry
        )
        errors = []

        def reader(reader_index):
            try:
                for read_number in range(reads_per_reader):
                    expiries.wait_before_read(read_number)
                    self.assertEqual(
                        derivate_bbox_server._point_value("affected_mask", None, 1, 0, 0), 1.5
                    )
                    expiries.read_done(reader_index)
            except Exception as error:  # collected and asserted below
                errors.append(error)
            finally:
                expiries.reader_finished(reader_index)

        ticker = threading.Thread(target=expiries.run)
        ticker.start()
        readers = [threading.Thread(target=reader, args=(index,)) for index in range(reader_count)]
        for reader_thread in readers:
            reader_thread.start()
        for reader_thread in readers:
            reader_thread.join()
        ticker.join()

        self.assertEqual(errors, [])
        self.assertGreater(len(self.opened), 2, "the run should cross several expiries")
        self.assertEqual([v for dataset in self.opened for v in dataset.violations], [])
        self.assertTrue(all(dataset.closed for dataset in self.opened[:-1]))
        self.assertFalse(self.opened[-1].closed)

    def test_read_that_looked_up_the_entry_before_an_expiry_uses_the_new_dataset(self):
        """Forces the interleaving the load test only hits by chance: the entry
        is looked up, then replaced and closed, then read."""
        self.patch_boundaries(lambda path: FakeDataset())
        get_context = derivate_bbox_server._get_mosaic_context
        stale = get_context("affected_mask", None)
        self.clock.now += TTL
        get_context("affected_mask", None)
        lookups = iter([stale])

        with mock.patch.object(
            derivate_bbox_server,
            "_get_mosaic_context",
            side_effect=lambda *args: next(lookups, None) or get_context(*args),
        ):
            value = derivate_bbox_server._point_value("affected_mask", None, 1, 0, 0)

        self.assertEqual(value, 1.5)
        self.assertTrue(stale["closed"])
        self.assertEqual([v for dataset in self.opened for v in dataset.violations], [])


class SingleFlightTest(_MosaicTestCase, tornado.testing.AsyncTestCase):
    def setUp(self):
        super().setUp()
        self.release = threading.Event()

        def open_dataset(path):
            if "affected_mask" in path:
                self.release.wait(5)
            return FakeDataset()

        self.patch_boundaries(open_dataset)
        self.addCleanup(self.release.set)

    def _in_thread(self, metric):
        result = {}
        thread = threading.Thread(
            target=lambda: result.setdefault(
                "value", derivate_bbox_server._point_value(metric, None, 1, 0, 0)
            )
        )
        thread.start()
        return thread, result

    def test_slow_open_of_one_mosaic_does_not_block_another(self):
        slow, _ = self._in_thread("affected_mask")

        fast, result = self._in_thread("sim_count")
        fast.join(2)

        self.assertFalse(fast.is_alive(), "sim_count waited for affected_mask's open")
        self.assertEqual(result["value"], 1.5)
        self.release.set()
        slow.join()

    def test_concurrent_requests_for_one_mosaic_open_it_once(self):
        threads = [self._in_thread("affected_mask")[0] for _ in range(8)]
        time.sleep(0.05)
        self.release.set()
        for thread in threads:
            thread.join()

        self.assertEqual(len(self.opened), 1)


class _ServerTestCase(_MosaicTestCase, tornado.testing.AsyncHTTPTestCase):
    dataset = FakeDataset

    def get_app(self):
        return derivate_bbox_server.make_app()

    def setUp(self):
        super().setUp()
        self.patch_boundaries(lambda path: self.dataset())


class ValueTest(_ServerTestCase):
    def test_point_inside_the_mosaic_returns_its_value(self):
        response = self.fetch(VALUE_QUERY)

        self.assertEqual(response.code, 200)
        self.assertEqual(json.loads(response.body), {"value": 1.5})


class OutsideTest(_ServerTestCase):
    dataset = staticmethod(lambda: FakeDataset(inside=False))

    def test_point_outside_the_mosaic_gets_404(self):
        response = self.fetch(VALUE_QUERY)

        self.assertEqual(response.code, 404)
        self.assertEqual(response.body, b"not found")


class ErrorBodyTest(_ServerTestCase):
    def test_bad_requests_get_a_generic_400_and_the_detail_is_logged(self):
        for query, detail in (
            ("/value.json?metric=secret_metric&band=1&e=1&n=2", "secret_metric"),
            (
                "/value.json?metric=affected_mask&partition=depth&band=1&e=1&n=2",
                "partition must be None",
            ),
            ("/value.json?metric=hit_rate&partition=..%2Fsecret&band=1&e=1&n=2", "bad partition"),
            ("/value.json?metric=affected_mask&band=7&e=1&n=2", "band 7 out of range"),
            ("/value.json?metric=affected_mask&band=x&e=1&n=2", "invalid literal"),
            (BBOX_BOGUS_SCALE, "scale must be one of"),
        ):
            with (
                self.subTest(query=query),
                self.assertLogs("derivate_bbox_server", "WARNING") as logs,
            ):
                response = self.fetch(query)

                self.assertEqual(response.code, 400)
                self.assertEqual(response.body, b"bad request")
                self.assertIn(detail, logs.output[0])

    def test_missing_mosaic_gets_a_generic_404_without_the_script_hint(self):
        self.key_exists.return_value = False

        with self.assertLogs("derivate_bbox_server", "WARNING") as logs:
            response = self.fetch(VALUE_QUERY)

        self.assertEqual(response.code, 404)
        self.assertEqual(response.body, b"not found")
        self.assertIn("run_derivate.py", logs.output[0])


class CorsTest(_ServerTestCase):
    def test_allowed_origin_is_echoed_and_x_corners_exposed_on_bbox(self):
        response = self.fetch("/bbox.png", headers={"Origin": LOCAL_ORIGIN}, method="OPTIONS")

        self.assertEqual(response.headers["Access-Control-Allow-Origin"], LOCAL_ORIGIN)
        self.assertEqual(response.headers["Access-Control-Expose-Headers"], "X-Corners")

    def test_foreign_origin_gets_no_allow_origin(self):
        for path in (VALUE_QUERY, "/bbox.png?metric=nope"):
            with self.subTest(path=path):
                response = self.fetch(path, headers={"Origin": "https://evil.example"})

                self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_allowed_origin_survives_an_error_response(self):
        with self.assertLogs("derivate_bbox_server", "WARNING"):
            response = self.fetch("/value.json?metric=nope", headers={"Origin": LOCAL_ORIGIN})

        self.assertEqual(response.code, 400)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], LOCAL_ORIGIN)


class HealthTest(_ServerTestCase):
    def test_healthz_answers_without_s3(self):
        response = self.fetch("/healthz")

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, b"ok")
        self.key_exists.assert_not_called()


class _JobRouteTestCase(tornado.testing.AsyncHTTPTestCase):
    """A real GeoTIFF registered as a Raster-Karten job; the registry's clock
    is fake. Not _ServerTestCase: that one fakes rasterio.open."""

    def get_app(self):
        return derivate_bbox_server.make_app()

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        for target, value in (("_jobs", {}), ("time", self.clock)):
            patcher = mock.patch.object(raster_jobs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.arr = np.array([[1.0, 2.0, 3.0], [-9999.0, 5.0, 6.0]], dtype=np.float32)
        self.tif = write_geotiff(
            Path(temp_dir.name) / "depth_rp300_1_2_3_4.tif", self.arr, nodata=-9999.0
        )
        self.job_id = raster_jobs.register({"depth": self.tif}, {"mode": "b"})

    def job_url(self, var="depth", ext="png", job_id=None):
        return f"/job/{job_id or self.job_id}/{var}.{ext}"


class JobFileTest(_JobRouteTestCase):
    def test_png_is_the_overlay_image(self):
        response = self.fetch(self.job_url(ext="png"))

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        self.assertEqual(response.headers["Cache-Control"], "private, max-age=3600")
        self.assertEqual(response.body, raster_overlay.render_png(self.tif, "b"))

    def test_f32_round_trips_the_values_with_nan_for_nodata(self):
        response = self.fetch(self.job_url(ext="f32"))

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
        grid = np.frombuffer(response.body, dtype="<f4").reshape(self.arr.shape)
        self.assertEqual(grid[0].tolist(), [1.0, 2.0, 3.0])
        self.assertTrue(np.isnan(grid[1, 0]))

    def test_tif_is_the_geotiff_as_a_download_with_its_german_name(self):
        response = self.fetch(self.job_url(ext="tif"))

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers["Content-Type"], "image/tiff")
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="adhoc_intensitaet_fliesstiefe_300_jahre_1_2_3_4.tif"',
        )
        self.assertEqual(response.body, self.tif.read_bytes())

    def test_allowed_origin_can_read_it(self):
        response = self.fetch(self.job_url(ext="f32"), headers={"Origin": LOCAL_ORIGIN})

        self.assertEqual(response.headers["Access-Control-Allow-Origin"], LOCAL_ORIGIN)


class JobNotFoundTest(_JobRouteTestCase):
    def assert_generic_404(self, url):
        response = self.fetch(url)

        self.assertEqual(response.code, 404)
        self.assertEqual(response.body, b"not found")

    def test_unknown_job(self):
        self.assert_generic_404(self.job_url(job_id="x" * 43))

    def test_expired_job(self):
        self.clock.now += raster_jobs.JOB_TTL_S

        self.assert_generic_404(self.job_url())

    def test_variable_the_job_does_not_have(self):
        self.assert_generic_404(self.job_url(var="velocity"))

    def test_nothing_outside_the_job_is_reachable(self):
        for url in (
            self.job_url(var="..%2Fdepth"),
            f"/job/{self.job_id}/../depth.png",
            f"/job/{self.job_id}/depth.txt",
            f"/job/{self.job_id}/DEPTH.png",
            f"/job/{self.job_id}/depth/x.png",
        ):
            with self.subTest(url=url):
                self.assertEqual(self.fetch(url).code, 404)

    def test_deleted_geotiff_gets_404_and_the_id_is_not_logged(self):
        self.tif.unlink()

        for ext in ("png", "f32", "tif"):
            with self.subTest(ext=ext), self.assertLogs("derivate_bbox_server", "WARNING") as logs:
                self.assert_generic_404(self.job_url(ext=ext))

                self.assertNotIn(self.job_id, "\n".join(logs.output))


class CogKeyTest(unittest.TestCase):
    def test_gebaeudeschatten_masks_resolve_by_variant_reach_and_min_depth(self):
        self.assertEqual(
            derivate_bbox_server._cog_key(
                derivate_bbox_server.GEBAEUDESCHATTEN_METRIC,
                "shadowing_building_surrounding_100_10",
            ),
            "Gebaeudeschatten-Data-Lake-Derivate/affected_mask/"
            "canton_affected_mask_shadowing_building_surrounding_100m_min10cm.tif",
        )

    def test_derivate_lake_metrics_are_unchanged(self):
        self.assertEqual(
            derivate_bbox_server._cog_key("affected_mask", None),
            "Data-Lake-Derivate/affected_mask/_mosaic/canton.tif",
        )

    def test_bad_requests(self):
        for metric, partition in [
            (derivate_bbox_server.GEBAEUDESCHATTEN_METRIC, "raw_200_1"),  # unknown reach
            (derivate_bbox_server.GEBAEUDESCHATTEN_METRIC, "any_building_800_1"),  # unknown variant
            (derivate_bbox_server.GEBAEUDESCHATTEN_METRIC, "raw_800_5"),  # unknown minimum depth
            (derivate_bbox_server.GEBAEUDESCHATTEN_METRIC, "raw_800"),  # minimum depth missing
            (derivate_bbox_server.GEBAEUDESCHATTEN_METRIC, None),
            ("no_such_metric", None),
        ]:
            with self.subTest(metric=metric, partition=partition):
                with self.assertRaises(derivate_bbox_server._BadRequest):
                    derivate_bbox_server._cog_key(metric, partition)


PRESIGNED_URL = "https://s3.example/mosaic.tif?X-Amz-Signature=secret"
CHUNK = derivate_download.CHUNK_SIZE
SELECTION = {"type": "bbox", "ring": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]}


class _FakeBody:
    """An S3 object body that records every read, so a test can tell the
    handler never read a whole object at once. fail_after: raise on the read
    after this many bytes."""

    def __init__(self, data, fail_after=None):
        self.data = data
        self.pos = 0
        self.fail_after = fail_after
        self.reads = []
        self.closed = False

    def read(self, amt=None):
        self.reads.append(amt)
        if self.fail_after is not None and self.pos >= self.fail_after:
            raise OSError(f"read of {PRESIGNED_URL} timed out")
        amt = len(self.data) if amt is None else amt
        chunk = self.data[self.pos : self.pos + amt]
        self.pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class _FakeS3:
    def __init__(self, bodies):
        self.bodies = bodies

    def get_object(self, Bucket, Key):
        body = self.bodies[Key]
        return {"ContentLength": len(body.data), "Body": body}


class _DownloadRouteTestCase(tornado.testing.AsyncHTTPTestCase):
    """ZIPs registered in raster_jobs; S3 and the mosaic crop replaced."""

    def get_app(self):
        return derivate_bbox_server.make_app()

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.bodies = {
            "k/1.tif": _FakeBody(b"a" * (3 * CHUNK + 5)),
            "k/2.tif": _FakeBody(b"b" * 10),
        }
        self.crops = {("hit_rate", "depth"): b"crop" * 1000, ("sim_count", None): None}
        for target, value in (("_downloads", {}), ("time", self.clock)):
            self.patch(raster_jobs, target, value)
        self.patch(derivate_download, "get_s3_client", lambda: _FakeS3(self.bodies))
        self.patch(derivate_download.derivate_lake, "crop_mosaic_to_selection", self.fake_crop)

    def patch(self, target, name, value):
        patcher = mock.patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_crop(self, metric, partition, selection, out_path):
        data = self.crops[(metric, partition)]
        if isinstance(data, Exception):
            raise data
        if data is None:
            return False
        Path(out_path).write_bytes(data)
        return True

    def download(self, kind, items, selection=None):
        download_id = raster_jobs.register_download(kind, items, selection)
        return self.fetch(f"/download/{download_id}.zip")


class DownloadTest(_DownloadRouteTestCase):
    def test_kachel_zip_holds_every_object_unchanged(self):
        response = self.download(
            "kacheln", [("m/kachel_1.tif", "k/1.tif"), ("m/kachel_2.tif", "k/2.tif")]
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers["Content-Type"], "application/zip")
        self.assertEqual(
            response.headers["Content-Disposition"], 'attachment; filename="derivat_kacheln.zip"'
        )
        with zipfile.ZipFile(BytesIO(response.body)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.namelist(), ["m/kachel_1.tif", "m/kachel_2.tif"])
            self.assertEqual(archive.read("m/kachel_1.tif"), self.bodies["k/1.tif"].data)
            self.assertEqual(archive.read("m/kachel_2.tif"), self.bodies["k/2.tif"].data)
            self.assertTrue(
                all(member.compress_type == zipfile.ZIP_STORED for member in archive.infolist())
            )

    def test_objects_are_read_chunk_by_chunk_and_closed(self):
        self.download("kacheln", [("a.tif", "k/1.tif"), ("b.tif", "k/2.tif")])

        for body in self.bodies.values():
            self.assertEqual(set(body.reads), {CHUNK}, "never a read of the whole object")
            self.assertTrue(body.closed)
        self.assertEqual(len(self.bodies["k/1.tif"].reads), 5)  # 4 chunks + the empty read

    def test_crop_zip_skips_a_dataset_without_data_and_deletes_the_crops(self):
        response = self.download("crop", [("hit_rate", "depth"), ("sim_count", None)], SELECTION)

        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="derivat_ausschnitt.zip"',
        )
        with zipfile.ZipFile(BytesIO(response.body)) as archive:
            self.assertEqual(
                archive.namelist(), ["derivat_trefferhaeufigkeit_fliesstiefe_ausschnitt.tif"]
            )
            self.assertEqual(
                archive.read("derivat_trefferhaeufigkeit_fliesstiefe_ausschnitt.tif"),
                self.crops[("hit_rate", "depth")],
            )
        self.assertEqual(list(work_dirs.kind_dir(work_dirs.RASTER_JOBS).iterdir()), [])

    def test_unknown_and_expired_ids_get_404(self):
        download_id = raster_jobs.register_download("kacheln", [("a.tif", "k/1.tif")])
        self.clock.now += raster_jobs.JOB_TTL_S

        for url in (f"/download/{download_id}.zip", f"/download/{'x' * 43}.zip"):
            with self.subTest(url=url):
                response = self.fetch(url)

                self.assertEqual(response.code, 404)
                self.assertEqual(response.body, b"not found")


class DownloadErrorTest(_DownloadRouteTestCase):
    def test_error_mid_stream_cuts_the_response_and_logs_without_the_signature(self):
        self.bodies["k/2.tif"] = _FakeBody(b"b" * (2 * CHUNK), fail_after=CHUNK)

        # Closed before the last chunk: the browser sees a failed download.
        with (
            self.assertLogs("derivate_bbox_server", "ERROR") as logs,
            self.assertRaises(HTTPStreamClosedError),
        ):
            self.download("kacheln", [("a.tif", "k/1.tif"), ("b.tif", "k/2.tif")])

        self.assertIn("https://s3.example/mosaic.tif?…", logs.output[0])
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertTrue(all(body.closed for body in self.bodies.values()))

    def test_error_before_the_first_byte_is_a_generic_502(self):
        self.crops[("hit_rate", "depth")] = OSError(f"'/vsicurl/{PRESIGNED_URL}' not recognized")

        with self.assertLogs("derivate_bbox_server", "ERROR") as logs:
            response = self.download("crop", [("hit_rate", "depth")], SELECTION)

        self.assertEqual(response.code, 502)
        self.assertEqual(response.body, b"upstream error")
        self.assertNotIn("Content-Disposition", response.headers)
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertEqual(list(work_dirs.kind_dir(work_dirs.RASTER_JOBS).iterdir()), [])


async def _until(condition, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


class DownloadLimitTest(_DownloadRouteTestCase):
    """One stream allowed, held by a client that sends its request and then
    never reads, so the server's socket buffer fills up and the stream stalls."""

    def setUp(self):
        super().setUp()
        self.patch(derivate_bbox_server, "_MAX_ZIP_STREAMS", 1)
        self.patch(derivate_bbox_server, "_CLIENT_STALL_TIMEOUT_S", 0.5)
        self.bodies["k/big.tif"] = _FakeBody(b"x" * (64 << 20))  # more than socket buffers hold

    async def start_stalled_client(self):
        download_id = raster_jobs.register_download("kacheln", [("big.tif", "k/big.tif")])
        stream = IOStream(socket.socket())
        self.addCleanup(stream.close)
        await stream.connect(("127.0.0.1", self.get_http_port()))
        await stream.write(f"GET /download/{download_id}.zip HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        await _until(lambda: derivate_bbox_server._active_zip_streams == 1)

    @tornado.testing.gen_test(timeout=30)
    async def test_stream_over_the_limit_gets_503_with_a_german_note(self):
        await self.start_stalled_client()
        download_id = raster_jobs.register_download("kacheln", [("a.tif", "k/2.tif")])

        with self.assertLogs("derivate_bbox_server", "WARNING"):
            busy = await self.http_client.fetch(
                self.get_url(f"/download/{download_id}.zip"), raise_error=False
            )

        self.assertEqual(busy.code, 503)
        self.assertEqual(busy.headers["Retry-After"], "60")
        self.assertIn("Bitte in einer Minute nochmals", busy.body.decode())

    @tornado.testing.gen_test(timeout=30)
    async def test_stalled_client_is_dropped_and_frees_its_slot_and_files(self):
        with self.assertLogs("derivate_bbox_server", "ERROR") as logs:
            await self.start_stalled_client()
            await _until(lambda: derivate_bbox_server._active_zip_streams == 0)

        self.assertIn("took no data", logs.output[0])
        self.assertEqual(list(work_dirs.kind_dir(work_dirs.RASTER_JOBS).iterdir()), [])
        download_id = raster_jobs.register_download("kacheln", [("a.tif", "k/2.tif")])
        response = await self.http_client.fetch(self.get_url(f"/download/{download_id}.zip"))
        self.assertEqual(response.code, 200)


class _RangeS3:
    """get_object for one canton mosaic, answering a Range like S3 does."""

    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    ETAG = '"v1"'
    LAST_MODIFIED = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)

    def get_object(self, Bucket, Key, Range=None, IfMatch=None):
        from botocore.exceptions import ClientError

        self.calls.append((Key, Range))
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        if IfMatch is not None and IfMatch != self.ETAG:
            raise ClientError({"Error": {"Code": "PreconditionFailed"}}, "GetObject")
        data = self.objects[Key]
        validators = {"ETag": self.ETAG, "LastModified": self.LAST_MODIFIED}
        if Range is None:
            return {"ContentLength": len(data), "Body": BytesIO(data)} | validators
        start, end = Range.removeprefix("bytes=").split("-")
        start, end = int(start), int(end) if end else len(data) - 1
        return {
            "ContentLength": end - start + 1,
            "Body": BytesIO(data[start : end + 1]),
            "ContentRange": f"bytes {start}-{end}/{len(data)}",
        } | validators


class CantonFileTest(tornado.testing.AsyncHTTPTestCase):
    MOSAIC = "Data-Lake-Derivate/hit_rate/_mosaic/variable=depth/canton.tif"

    def get_app(self):
        return derivate_bbox_server.make_app()

    def setUp(self):
        super().setUp()
        self.data = bytes(range(256)) * (3 * CHUNK // 256 + 1)
        self.s3 = _RangeS3({self.MOSAIC: self.data})
        patcher = mock.patch.object(derivate_download, "get_s3_client", lambda: self.s3)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_whole_file_with_its_name_and_length(self):
        response = self.fetch("/canton/hit_rate.tif?partition=depth")

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, self.data)
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="derivat_trefferhaeufigkeit_fliesstiefe_kanton_bern.tif"',
        )
        self.assertEqual(response.headers["Content-Length"], str(len(self.data)))
        self.assertEqual(response.headers["Accept-Ranges"], "bytes")
        # Browsers resume only with a validator.
        self.assertEqual(response.headers["ETag"], '"v1"')
        self.assertEqual(response.headers["Last-Modified"], "Wed, 30 Sep 2026 12:00:00 GMT")
        self.assertEqual(self.s3.calls, [(self.MOSAIC, None)])

    def test_a_resumed_download_gets_the_rest(self):
        response = self.fetch(
            "/canton/hit_rate.tif?partition=depth", headers={"Range": "bytes=100-"}
        )

        self.assertEqual(response.code, 206)
        self.assertEqual(response.body, self.data[100:])
        self.assertEqual(
            response.headers["Content-Range"], f"bytes 100-{len(self.data) - 1}/{len(self.data)}"
        )

    def test_a_resume_of_the_same_file_gets_the_rest(self):
        response = self.fetch(
            "/canton/hit_rate.tif?partition=depth",
            headers={"Range": "bytes=100-", "If-Range": '"v1"'},
        )
        self.assertEqual(response.code, 206)
        self.assertEqual(response.body, self.data[100:])

    def test_a_resume_after_the_file_changed_gets_all_of_the_new_one(self):
        response = self.fetch(
            "/canton/hit_rate.tif?partition=depth",
            headers={"Range": "bytes=100-", "If-Range": '"v0"'},
        )
        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, self.data)
        self.assertNotIn("Content-Range", response.headers)

    def test_gebaeudeschatten_mask_is_named_in_m(self):
        key = "Gebaeudeschatten-Data-Lake-Derivate/affected_mask/canton_affected_mask_raw_50m_min10cm.tif"
        self.s3.objects[key] = b"mask"
        response = self.fetch(
            f"/canton/{derivate_bbox_server.GEBAEUDESCHATTEN_METRIC}.tif?partition=raw_50_10"
        )

        self.assertEqual(response.body, b"mask")
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="gebaeudeschatten_maske_reichweite_50m_roh_ab_0_1m_kanton_bern.tif"',
        )

    def test_only_known_canton_files_are_served(self):
        for path in ("/canton/no_such_metric.tif", "/canton/hit_rate.tif?partition=../../secret"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path).code, 400)
        self.assertEqual(self.s3.calls, [])

    def test_a_mosaic_not_built_yet_is_404(self):
        self.assertEqual(self.fetch("/canton/hit_rate.tif?partition=velocity").code, 404)

    def test_a_malformed_range_is_416_and_never_reaches_s3(self):
        response = self.fetch(
            "/canton/hit_rate.tif?partition=depth", headers={"Range": "bytes=0-1,5-9"}
        )
        self.assertEqual(response.code, 416)
        self.assertEqual(self.s3.calls, [])

    def test_over_the_limit_gets_503_with_a_german_note(self):
        with mock.patch.object(
            derivate_bbox_server, "_active_canton_streams", derivate_bbox_server._MAX_CANTON_STREAMS
        ):
            response = self.fetch("/canton/hit_rate.tif?partition=depth")
        self.assertEqual(response.code, 503)
        self.assertIn("Kanton-Dateien", response.body.decode())


class FileRouteTest(tornado.testing.AsyncHTTPTestCase):
    """A file registered with raster_jobs.register_file (the Rohdaten of an
    area's IFK); the registry's clock is fake."""

    def get_app(self):
        return derivate_bbox_server.make_app()

    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        for target, value in (("_files", {}), ("time", self.clock)):
            patcher = mock.patch.object(raster_jobs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.path = Path(temp_dir.name) / "rohdaten_abc.csv"
        self.path.write_bytes(b"\xef\xbb\xbfid_anriss\n1\n")
        self.file_id = raster_jobs.register_file(
            self.path, "ifk_gebiet_rohdaten_1_2_3_4.csv", "text/csv"
        )

    def test_the_file_is_a_download_under_its_registered_name(self):
        response = self.fetch(f"/file/{self.file_id}")

        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers["Content-Type"], "text/csv")
        self.assertEqual(
            response.headers["Content-Disposition"],
            'attachment; filename="ifk_gebiet_rohdaten_1_2_3_4.csv"',
        )
        self.assertEqual(response.body, self.path.read_bytes())

    def test_unknown_expired_and_deleted_files_get_the_same_404(self):
        self.assertEqual(self.fetch("/file/" + "x" * 43).code, 404)
        self.path.unlink()
        with self.assertLogs("derivate_bbox_server", "WARNING") as logs:
            deleted = self.fetch(f"/file/{self.file_id}")
        self.assertEqual((deleted.code, deleted.body), (404, b"not found"))
        self.assertNotIn(self.file_id, "".join(logs.output))
        self.clock.now += raster_jobs.JOB_TTL_S
        self.assertEqual(self.fetch(f"/file/{self.file_id}").code, 404)

    def test_the_id_reaches_no_other_path(self):
        for url in (f"/file/{self.file_id}/../x", f"/file/..%2F{self.file_id}", "/file/"):
            with self.subTest(url=url):
                self.assertEqual(self.fetch(url).code, 404)
