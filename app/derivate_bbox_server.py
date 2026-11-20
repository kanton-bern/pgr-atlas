"""Tiny Tornado server that crops+colorizes a viewport-sized window directly
from the derivate lake's canton-wide mosaic COGs (Data-Lake-Derivate/<metric>/
_mosaic/[<key>=<value>/]canton.tif, built by the pipeline's
derivate/run_derivate.py --mosaic; paths via probe_core.derivate.derivate_lake),
on every pan/zoom -- the map layer of the Raster-Derivate view (see
raster_bbox_map's derivate_bbox_* docstring).

One mosaic per metric+partition. The colour style (scale/vmin/vmax/ramp)
comes in as query args from the app (views/raster_derivate.py's _style), so
the legend and the pixels share one source and this server doesn't need to
know which metric uses which scale. The band is addressed by its 1-based
index (single-band mosaics have no description).

Why server-side: browser-side GeoTIFF decoding (geotiff.js) is unreliable,
Web Mercator tiles (PMTiles) misalign against LV95's true 5m grid, and
per-kachel static images need a cap on how many render at a canton-wide
zoom. This crops and colorizes server-side, entirely in native LV95
(GDAL/rasterio), so there's no reprojection to misalign -- only the
response's 4 corner points ever get converted to WGS84, for MapLibre's
`image` source placement (the same zero-raster-reprojection approach
Raster-Karten uses). One dynamic image per view, so no viewport cap either.

Alignment discipline (the one thing that has to be exact): the requested
viewport bbox almost never lands on the COG's own pixel boundaries, so this
never crops to the raw requested bbox. It snaps outward to the nearest whole-
pixel window of the source COG first, reads THAT, and returns THAT window's
own true bounds (not the request) as the placement corners -- so whatever
comes back is pixel-exact against the source grid by construction, for an
adaptively-sized window. GDAL automatically reads from the COG's internal
overview levels when the requested output size is much smaller than the
window (zoomed out).

Single endpoint, one round trip: GET /bbox.png?... returns the colorized PNG
directly (Content-Type: image/png) with the placement corners in an
`X-Corners` response header (JSON [[lon,lat] x4], TL/TR/BR/BL, the
order MapLibre expects), so the
browser can read both in one fetch() and hand MapLibre a blob: URL + those
corners -- no base64 inflation, no second request.

Tornado, not a new library -- same reasoning as pmtiles_server.py (already a
Streamlit dependency, its async handlers suit a small proxy well). The
actual rasterio/GDAL work is synchronous and blocking, so it runs in a
thread executor per request, same pattern pmtiles_server.py uses for its
boto3 calls.

Concurrency: _mosaic_cache_lock only guards the cache dicts. Opening a mosaic
(S3 check, presign, rasterio.open) is serialised per (metric, partition) by
that key's own load lock, so a cold mosaic doesn't hold up requests for the
others. When an entry expires, the new one is swapped in first and the old
dataset is closed under its own ds_lock; readers check `closed` after taking
ds_lock and fetch the current entry again (_read_mosaic).

Raster-Karten jobs: GET /job/<id>/<var>.png|.f32|.tif serves one finished
job's overlay image, hover grid (little-endian float32, NaN = nodata) or
GeoTIFF, from the job registered in raster_jobs (same process). The id is a
capability URL: unknown, expired and unreadable jobs all get the same generic
404, and the id is never logged.

Raster-Derivate ZIPs: GET /download/<id>.zip streams a ZIP registered in
raster_jobs by views/raster_derivate.py (see _DownloadHandler and derivate_download).

Result files: GET /file/<id> streams one file registered in raster_jobs
(register_file), as a download: the Rohdaten of an area's IFK
(views/ifk_area.py). The same capability id and generic 404 as a job.

Canton files: GET /canton/<metric>.tif[?partition=...] passes one canton COG
(a derivate mosaic or a Gebäudeschatten mask) through from S3, with Range
support so the browser can resume it (see _CantonFileHandler).

Error bodies stay generic ("bad request", "not found"); the details go to the
log. CORS headers only for the allowed origins (cors.py). /healthz answers
without S3.
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO

import numpy as np
import rasterio
import rasterio.windows
from rasterio.coords import BoundingBox
from PIL import Image
from pyproj import Transformer
from rasterio.enums import Resampling

import tornado.ioloop
import tornado.web
from tornado import gen, iostream

import derivate_download
import raster_export
import raster_jobs
import raster_overlay
import ui_text
from cors import set_cors_headers
from probe_core.s3 import s3_key_exists, s3_presigned_url
from probe_core.data_lake.data_interface import S3_BUCKET_GOLD
from probe_core import gebaeudeschatten
from probe_core.derivate import derivate_lake
from raster_utils import MASK_COLORS, RAMPS, SCALES, _colorize_band, colorize_mask

S3_BUCKET = S3_BUCKET_GOLD

# Presigned URLs default to 24h (s3_presigned_url); re-open well before that.
# Also bounds how long a rebuilt mosaic (e.g. after a --force rerun that
# added threshold bands, which shifts band indices) keeps being served from
# the old open dataset -- same order as views/raster_derivate.py's 300s band-stats cache.
_MOSAIC_CACHE_TTL_S = 600

# Safety clamp on the requested output size -- this server only ever serves
# this app's own map component, not the public internet, but a stray huge
# request (e.g. a bogus width/height) shouldn't be allowed to force a huge
# GDAL read/PNG encode.
_MAX_OUTPUT_PX = 2048

# Job files never change; the id expires after raster_jobs.JOB_TTL_S anyway.
_JOB_CACHE_CONTROL = f"private, max-age={raster_jobs.JOB_TTL_S}"
_ATTACHMENT_CHUNK_SIZE = 1 << 16  # 64 KiB per streamed chunk
_URL_QUERY = re.compile(r"(https?://[^\s?'\"]+)\?[^\s'\"]*")

# ZIP streams at once. Each one keeps up to derivate_download.PREFETCH files in
# the work folder (a crop can be hundreds of MB), which on the stages is an
# emptyDir the pod is evicted for filling (sizeLimit 5Gi).
_MAX_ZIP_STREAMS = 2
# A ZIP or canton-file client that takes no data for this long is dropped, so
# its temp files and slot are freed (the ingress itself allows a day).
_CLIENT_STALL_TIMEOUT_S = 120
# Chunk reads and cleanup of the ZIP streams, apart from the executor that
# /bbox.png and /value.json use: a cleanup waits for running crops.
_zip_executor = ThreadPoolExecutor(max_workers=2 * _MAX_ZIP_STREAMS, thread_name_prefix="zip-io")
_active_zip_streams = 0

# Canton files passed through at once (/canton). They need no disk, only a
# chunk of memory and a thread each; the cap bounds the threads.
_MAX_CANTON_STREAMS = 4
_canton_executor = ThreadPoolExecutor(
    max_workers=_MAX_CANTON_STREAMS, thread_name_prefix="canton-io"
)
_active_canton_streams = 0
# A partition value as the lakes name them: variable, combo or GS mask settings.
_PARTITION = re.compile(r"[a-z0-9_]+")
# One range, as a resuming browser sends it: "bytes=<start>-[<end>]" or "bytes=-<suffix>".
_RANGE = re.compile(r"bytes=(\d+-\d*|-\d+)")

_WGS84_TO_LV95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
_LV95_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)

# Presigned-GET-only against this bucket.
_VSICURL_ENV = derivate_lake.VSICURL_ENV

logger = logging.getLogger(__name__)

# (metric, partition) -> {'url', 'ds', 'ds_lock', 'fetched_at', 'closed'}
_mosaic_cache = {}
# (metric, partition) -> lock held while that mosaic is being opened
_load_locks = {}
_mosaic_cache_lock = threading.Lock()  # guards both dicts, never held during I/O


class _BadRequest(Exception):
    pass


class _NotFound(Exception):
    pass


def _fresh_entry(key):
    """The cached entry for key if it hasn't expired. Caller holds _mosaic_cache_lock."""
    cached = _mosaic_cache.get(key)
    if cached and time.monotonic() - cached["fetched_at"] < _MOSAIC_CACHE_TTL_S:
        return cached
    return None


