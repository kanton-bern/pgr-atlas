import datetime
import gzip
import io
import socket
import threading
from unittest import mock

import tornado.testing
from botocore.exceptions import ClientError

import coverage_store
import pmtiles_server

LOCAL_ORIGIN = "http://localhost:8501"


def _s3_object(body=b"PMTi"):
    return {
        "ContentLength": len(body),
        "ContentRange": f"bytes 0-{len(body) - 1}/100",
        "ETag": '"abc123"',
        "LastModified": datetime.datetime(2026, 9, 1, 12, 0, tzinfo=datetime.timezone.utc),
        "Body": io.BytesIO(body),
    }


def _client_error(status):
    return ClientError(
        {
            "Error": {"Code": str(status), "Message": "bucket maxi said no"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "GetObject",
    )


def _unused_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ProxyTestCase(tornado.testing.AsyncHTTPTestCase):
    ready_urls = ()

    def get_app(self):
        return pmtiles_server.make_app(self.ready_urls)

    def setUp(self):
        super().setUp()
        self.s3 = mock.Mock()
        self.s3.get_object.return_value = _s3_object()
        patcher = mock.patch.object(pmtiles_server, "get_s3_client", return_value=self.s3)
        patcher.start()
        self.addCleanup(patcher.stop)


class TilesetKeyTest(_ProxyTestCase):
    def test_range_request_is_forwarded_and_answered_with_206(self):
        response = self.fetch("/tiles.pmtiles", headers={"Range": "bytes=0-3"})

        self.assertEqual(response.code, 206)
        self.assertEqual(response.body, b"PMTi")
        self.assertEqual(response.headers["Content-Range"], "bytes 0-3/100")
        self.s3.get_object.assert_called_once_with(
            Bucket=pmtiles_server.S3_BUCKET, Key="tiles.pmtiles", Range="bytes=0-3"
        )

    def test_keys_other_than_root_level_pmtiles_get_404_without_s3_call(self):
        for path in (
            "/gold/manifest.json",
            "/Data-Lake-Gold/part.pmtiles",
            "/..%2Fsecret.pmtiles",
            "/.pmtiles",
            "/tiles.pmtiles.bak",
            "/_shared/map_controls.js",
            "/",
        ):
            with self.subTest(path=path):
                response = self.fetch(path)

                self.assertEqual(response.code, 404)
                self.assertEqual(response.body, b"not found")
        self.s3.get_object.assert_not_called()


class CacheHeaderTest(_ProxyTestCase):
    def test_tileset_response_carries_validators_and_cache_control(self):
        response = self.fetch("/tiles.pmtiles", headers={"Range": "bytes=0-3"})

        self.assertEqual(response.headers["ETag"], '"abc123"')
        self.assertEqual(response.headers["Last-Modified"], "Tue, 01 Sep 2026 12:00:00 GMT")
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")


class ErrorBodyTest(_ProxyTestCase):
    def test_missing_key_gets_generic_404(self):
        self.s3.get_object.side_effect = _client_error(404)

        response = self.fetch("/tiles.pmtiles")

        self.assertEqual(response.code, 404)
        self.assertEqual(response.body, b"not found")

    def test_other_s3_error_gets_generic_502_without_bucket_details(self):
        self.s3.get_object.side_effect = _client_error(403)

        with self.assertLogs("pmtiles_server", "WARNING") as logs:
            response = self.fetch("/tiles.pmtiles")

        self.assertEqual(response.code, 502)
        self.assertEqual(response.body, b"upstream error")
        self.assertIn("tiles.pmtiles", logs.output[0])


class CorsTest(_ProxyTestCase):
    def test_allowed_origin_is_echoed_with_exposed_headers(self):
        response = self.fetch("/tiles.pmtiles", headers={"Origin": LOCAL_ORIGIN})

        self.assertEqual(response.headers["Access-Control-Allow-Origin"], LOCAL_ORIGIN)
        self.assertIn("ETag", response.headers["Access-Control-Expose-Headers"])
        self.assertEqual(response.headers["Vary"], "Origin")

    def test_foreign_origin_gets_no_allow_origin(self):
        for path in ("/tiles.pmtiles", "/coverage.geojson", "/nope.json"):
            with self.subTest(path=path):
                response = self.fetch(path, headers={"Origin": "https://evil.example"})

                self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_allowed_origins_come_from_the_environment(self):
        origin = "https://atlas.example"
        with mock.patch.dict("os.environ", {"SIDECAR_ALLOWED_ORIGINS": f" {origin}/ ,x"}):
            allowed = self.fetch("/tiles.pmtiles", headers={"Origin": origin})
            local = self.fetch("/tiles.pmtiles", headers={"Origin": LOCAL_ORIGIN})

        self.assertEqual(allowed.headers["Access-Control-Allow-Origin"], origin)
        self.assertNotIn("Access-Control-Allow-Origin", local.headers)


class HealthTest(_ProxyTestCase):
    def test_healthz_answers_without_s3(self):
        response = self.fetch("/healthz")

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, b"ok")
        self.s3.get_object.assert_not_called()

    def test_readyz_without_targets_is_ready(self):
        self.assertEqual(self.fetch("/readyz").code, 200)


class ReadyWithTargetsTest(_ProxyTestCase):
    """Our own /healthz stands in for a server that is up."""

    def get_app(self):
        self.ready_urls = (f"http://127.0.0.1:{self.get_http_port()}/healthz",)
        return super().get_app()

    def test_readyz_is_200_when_all_targets_are_up(self):
        response = self.fetch("/readyz")

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, b"ok")


