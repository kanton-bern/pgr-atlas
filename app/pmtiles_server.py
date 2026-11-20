"""Tiny Tornado server that streams the overview PMTiles file straight from
S3 (the app's bucket, PROBE_S3_BUCKET; same private Hosttech object storage the data lake uses)
instead of local disk, forwarding HTTP Range headers through to S3's own
native Range support on GetObject.

Needed because Streamlit's own static handler for custom components
(component_request_handler.py in the streamlit package) reads and returns
the WHOLE file on every request, regardless of any Range header — see
ComponentRequestHandler.get(): `contents = file.read(); self.write(contents)`.
That's fine for small JS/CSS assets, but PMTiles is fundamentally built on
HTTP range requests (header, then root directory, then individual tile
chunks, each at a different byte offset) to avoid ever downloading the whole
(700MB+) archive. Since Streamlit's handler always returns bytes starting at
0 no matter what range was asked for, every pmtiles.js request past the
first (which happens to start at byte 0) silently gets the wrong bytes back
— tiles never render, nothing errors loudly.

Tornado's own async handlers can forward Range requests natively to S3, and
Tornado is already a Streamlit dependency — so this exposes a small proxy on
a separate port with CORS enabled (for the allowed origins only, see cors.py),
rather than introducing a new library.

Only root-level `*.pmtiles` keys are proxied (_TILESET_KEY); any other path is
a 404 without an S3 call, so the proxy can't be used to read the rest of the
bucket. /healthz answers without S3; /readyz also checks the URLs passed to
start() (the other servers of the process). Neither says whether S3 works:
that is checked once a minute in the background, and /readyz-s3 and /metrics
report the last result (docs/monitoring.md). /coverage.geojson?v=<version>
serves a coverage the app published to coverage_store, also without S3.
POST /prefetch?id_anriss=N starts reading one anriss's data in the background
while its map popup is open (see anriss_prefetch.py); it answers at once.
POST /prefetch-ifk?x=..&y=..&client=.. does the same for one IFK pixel
(ifk_prefetch.py).
The bucket is private (same credentials as the rest of the data lake, see
probe_core.s3's S3_CONFIG/get_s3_client), so the browser
can't be pointed at S3 directly — bytes still have to pass through this
process, just sourced from S3 GetObject instead of a local file.
"""

import asyncio
import logging
import math
import os
import re
import time
from urllib.parse import urlsplit
import threading

import tornado.httpclient
import tornado.ioloop
import tornado.web
from tornado import iostream
from botocore.exceptions import BotoCoreError, ClientError

import anriss_prefetch
import ifk_prefetch
import coverage_store
from cors import allowed_origins, set_cors_headers

# Same S3 client setup as the rest of the app (probe-core), rather than
# duplicating boto3 configuration here.
from probe_core.data_lake.data_interface import S3_BUCKET_GOLD
from probe_core.s3 import get_s3_client

# Tilesets live at the root of the app's one bucket (PROBE_S3_BUCKET, a peer
# of Data-Lake-*), not under any data-lake prefix.
S3_BUCKET = S3_BUCKET_GOLD

_CHUNK_SIZE = 1 << 16  # 64 KiB per streamed chunk

# The tilesets sit at the bucket root; no "/" means no other prefix is reachable.
_TILESET_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.pmtiles")

# Tilesets are rebuilt by hand and rarely; the ETag lets pmtiles.js notice a
# rebuilt archive within the hour.
_CACHE_CONTROL = "public, max-age=3600"

# The coverage URL carries its version (?v=), so a given URL never changes.
_COVERAGE_CACHE_CONTROL = "public, max-age=31536000, immutable"

_READY_TIMEOUT_S = 2.0

# The S3 check. boto3 retries an unreachable endpoint for minutes, so an answer
# that takes longer than the timeout counts as "not reachable" already.
_S3_CHECK_INTERVAL_S = 60.0
_S3_CHECK_TIMEOUT_S = 15.0

logger = logging.getLogger(__name__)