GEBAEUDESCHATTEN_METRIC = derivate_download.GEBAEUDESCHATTEN_METRIC


def _cog_key(metric, partition):
    """S3 key of the canton COG behind (metric, partition). Raises _BadRequest
    for an unknown metric or a partition that doesn't fit it."""
    try:
        if metric == GEBAEUDESCHATTEN_METRIC:
            variant, reach, min_depth = (partition or "").rsplit("_", 2)
            return gebaeudeschatten.affected_mask_key(int(reach), variant, int(min_depth))
        if metric not in derivate_lake.PARTITION_KEYS:
            raise ValueError(f"unknown metric {metric!r}")
        return derivate_lake.mosaic_key(metric, partition)
    except ValueError as error:
        raise _BadRequest(str(error)) from error


def _open_mosaic(metric, partition):
    """Opens one (metric, partition)'s canton mosaic COG as a new cache entry.
    Raises _NotFound if no mosaic exists yet, _BadRequest on a partition mismatch."""
    cog_key = _cog_key(metric, partition)
    if not s3_key_exists(S3_BUCKET, cog_key):
        raise _NotFound(
            f"No canton mosaic for {metric} {partition or ''} yet "
            f"-- run derivate/run_derivate.py --mosaic"
        )
    url = s3_presigned_url(S3_BUCKET, cog_key)
    with rasterio.Env(**_VSICURL_ENV):
        dataset = rasterio.open(f"/vsicurl/{url}")
    return {
        "url": url,
        "ds": dataset,
        "ds_lock": threading.Lock(),
        "fetched_at": time.monotonic(),
        "closed": False,
    }