class ReadyWithDownTargetTest(_ProxyTestCase):
    """A port nobody listens on stands in for a server that is down."""

    def get_app(self):
        self.ready_urls = (
            f"http://127.0.0.1:{self.get_http_port()}/healthz",
            f"http://127.0.0.1:{_unused_port()}/healthz",
        )
        return super().get_app()

    def test_readyz_is_503_when_a_target_is_down(self):
        with self.assertLogs("pmtiles_server", "WARNING"):
            response = self.fetch("/readyz")

        self.assertEqual(response.code, 503)
        self.assertEqual(response.body, b"not ready")


class S3CheckTest(_ProxyTestCase):
    """The background S3 check, one round at a time, and the two endpoints
    that report its last result."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pmtiles_server, "_s3_status", pmtiles_server._S3Status())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check(self, pending=None):
        return self.io_loop.run_sync(lambda: pmtiles_server._check_s3(pending))

    def test_before_the_first_check_nothing_is_reported_as_reachable(self):
        ready = self.fetch("/readyz-s3")
        metrics = self.fetch("/metrics")

        self.assertEqual(ready.code, 503)
        self.assertEqual(ready.body, b"s3 not checked yet")
        self.assertEqual(metrics.code, 200)
        self.assertEqual(metrics.body, b"")
        self.s3.head_bucket.assert_not_called()

    def test_reachable_bucket_is_reported_without_an_s3_call_per_request(self):
        with self.assertLogs("pmtiles_server", "INFO"):
            self.assertIsNone(self._check())

        ready = self.fetch("/readyz-s3")
        metrics = self.fetch("/metrics").body.decode()

        self.assertEqual(ready.code, 200)
        self.assertEqual(ready.body, b"ok")
        self.assertIn("\npgr_atlas_s3_reachable 1\n", metrics)
        self.assertRegex(metrics, r"\npgr_atlas_s3_last_check_timestamp_seconds \d{10}\n")
        self.s3.head_bucket.assert_called_once_with(Bucket=pmtiles_server.S3_BUCKET)

    def test_refused_key_is_reported_and_logged_once(self):
        self.s3.head_bucket.side_effect = _client_error(403)

        with self.assertLogs("pmtiles_server", "ERROR") as logs:
            self._check()
        with self.assertNoLogs("pmtiles_server", "ERROR"):
            self._check()

        ready = self.fetch("/readyz-s3")
        self.assertEqual(len(logs.output), 1)
        self.assertEqual(ready.code, 503)
        self.assertEqual(ready.body, b"s3 not reachable")
        self.assertIn("\npgr_atlas_s3_reachable 0\n", self.fetch("/metrics").body.decode())

    def test_recovery_is_reported(self):
        self.s3.head_bucket.side_effect = [_client_error(503), None]

        with self.assertLogs("pmtiles_server", "ERROR"):
            self._check()
        with self.assertLogs("pmtiles_server", "INFO"):
            self._check()

        self.assertEqual(self.fetch("/readyz-s3").code, 200)

    def test_unanswered_request_counts_as_not_reachable_and_is_not_repeated(self):
        answered = threading.Event()
        self.s3.head_bucket.side_effect = lambda **kwargs: answered.wait(5)
        self.addCleanup(answered.set)

        with (
            mock.patch.object(pmtiles_server, "_S3_CHECK_TIMEOUT_S", 0.05),
            self.assertLogs("pmtiles_server", "ERROR"),
        ):
            pending = self._check()
        self.assertIsNotNone(pending)
        self.assertEqual(self.fetch("/readyz-s3").code, 503)

        answered.set()
        with self.assertLogs("pmtiles_server", "INFO"):
            self.assertIsNone(self._check(pending))
        self.assertEqual(self.fetch("/readyz-s3").code, 200)
        self.s3.head_bucket.assert_called_once()


class CoverageTest(_ProxyTestCase):
    geojson = '{"type": "FeatureCollection", "features": []}'

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(coverage_store, "_by_name", {})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unknown_or_missing_version_is_404_without_s3_call(self):
        coverage_store.publish("gold", self.geojson)

        for path in ("/coverage.geojson?v=0000000000000000", "/coverage.geojson"):
            with self.subTest(path=path):
                response = self.fetch(path)

                self.assertEqual(response.code, 404)
                self.assertNotIn("Cache-Control", response.headers)
        self.s3.get_object.assert_not_called()

    def test_published_version_is_served_immutable_with_etag(self):
        version = coverage_store.publish("gold", self.geojson)

        response = self.fetch(
            f"/coverage.geojson?v={version}",
            decompress_response=False,
            headers={"Accept-Encoding": "identity"},
        )

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, self.geojson.encode())
        self.assertEqual(response.headers["Content-Type"], "application/geo+json")
        self.assertEqual(response.headers["ETag"], f'W/"{version}"')
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertNotIn("Content-Encoding", response.headers)
        self.s3.get_object.assert_not_called()

    def test_each_name_is_served_by_its_own_version(self):
        gold = coverage_store.publish("gold", self.geojson)
        derivate = coverage_store.publish(
            "derivate/sim_count/None", self.geojson.replace("[]", "[null]")
        )

        self.assertEqual(self.fetch(f"/coverage.geojson?v={gold}").body, self.geojson.encode())
        self.assertIn(b"[null]", self.fetch(f"/coverage.geojson?v={derivate}").body)

    def test_replaced_version_is_404(self):
        old = coverage_store.publish("gold", self.geojson)
        coverage_store.publish("gold", self.geojson.replace("[]", "[null]"))

        self.assertEqual(self.fetch(f"/coverage.geojson?v={old}").code, 404)

    def test_gzipped_when_the_client_accepts_it(self):
        version = coverage_store.publish("gold", self.geojson)

        response = self.fetch(
            f"/coverage.geojson?v={version}",
            decompress_response=False,
            headers={"Accept-Encoding": "gzip, deflate"},
        )

        self.assertEqual(response.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", response.headers["Vary"])
        self.assertEqual(gzip.decompress(response.body), self.geojson.encode())

    def test_matching_if_none_match_gets_304(self):
        version = coverage_store.publish("gold", self.geojson)

        response = self.fetch(
            f"/coverage.geojson?v={version}", headers={"If-None-Match": f'W/"{version}"'}
        )

        self.assertEqual(response.code, 304)
        self.assertEqual(response.body, b"")

    def test_stale_etag_gets_the_body(self):
        version = coverage_store.publish("gold", self.geojson)

        response = self.fetch(f"/coverage.geojson?v={version}", headers={"If-None-Match": '"old"'})

        self.assertEqual(response.code, 200)
        self.assertEqual(response.body, self.geojson.encode())

    def test_allowed_origin_can_read_it(self):
        version = coverage_store.publish("gold", self.geojson)

        response = self.fetch(f"/coverage.geojson?v={version}", headers={"Origin": LOCAL_ORIGIN})

        self.assertEqual(response.headers["Access-Control-Allow-Origin"], LOCAL_ORIGIN)

    def test_other_geojson_paths_still_get_404_without_s3_call(self):
        coverage_store.publish("gold", self.geojson)

        for path in ("/other.geojson", "/coverage.geojsonx", "/sub/coverage.geojson"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path).code, 404)
        self.s3.get_object.assert_not_called()


class PrefetchRouteTest(_ProxyTestCase):
    """POST /prefetch hands the id to anriss_prefetch -- only for the app itself."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pmtiles_server.anriss_prefetch, "request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, query, headers):
        return self.fetch(f"/prefetch?{query}", method="POST", body=b"", headers=headers)

    def test_allowed_origin_starts_the_prefetch(self):
        response = self._post("id_anriss=5874283", {"Origin": LOCAL_ORIGIN})
        self.assertEqual(response.code, 202)
        self.request.assert_called_once_with(5874283)

    def test_same_origin_behind_a_proxy_is_accepted(self):
        # deployed: the sidecar sits behind a path prefix of the app's own host
        response = self._post(
            "id_anriss=7",
            {"Origin": "https://pgr-atlas.example.ch", "X-Forwarded-Host": "pgr-atlas.example.ch"},
        )
        self.assertEqual(response.code, 202)

    def test_foreign_or_missing_origin_is_refused(self):
        for headers in ({"Origin": "https://evil.example"}, {}):
            self.assertEqual(self._post("id_anriss=7", headers).code, 403)
        self.request.assert_not_called()

    def test_bad_id_is_refused(self):
        for query in ("", "id_anriss=abc", "id_anriss=-3", "id_anriss=0"):
            self.assertEqual(self._post(query, {"Origin": LOCAL_ORIGIN}).code, 400)
        self.request.assert_not_called()