class _S3RangeProxyHandler(tornado.web.RequestHandler):
    """Streams a single tileset from S3, forwarding the client's Range header
    to S3's GetObject and mirroring back whatever status/headers S3 replies
    with (206 + Content-Range for a range read, 200 + Content-Length for a
    full read). Error bodies stay generic; the details go to the log."""

    def set_default_headers(self):
        # pmtiles.js reads the ETag to notice a rebuilt archive.
        set_cors_headers(self, "Content-Range, Content-Length, Accept-Ranges, ETag")

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    async def get(self, key):
        if not _TILESET_KEY.fullmatch(key):
            self.set_status(404)
            self.finish("not found")
            return

        get_object_args = {"Bucket": S3_BUCKET, "Key": key}
        range_header = self.request.headers.get("Range")
        if range_header:
            get_object_args["Range"] = range_header

        loop = tornado.ioloop.IOLoop.current()
        try:
            s3_object = await loop.run_in_executor(
                None, lambda: get_s3_client().get_object(**get_object_args)
            )
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 502)
            logger.warning("S3 GetObject failed for key %r: %s", key, error)
            if status == 404:
                self.set_status(404)
                self.finish("not found")
            else:
                self.set_status(502)
                self.finish("upstream error")
            return

        self.set_header("Accept-Ranges", "bytes")
        self.set_header("Content-Type", "application/octet-stream")
        self.set_header("Content-Length", str(s3_object["ContentLength"]))
        self.set_header("Cache-Control", _CACHE_CONTROL)
        if "ETag" in s3_object:
            self.set_header("ETag", s3_object["ETag"])
        if "LastModified" in s3_object:
            self.set_header("Last-Modified", s3_object["LastModified"])
        if "ContentRange" in s3_object:
            self.set_status(206)
            self.set_header("Content-Range", s3_object["ContentRange"])

        body = s3_object["Body"]
        try:
            while True:
                chunk = await loop.run_in_executor(None, body.read, _CHUNK_SIZE)
                if not chunk:
                    break
                self.write(chunk)
                await self.flush()
        except iostream.StreamClosedError:
            # Client (pmtiles.js) aborted an in-flight range request -- e.g.
            # a rapid pan/zoom superseding an older tile fetch. Normal and
            # frequent, not an error: swallow it here so Tornado's default
            # handler doesn't also try (and fail) to write an error response
            # onto an already-closed/half-written stream.
            pass
        finally:
            body.close()


class _CoverageHandler(tornado.web.RequestHandler):
    """/coverage.geojson?v=<version>: the coverage published to coverage_store
    with that version, gzipped when the client accepts it. The ETag is the
    version. A version no coverage holds (never published, or replaced since)
    is a 404."""

    def set_default_headers(self):
        set_cors_headers(self)

    def get(self):
        coverage = coverage_store.get(self.get_query_argument("v", ""))
        if coverage is None:
            self.set_status(404)
            self.finish("unknown coverage version")
            return
        self.set_header("ETag", f'W/"{coverage.version}"')
        self.set_header("Vary", "Origin, Accept-Encoding")
        self.set_header("Cache-Control", _COVERAGE_CACHE_CONTROL)
        if self.check_etag_header():
            self.set_status(304)
            self.finish()
            return
        self.set_header("Content-Type", "application/geo+json")
        if "gzip" in self.request.headers.get("Accept-Encoding", ""):
            self.set_header("Content-Encoding", "gzip")
            self.finish(coverage.gzipped)
        else:
            self.finish(coverage.body)


def _is_app_origin(request) -> bool:
    """True if the request's Origin is the app itself: the host it was sent to
    (X-Forwarded-Host behind a proxy), or one of cors.allowed_origins()."""
    origin = request.headers.get("Origin")
    if not origin:
        return False
    if origin.rstrip("/") in allowed_origins():
        return True
    host = request.headers.get("X-Forwarded-Host") or request.host
    return urlsplit(origin).netloc == host.split(",")[0].strip()