def _close_entry(entry):
    """Closes a replaced entry's dataset once no reader holds its ds_lock."""
    with entry["ds_lock"]:
        entry["closed"] = True
        try:
            entry["ds"].close()
        except Exception:  # a failed close of a replaced dataset must not fail the request
            logger.warning(
                "Closing the expired mosaic dataset %s failed",
                entry["url"].split("?")[0],
                exc_info=True,
            )


def _get_mosaic_context(metric, partition):
    """Presigned URL + a live, already-OPEN rasterio dataset for one
    (metric, partition)'s canton mosaic COG, cached across requests. Keeping
    the dataset open matters, not just the URL: a fresh rasterio.open(
    "/vsicurl/...") re-parses the whole COG directory (IFD + every overview
    level) over the network on every call -- measured ~7-8s per request on an
    18-band/1.6GB mosaic when this cache only held the URL, which would make
    every pan/zoom feel broken. `dataset` is NOT thread-safe for concurrent reads
    (GDAL datasets aren't), so read it through _read_mosaic, which holds
    `ds_lock` and handles an entry closed by expiry. Raises _NotFound if no
    mosaic exists for (metric, partition) yet, _BadRequest for an unknown
    metric / partition mismatch."""
    _cog_key(metric, partition)  # rejects unknown metrics before anything is cached
    key = (metric, partition)
    with _mosaic_cache_lock:
        cached = _fresh_entry(key)
        if cached:
            return cached
        load_lock = _load_locks.setdefault(key, threading.Lock())

    with load_lock:
        with _mosaic_cache_lock:
            cached = _fresh_entry(key)  # another request may have opened it meanwhile
        if cached:
            return cached
        entry = _open_mosaic(metric, partition)
        with _mosaic_cache_lock:
            old = _mosaic_cache.get(key)
            _mosaic_cache[key] = entry
    if old is not None:
        _close_entry(old)
    return entry


def _read_mosaic(metric, partition, read):
    """Calls read(dataset) on the mosaic's open dataset while holding its ds_lock.
    If the entry was closed by an expiry between the lookup and the lock, the
    current entry is fetched once more."""
    for _ in range(2):
        entry = _get_mosaic_context(metric, partition)
        with entry["ds_lock"]:
            if not entry["closed"]:
                with rasterio.Env(**_VSICURL_ENV):
                    return read(entry["ds"])
    raise RuntimeError(f"mosaic {metric} {partition} was replaced twice during one read")


def _corners_lonlat(bounds):
    """LV95 bounds -> TL, TR, BR, BL in WGS84 (row 0 = north edge)."""
    corners_lv95 = [
        (bounds.left, bounds.top),
        (bounds.right, bounds.top),
        (bounds.right, bounds.bottom),
        (bounds.left, bounds.bottom),
    ]
    return [list(_LV95_TO_WGS84.transform(east, north)) for east, north in corners_lv95]


def _snapped_window(dataset, west, south, east, north):
    """Requested WGS84 viewport -> a whole-pixel window of `dataset`, snapped
    OUTWARD (floor/ceil) so it always fully covers the request, then clipped
    to the dataset's own extent (derivate_lake.snapped_window). This is the
    alignment guarantee: whatever window comes back is exactly on the source
    COG's native pixel grid, so reading it and reporting back its OWN true
    bounds (see rasterio.windows.bounds at the call site) is pixel-exact by
    construction -- never the raw, off-grid request bbox. A viewport that
    doesn't overlap the mosaic at all gives a zero-size window, which the
    caller turns into a clean 404."""
    corners = [(west, south), (east, south), (east, north), (west, north)]
    xs, ys = zip(*(_WGS84_TO_LV95.transform(lon, lat) for lon, lat in corners))
    return derivate_lake.snapped_window(dataset, min(xs), min(ys), max(xs), max(ys))