class IfkPrefetchRouteTest(_ProxyTestCase):
    """POST /prefetch-ifk hands a pixel to ifk_prefetch -- only real pixel
    centers in Switzerland, only for the app itself."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pmtiles_server.ifk_prefetch, "request")
        self.request = patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, query, headers=None):
        return self.fetch(
            f"/prefetch-ifk?{query}",
            method="POST",
            body=b"",
            headers={"Origin": LOCAL_ORIGIN} if headers is None else headers,
        )

    def test_pixel_center_starts_the_prefetch(self):
        response = self._post("x=2600002.5&y=1200007.5&client=3f2a-9c")
        self.assertEqual(response.code, 202)
        self.request.assert_called_once_with("3f2a-9c", 2600002.5, 1200007.5)

    def test_foreign_origin_is_refused(self):
        self.assertEqual(
            self._post("x=2600002.5&y=1200007.5&client=a", {"Origin": "https://evil.example"}).code,
            403,
        )
        self.request.assert_not_called()

    def test_bad_arguments_are_refused(self):
        for query in (
            "",
            "x=2600002.5&y=1200007.5",  # no client
            "x=abc&y=1200007.5&client=a",
            "x=2600000&y=1200007.5&client=a",  # not a pixel center
            "x=2.5&y=7.5&client=a",  # outside Switzerland
            "x=nan&y=1200007.5&client=a",
            "x=2600002.5&y=1200007.5&client=a%27%3B--",
        ):  # client not an id
            with self.subTest(query=query):
                self.assertEqual(self._post(query).code, 400)
        self.request.assert_not_called()