class _PrefetchHandler(tornado.web.RequestHandler):
    """POST /prefetch?id_anriss=N: hand the id to anriss_prefetch and answer
    202 at once -- the reads run in its thread pool, not in this server's
    event loop. The response has no body; the map doesn't wait for it."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def post(self):
        # A cross-origin POST without custom headers needs no preflight, so
        # CORS alone wouldn't stop another site from triggering S3 reads here:
        # only the app itself may -- same origin (deployed: the sidecar sits
        # behind a path prefix of the app's host, and browsers send Origin on
        # every POST) or an allowed origin (local port mode).
        if not _is_app_origin(self.request):
            self.set_status(403)
            self.finish("forbidden")
            return
        try:
            id_anriss = int(self.get_query_argument("id_anriss"))
        except (tornado.web.MissingArgumentError, ValueError):
            self.set_status(400)
            self.finish("bad request")
            return
        if id_anriss <= 0:
            self.set_status(400)
            self.finish("bad request")
            return
        anriss_prefetch.request(id_anriss)
        self.set_status(202)
        self.finish()


# A map instance's own random id (the IFK map makes a UUID per iframe).
_CLIENT_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
# Same padded Switzerland extent as frontend/src/shared/lv95.ts's BOUNDS.
_LV95_BOUNDS = (2460000.0, 1050000.0, 2860000.0, 1320000.0)


def _is_gold_pixel_center(v: float) -> bool:
    """On the 5 m lattice gold pixels are centered on (k*5 + 2.5)."""
    return (v - 2.5) % 5 == 0


class _IfkPrefetchHandler(tornado.web.RequestHandler):
    """POST /prefetch-ifk?x=..&y=..&client=..: hand the pixel to ifk_prefetch
    and answer 202 at once, like _PrefetchHandler. Only pixel centers inside
    Switzerland are accepted, so nothing but real pixels gets computed."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def post(self):
        if not _is_app_origin(self.request):
            self.set_status(403)
            self.finish("forbidden")
            return
        try:
            x = float(self.get_query_argument("x"))
            y = float(self.get_query_argument("y"))
            client = self.get_query_argument("client")
        except (tornado.web.MissingArgumentError, ValueError):
            self.set_status(400)
            self.finish("bad request")
            return
        xmin, ymin, xmax, ymax = _LV95_BOUNDS
        if not (
            _CLIENT_ID.fullmatch(client)
            and math.isfinite(x)
            and math.isfinite(y)
            and xmin <= x <= xmax
            and ymin <= y <= ymax
            and _is_gold_pixel_center(x)
            and _is_gold_pixel_center(y)
        ):
            self.set_status(400)
            self.finish("bad request")
            return
        ifk_prefetch.request(client, x, y)
        self.set_status(202)
        self.finish()


class _HealthHandler(tornado.web.RequestHandler):
    """/healthz: this server's IOLoop answers. No S3 call."""

    def get(self):
        self.finish("ok")


class _ReadyHandler(tornado.web.RequestHandler):
    """/readyz: this server answers and every URL in ready_urls returns 200."""

    def initialize(self, ready_urls):
        self.ready_urls = ready_urls

    async def get(self):
        results = await asyncio.gather(*(_is_up(url) for url in self.ready_urls))
        if all(results):
            self.finish("ok")
        else:
            self.set_status(503)
            self.finish("not ready")


class _S3Status:
    """The last result of the S3 check: reachable is None until the first one
    is in, checked_at is the Unix time of the last one."""

    reachable: bool | None = None
    checked_at: float | None = None


_s3_status = _S3Status()


def _s3_error() -> str | None:
    """Asks S3 for the app's bucket with the app's credentials. None when it
    answers, else the error: endpoint unreachable, key refused, bucket gone."""
    try:
        get_s3_client().head_bucket(Bucket=S3_BUCKET)
    except (ClientError, BotoCoreError) as e:
        return str(e)
    return None


async def _check_s3(pending: asyncio.Future | None) -> asyncio.Future | None:
    """One round of the S3 check, recorded in _s3_status. A request still
    unanswered after the timeout counts as not reachable; it is returned, and
    the next round waits for it instead of starting another one."""
    if pending is None:
        pending = asyncio.get_running_loop().run_in_executor(None, _s3_error)
    done, _ = await asyncio.wait({pending}, timeout=_S3_CHECK_TIMEOUT_S)
    error = pending.result() if done else f"no answer within {_S3_CHECK_TIMEOUT_S:.0f} s"
    reachable = error is None
    # Logged when the state changes, not every minute of an outage.
    if reachable != _s3_status.reachable:
        if reachable:
            logger.info("S3 check: bucket reachable")
        else:
            logger.error("S3 check: bucket not reachable: %s", error)
    _s3_status.reachable = reachable
    _s3_status.checked_at = time.time()
    return None if done else pending


async def _watch_s3() -> None:
    """Checks S3 for the life of the server, once per interval."""
    pending = None
    while True:
        pending = await _check_s3(pending)
        await asyncio.sleep(_S3_CHECK_INTERVAL_S)