def _as_float_with_nan(dataset, band_values):
    """Band values as float32 with the dataset's nodata turned into NaN (the
    uint8 affected_mask uses 255, the float metrics NaN already)."""
    values = band_values.astype(np.float32, copy=False)
    if dataset.nodata is not None and not np.isnan(dataset.nodata):
        values[values == dataset.nodata] = np.nan
    return values


def _check_band(dataset, band):
    if not 1 <= band <= dataset.count:
        raise _BadRequest(f"band {band} out of range 1..{dataset.count}")


def _render(
    metric,
    partition,
    band,
    scale,
    vmin,
    vmax,
    ramp,
    west,
    south,
    east,
    north,
    out_w,
    out_h,
    mask_color="orange",
):
    """The blocking half -- runs in a thread executor. Returns (png_bytes,
    corners), None if the viewport doesn't overlap the mosaic, or raises
    _BadRequest/_NotFound."""

    def read(dataset):
        _check_band(dataset, band)
        window = _snapped_window(dataset, west, south, east, north)
        if window.width <= 0 or window.height <= 0:
            return None
        # Scale the read shape from the snapped window towards the
        # requested output size, but never upscale past the window's own
        # native resolution -- GDAL picks the matching overview level
        # automatically when out_shape is smaller than the window.
        read_w = min(out_w, window.width) or 1
        read_h = min(out_h, window.height) or 1
        band_values = dataset.read(
            band, window=window, out_shape=(read_h, read_w), resampling=Resampling.nearest
        )
        return _as_float_with_nan(dataset, band_values), rasterio.windows.bounds(
            window, dataset.transform
        )

    # Reuse the cached, already-open dataset (see _get_mosaic_context) --
    # opening fresh per request re-parses the whole COG directory over the
    # network every time.
    result = _read_mosaic(metric, partition, read)
    if result is None:
        return None
    band_values, true_bounds = result
    rgba = (
        colorize_mask(band_values, MASK_COLORS[mask_color])
        if scale == "mask"
        else _colorize_band(band_values, vmin, vmax, scale, ramp)
    )
    png = BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(png, format="PNG")
    return png.getvalue(), _corners_lonlat(BoundingBox(*true_bounds))


def _point_value(metric, partition, band, e, n):
    """The blocking half for /value.json -- single-pixel read from the same
    cached, already-open dataset _render uses. Returns the band's value at
    LV95 (e, n), or None if that point falls outside the mosaic's extent or
    on a nodata cell."""

    def read(dataset):
        _check_band(dataset, band)
        row, col = dataset.index(e, n)
        if not (0 <= row < dataset.height and 0 <= col < dataset.width):
            return None
        pixel = dataset.read(band, window=rasterio.windows.Window(col, row, 1, 1))
        return _as_float_with_nan(dataset, pixel)

    pixel = _read_mosaic(metric, partition, read)
    if pixel is None:
        return None
    value = float(pixel[0, 0])
    return value if np.isfinite(value) else None


def _mosaic_args(handler):
    """(metric, partition, band) from the query -- partition '' / absent =
    unpartitioned metric. Raises ValueError for a partition no lake names:
    it becomes part of an S3 key and of the mosaic cache's key."""
    metric = handler.get_query_argument("metric")
    partition = handler.get_query_argument("partition", "") or None
    if partition is not None and not _PARTITION.fullmatch(partition):
        raise ValueError(f"bad partition {partition!r}")
    band = int(handler.get_query_argument("band"))
    return metric, partition, band


_ERROR_BODIES = {
    400: "bad request",
    404: "not found",
    416: "range not satisfiable",
    502: "upstream error",
}


def _error_body(status_code: int) -> str:
    """The plain-text body of an error response; a 503 tells the user to retry."""
    if status_code == 503:
        return ui_text.t("server.zip_busy")
    return _ERROR_BODIES.get(status_code, "server error")


class _MosaicHandler(tornado.web.RequestHandler):
    """Shared by /bbox.png and /value.json: CORS, preflight, and the mapping
    of _BadRequest/_NotFound to generic 400/404 bodies (details to the log)."""

    expose_headers = ""

    def set_default_headers(self):
        set_cors_headers(self, self.expose_headers)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.finish(_error_body(status_code))

    async def _run(self, blocking_call):
        """Parses the query, runs blocking_call(*args) in the executor and
        returns its result. Raises HTTPError 400/404 for _BadRequest/_NotFound,
        after logging the detail."""
        loop = tornado.ioloop.IOLoop.current()
        try:
            args = self._query_args()
            return await loop.run_in_executor(None, lambda: blocking_call(*args))
        except _BadRequest as error:
            logger.warning("Bad request %s: %s", self.request.uri, error)
            raise tornado.web.HTTPError(400) from error
        except _NotFound as error:
            logger.warning("Not found %s: %s", self.request.uri, error)
            raise tornado.web.HTTPError(404) from error


class _ValueHandler(_MosaicHandler):
    """GET /value.json?metric=...&partition=...&band=...&e=...&n=... -- the
    click-to-read-a-pixel counterpart to /bbox.png, for the Raster-Derivate
    view's live map layer (frontend/src/raster_bbox_map/derivate.ts's showValueAt).
    A separate point query rather than shipping a full per-pixel grid
    alongside every /bbox.png crop: that crop is refetched on every pan/zoom,
    so attaching raw float data to it would multiply the traffic of a view
    that's already a live tile feed; a single-pixel read off the cached,
    already-open dataset is cheap enough to do per click instead."""

    def _query_args(self):
        try:
            return (
                *_mosaic_args(self),
                float(self.get_query_argument("e")),
                float(self.get_query_argument("n")),
            )
        except (tornado.web.MissingArgumentError, ValueError) as error:
            raise _BadRequest(str(error)) from error

    async def get(self):
        value = await self._run(_point_value)
        if value is None:  # outside the mosaic or a nodata cell
            raise tornado.web.HTTPError(404)
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"value": value}))


class _BboxHandler(_MosaicHandler):
    """GET /bbox.png?metric=...&partition=...&band=...&scale=...&vmin=...&vmax=...&ramp=...
    &west=...&south=...&east=...&north=...&width=...&height=...[&mask_color=orange|purple]"""

    expose_headers = "X-Corners"

    def _query_args(self):
        try:
            metric, partition, band = _mosaic_args(self)
            scale = self.get_query_argument("scale")
            ramp = self.get_query_argument("ramp", "viridis")
            vmin = float(self.get_query_argument("vmin", "0"))
            vmax = float(self.get_query_argument("vmax", "1"))
            west = float(self.get_query_argument("west"))
            south = float(self.get_query_argument("south"))
            east = float(self.get_query_argument("east"))
            north = float(self.get_query_argument("north"))
            out_w = min(max(1, int(float(self.get_query_argument("width")))), _MAX_OUTPUT_PX)
            out_h = min(max(1, int(float(self.get_query_argument("height")))), _MAX_OUTPUT_PX)
            mask_color = self.get_query_argument("mask_color", "orange")
        except (tornado.web.MissingArgumentError, ValueError) as error:
            raise _BadRequest(str(error)) from error
        if scale not in SCALES:
            raise _BadRequest(f"scale must be one of {SCALES}, got {scale!r}")
        if mask_color not in MASK_COLORS:
            raise _BadRequest(
                f"mask_color must be one of {sorted(MASK_COLORS)}, got {mask_color!r}"
            )
        if ramp not in RAMPS:
            raise _BadRequest(f"ramp must be one of {sorted(RAMPS)}, got {ramp!r}")
        if scale == "log" and not 0 < vmin < vmax:
            raise _BadRequest(f"log scale needs 0 < vmin < vmax, got {vmin}, {vmax}")
        return (
            metric,
            partition,
            band,
            scale,
            vmin,
            vmax,
            ramp,
            west,
            south,
            east,
            north,
            out_w,
            out_h,
            mask_color,
        )

    async def get(self):
        result = await self._run(_render)
        if result is None:  # the viewport doesn't overlap the mosaic
            raise tornado.web.HTTPError(404)
        png_bytes, corners = result
        self.set_header("Content-Type", "image/png")
        self.set_header("X-Corners", json.dumps(corners))
        self.write(png_bytes)


# Blocking (path, meta) -> bytes per rendered job file type, run in the executor.
_JOB_RENDERERS = {
    "png": ("image/png", lambda path, meta: raster_overlay.render_png(path, meta["mode"])),
    "f32": ("application/octet-stream", lambda path, meta: raster_overlay.hover_grid(path)),
}