class _S3ReadyHandler(tornado.web.RequestHandler):
    """/readyz-s3: did the last S3 check reach the bucket? No S3 call per
    request. Not for a Kubernetes probe: a short S3 outage would take every
    pod out of service at once, or restart them all."""

    def get(self):
        if _s3_status.reachable:
            self.finish("ok")
        else:
            self.set_status(503)
            self.finish(
                "s3 not checked yet" if _s3_status.reachable is None else "s3 not reachable"
            )


class _MetricsHandler(tornado.web.RequestHandler):
    """/metrics: the S3 check in Prometheus' text format, for the alert rule.
    Empty until the first check is in. Two fixed metrics, written by hand
    instead of adding a client library for them."""

    def get(self):
        self.set_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        if _s3_status.reachable is None:
            self.finish("")
            return
        self.finish(
            "# HELP pgr_atlas_s3_reachable 1 if the last S3 check reached the bucket, else 0.\n"
            "# TYPE pgr_atlas_s3_reachable gauge\n"
            f"pgr_atlas_s3_reachable {int(_s3_status.reachable)}\n"
            "# HELP pgr_atlas_s3_last_check_timestamp_seconds Unix time of the last S3 check.\n"
            "# TYPE pgr_atlas_s3_last_check_timestamp_seconds gauge\n"
            f"pgr_atlas_s3_last_check_timestamp_seconds {_s3_status.checked_at:.0f}\n"
        )


async def _is_up(url: str) -> bool:
    client = tornado.httpclient.AsyncHTTPClient()
    try:
        await client.fetch(url, request_timeout=_READY_TIMEOUT_S)
    except (tornado.httpclient.HTTPClientError, OSError) as e:  # non-2xx, timeout; refused
        logger.warning("Readiness check failed for %s: %s", url, e)
        return False
    return True


def make_app(ready_urls: tuple[str, ...] = ()) -> tornado.web.Application:
    """Builds the proxy application. The catch-all S3 route must stay last."""
    return tornado.web.Application(
        [
            (r"/healthz", _HealthHandler),
            (r"/coverage\.geojson", _CoverageHandler),
            (r"/prefetch", _PrefetchHandler),
            (r"/prefetch-ifk", _IfkPrefetchHandler),
            (r"/readyz", _ReadyHandler, {"ready_urls": ready_urls}),
            (r"/readyz-s3", _S3ReadyHandler),
            (r"/metrics", _MetricsHandler),
            (r"/(.*)", _S3RangeProxyHandler),
        ]
    )


def _serve_forever(port: int, address: str, ready_urls: tuple[str, ...]) -> None:
    asyncio.set_event_loop(asyncio.new_event_loop())
    make_app(ready_urls).listen(port, address=address)
    loop = tornado.ioloop.IOLoop.current()
    loop.spawn_callback(_watch_s3)
    loop.start()


def _serve_or_exit(port: int, address: str, ready_urls: tuple[str, ...]) -> None:
    """Runs the server for the life of the process. If its IOLoop stops or
    fails (a port already in use, for example), the whole process exits with
    1, so Kubernetes restarts the container instead of
    leaving it running with blank maps."""
    try:
        _serve_forever(port, address, ready_urls)
        logger.error("pmtiles_server on port %d stopped", port)
    except Exception:
        logger.exception("pmtiles_server on port %d failed", port)
    os._exit(1)


_start_lock = threading.Lock()
_started = False


def start(port: int, address: str = "0.0.0.0", ready_urls: tuple[str, ...] = ()) -> int:
    """Starts the server in a daemon thread. Idempotent — a second call
    (whether from a second Streamlit session rerun, or a second caller
    entirely, e.g. run_app.py's eager startup call racing app.py's own
    per-session st.cache_resource call in the same process) is a no-op, not
    a second thread trying to bind the same port. st.cache_resource alone
    is not enough under k8s multi-replica session affinity — see
    run_app.py's module docstring. Returns the port, for convenience at the call site.

    address="127.0.0.1" restricts it to localhost -- for a deployment
    fronted by a reverse proxy (e.g. an nginx in front of the container)
    that terminates the externally-reachable
    port itself and forwards to this one internally, so no separate
    firewall rule is needed for this port at all.

    ready_urls: the health URLs /readyz checks besides this server itself."""
    global _started
    with _start_lock:
        if _started:
            return port
        threading.Thread(
            target=_serve_or_exit, args=(port, address, tuple(ready_urls)), daemon=True
        ).start()
        _started = True
    return port