class _JobFileHandler(tornado.web.RequestHandler):
    """GET /job/<id>/<var>.png|.f32|.tif -- one file of a finished
    Raster-Karten job (see raster_jobs). <var> only selects from the job's
    own paths, so it can't reach any other file."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.finish(_error_body(status_code))

    async def get(self, job_id, variable, extension):
        job = raster_jobs.get(job_id)
        path = job.paths.get(variable) if job is not None else None
        if path is None:
            raise tornado.web.HTTPError(404)
        loop = tornado.ioloop.IOLoop.current()
        try:
            if extension == "tif":
                tif_file = await loop.run_in_executor(None, open, path, "rb")
            else:
                content_type, render = _JOB_RENDERERS[extension]
                body = await loop.run_in_executor(None, render, path, job.meta)
        except OSError as error:  # the GeoTIFF is gone or unreadable (rasterio errors are OSErrors)
            logger.warning("Raster job file %s unreadable: %s", path, error)
            raise tornado.web.HTTPError(404) from error

        self.set_header("Cache-Control", _JOB_CACHE_CONTROL)
        if extension == "tif":
            await _stream_attachment(
                self, tif_file, raster_export.download_name(path), "image/tiff"
            )
        else:
            self.set_header("Content-Type", content_type)
            self.finish(body)


async def _stream_attachment(handler, open_file, filename: str, content_type: str):
    """Sends open_file as a download named filename, in chunks, and closes it."""
    loop = tornado.ioloop.IOLoop.current()
    handler.set_header("Content-Type", content_type)
    handler.set_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.set_header("Content-Length", str(os.fstat(open_file.fileno()).st_size))
    try:
        while chunk := await loop.run_in_executor(None, open_file.read, _ATTACHMENT_CHUNK_SIZE):
            handler.write(chunk)
            await handler.flush()
        handler.finish()
    except iostream.StreamClosedError:
        pass  # the browser cancelled the download
    finally:
        open_file.close()


class _FileHandler(tornado.web.RequestHandler):
    """GET /file/<id> -- one result file registered with
    raster_jobs.register_file (the Rohdaten of an area's IFK). The id only
    names a registered path, so it can't reach any other file."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.finish(_error_body(status_code))

    async def get(self, file_id):
        entry = raster_jobs.get_file(file_id)
        if entry is None:
            raise tornado.web.HTTPError(404)
        loop = tornado.ioloop.IOLoop.current()
        try:
            result_file = await loop.run_in_executor(None, open, entry.path, "rb")
        except OSError as error:  # the session that wrote it dropped its folder
            logger.warning("Result file %s unreadable: %s", entry.path, error)
            raise tornado.web.HTTPError(404) from error
        self.set_header("Cache-Control", _JOB_CACHE_CONTROL)
        await _stream_attachment(self, result_file, entry.download_name, entry.content_type)


def _without_url_queries(error: Exception) -> str:
    """The error text with every URL's query string cut off: a failed crop read
    names the presigned mosaic URL, signature included."""
    return _URL_QUERY.sub(r"\1?…", f"{type(error).__name__}: {error}")


class _ClientStalled(Exception):
    pass


class _DownloadHandler(tornado.web.RequestHandler):
    """GET /download/<id>.zip -- a Raster-Derivate ZIP registered with
    raster_jobs.register_download, streamed as it is written (see
    derivate_download). The length isn't known up front, so the response is
    chunked. An error before the first byte is a 502. After it, the connection is
    closed without the final chunk, so the browser reports a failed download
    instead of saving a cut-off ZIP. At most _MAX_ZIP_STREAMS run at once; one
    more gets a 503 with a German note, shown in the tab the link opened."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code, **kwargs):
        if status_code == 503:
            self.set_header("Retry-After", "60")
            self.set_header("Content-Type", "text/plain; charset=utf-8")
        self.finish(_error_body(status_code))

    async def get(self, download_id):
        global _active_zip_streams
        download = raster_jobs.get_download(download_id)
        if download is None:
            raise tornado.web.HTTPError(404)
        if _active_zip_streams >= _MAX_ZIP_STREAMS:
            logger.warning(
                "Derivate %s ZIP refused: %d streams running", download.kind, _active_zip_streams
            )
            raise tornado.web.HTTPError(503)
        _active_zip_streams += 1  # only the IOLoop thread counts, so no lock
        try:
            await self._serve(download)
        finally:
            _active_zip_streams -= 1

    async def _serve(self, download):
        self.set_header("Content-Type", "application/zip")
        self.set_header(
            "Content-Disposition",
            f'attachment; filename="{derivate_download.ZIP_NAMES[download.kind]}"',
        )
        self.set_header("Cache-Control", "no-store")
        loop = tornado.ioloop.IOLoop.current()
        files = derivate_download.Prefetcher(download)
        failed = written = False
        try:
            await self._stream_zip(files)
            written = True
        except iostream.StreamClosedError:
            pass  # the browser cancelled the download
        except Exception as error:  # S3, GDAL, disk or a stalled client: anything that stops it
            logger.error("Derivate %s ZIP failed: %s", download.kind, _without_url_queries(error))
            failed = True
        finally:
            await loop.run_in_executor(_zip_executor, files.close)
        # Only after the temp files are gone, so a finished download never
        # leaves any behind.
        if written:
            self.finish()
        if failed and not self._headers_written:
            raise tornado.web.HTTPError(502)
        if failed:
            self.request.connection.close()

    async def _stream_zip(self, files):
        loop = tornado.ioloop.IOLoop.current()
        sink = derivate_download.ZipSink()
        archive = zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED)
        while (future := files.next()) is not None:
            entry = await asyncio.wrap_future(future)
            if entry is None:
                continue
            try:
                with archive.open(entry.zip_info(), "w") as member:
                    while chunk := await loop.run_in_executor(
                        _zip_executor, entry.body.read, derivate_download.CHUNK_SIZE
                    ):
                        member.write(chunk)
                        await self._send(sink)
            finally:
                entry.close()
        archive.close()
        await self._send(sink)

    async def _send(self, sink):
        data = sink.drain()
        if not data:
            return
        self.write(data)
        try:
            await gen.with_timeout(
                timedelta(seconds=_CLIENT_STALL_TIMEOUT_S),
                self.flush(),
                quiet_exceptions=(iostream.StreamClosedError,),
            )
        except gen.TimeoutError:
            raise _ClientStalled(
                f"the client took no data for {_CLIENT_STALL_TIMEOUT_S} s"
            ) from None


def _s3_error_code(error: Exception) -> str | None:
    return getattr(error, "response", {}).get("Error", {}).get("Code")


class _CantonFileHandler(tornado.web.RequestHandler):
    """GET /canton/<metric>.tif[?partition=...] -- one canton COG from S3,
    passed through chunk by chunk. The browser can't reach the object storage
    on every stage (Bedag's own S3 is internal), so the app serves it. Only
    the keys _cog_key knows are reachable. A Range header goes to S3 as is,
    so an interrupted download resumes (206 + Content-Range): browsers resume
    only with a validator, so S3's ETag and Last-Modified are passed on, and
    an If-Range goes to S3 as IfMatch -- if the file changed since, the whole
    new file is sent (200), never a mix of old and new bytes. At most
    _MAX_CANTON_STREAMS run at once; one more gets a 503."""

    def set_default_headers(self):
        set_cors_headers(self)

    def options(self, *args, **kwargs):
        self.set_status(204)
        self.finish()

    def write_error(self, status_code, **kwargs):
        if status_code == 503:
            self.set_header("Retry-After", "60")
            self.set_header("Content-Type", "text/plain; charset=utf-8")
            self.finish(ui_text.t("server.canton_busy"))
            return
        self.finish(_error_body(status_code))

    async def get(self, metric):
        global _active_canton_streams
        partition = self.get_query_argument("partition", None)
        try:
            if partition is not None and not _PARTITION.fullmatch(partition):
                raise ValueError(f"bad partition {partition!r}")
            key = _cog_key(metric, partition)
            name = derivate_download.canton_file_name(metric, partition)
        except (_BadRequest, ValueError) as error:
            logger.info("Canton file refused: %s", error)
            raise tornado.web.HTTPError(400) from error
        byte_range = self.request.headers.get("Range")
        if byte_range is not None and not _RANGE.fullmatch(byte_range):
            raise tornado.web.HTTPError(416)
        if _active_canton_streams >= _MAX_CANTON_STREAMS:
            logger.warning("Canton file refused: %d streams running", _active_canton_streams)
            raise tornado.web.HTTPError(503)
        _active_canton_streams += 1  # only the IOLoop thread counts, so no lock
        try:
            await self._serve(key, name, byte_range, self.request.headers.get("If-Range"))
        finally:
            _active_canton_streams -= 1

    async def _serve(self, key, name, byte_range, if_range):
        s3_object = await self._open(key, byte_range, if_range)
        self._set_file_headers(s3_object, name)
        body = s3_object["Body"]
        loop = tornado.ioloop.IOLoop.current()
        try:
            while chunk := await loop.run_in_executor(
                _canton_executor, body.read, derivate_download.CHUNK_SIZE
            ):
                self.write(chunk)
                await gen.with_timeout(
                    timedelta(seconds=_CLIENT_STALL_TIMEOUT_S),
                    self.flush(),
                    quiet_exceptions=(iostream.StreamClosedError,),
                )
            self.finish()
        except iostream.StreamClosedError:
            pass  # the browser cancelled the download (it can resume it)
        except Exception as error:  # S3 or a stalled client: cut the response short
            logger.error("Canton file %s stopped: %s", key, _without_url_queries(error))
            self.request.connection.close()
        finally:
            body.close()

    async def _open(self, key, byte_range, if_range):
        """S3's get_object response for the request, or an HTTPError."""
        loop = tornado.ioloop.IOLoop.current()

        def get_object(**extra):
            return derivate_download.get_s3_client().get_object(Bucket=S3_BUCKET, Key=key, **extra)

        ranged = {"Range": byte_range} if byte_range else {}
        # If-Range carries an ETag (quoted) or a date; only an ETag can go to S3.
        if byte_range and if_range and if_range.startswith('"'):
            ranged["IfMatch"] = if_range
        try:
            try:
                return await loop.run_in_executor(_canton_executor, lambda: get_object(**ranged))
            except Exception as error:
                if _s3_error_code(error) not in ("PreconditionFailed", "412"):
                    raise
                # The file changed since the browser's first part: send all of it.
                return await loop.run_in_executor(_canton_executor, get_object)
        except Exception as error:
            code = _s3_error_code(error)
            if code in ("NoSuchKey", "404"):
                raise tornado.web.HTTPError(404) from error
            if code == "InvalidRange":
                raise tornado.web.HTTPError(416) from error
            logger.error("Canton file %s failed: %s", key, _without_url_queries(error))
            raise tornado.web.HTTPError(502) from error

    def _set_file_headers(self, s3_object, name):
        if s3_object.get("ContentRange"):
            self.set_status(206)
            self.set_header("Content-Range", s3_object["ContentRange"])
        self.set_header("Content-Type", "image/tiff")
        self.set_header("Content-Disposition", f'attachment; filename="{name}"')
        self.set_header("Content-Length", str(s3_object["ContentLength"]))
        self.set_header("Accept-Ranges", "bytes")
        self.set_header("Cache-Control", "no-store")
        for header, field in (("ETag", "ETag"), ("Last-Modified", "LastModified")):
            if s3_object.get(field):
                self.set_header(header, s3_object[field])


class _HealthHandler(tornado.web.RequestHandler):
    """/healthz: this server's IOLoop answers. No S3 call."""

    def get(self):
        self.finish("ok")


def make_app() -> tornado.web.Application:
    """Builds the crop server application."""
    return tornado.web.Application(
        [
            (r"/bbox\.png", _BboxHandler),
            (r"/value\.json", _ValueHandler),
            (r"/job/([A-Za-z0-9_-]+)/([a-z]+)\.(png|f32|tif)", _JobFileHandler),
            (r"/download/([A-Za-z0-9_-]+)\.zip", _DownloadHandler),
            (r"/file/([A-Za-z0-9_-]+)", _FileHandler),
            (r"/canton/([a-z_]+)\.tif", _CantonFileHandler),
            (r"/healthz", _HealthHandler),
        ]
    )


def _serve_forever(port, address):
    asyncio.set_event_loop(asyncio.new_event_loop())
    make_app().listen(port, address=address)
    tornado.ioloop.IOLoop.current().start()


def _serve_or_exit(port, address) -> None:
    """Runs the server for the life of the process. If its IOLoop stops or
    fails (a port already in use, for example), the whole process exits with
    1, so Kubernetes restarts the container instead of
    leaving it running with blank maps."""
    try:
        _serve_forever(port, address)
        logger.error("derivate_bbox_server on port %d stopped", port)
    except Exception:
        logger.exception("derivate_bbox_server on port %d failed", port)
    os._exit(1)


_start_lock = threading.Lock()
_started = False


def start(port, address="0.0.0.0"):
    """Starts the server in a daemon thread. Idempotent -- a second call is
    a no-op, not a second thread trying to bind the same port -- same
    contract as pmtiles_server.start(), see that function's docstring for
    why this changed from "caller's responsibility" (st.cache_resource-only
    broke under k8s multi-replica session affinity -- see run_app.py).
    address="127.0.0.1" for a deployment fronted by a reverse proxy that
    terminates the externally-reachable port and forwards internally."""
    global _started
    with _start_lock:
        if _started:
            return port
        threading.Thread(target=_serve_or_exit, args=(port, address), daemon=True).start()
        _started = True
    return port
