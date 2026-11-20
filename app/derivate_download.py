"""Raster-Derivate ZIP downloads: the size estimate the view shows before a
ZIP is requested, and the files derivate_bbox_server.py streams into it.

A ZIP is never held in memory. views/raster_derivate.py registers what goes into it
(raster_jobs.register_download) and links to /download/<id>.zip; the sidecar
fetches the files a few ahead, in parallel, into temp files (Prefetcher) and
writes each one chunk by chunk into an uncompressed ZIP whose bytes go straight
to the response (ZipSink). A kachel is copied from S3 chunk by chunk, a crop is
written by crop_mosaic_to_selection; each temp file is deleted once it is in
the ZIP. Lives outside the view so it can be unit-tested without Streamlit.

There is no size cap. Measured in a container with an
8 GiB limit: a 1.2 GB kachel ZIP streamed with +18 MB RSS, two at once with
+32 MB. A crop ZIP's memory follows the selection's area and the PREFETCH crops
running at once, not the ZIP's size: all 13 datasets over 17 x 17 km (the
300-kachel limit) peaked at +1.3 GB for a 269 MB ZIP. The area is capped by
views/raster_derivate.py's _MAX_KACHELN and the streams by derivate_bbox_server.py's
_MAX_ZIP_STREAMS.
"""

import shutil
import tempfile
import time
import zipfile
from collections import deque
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import BinaryIO

from probe_core.data_lake.data_interface import S3_BUCKET_GOLD
from probe_core.derivate import derivate_lake
from probe_core.s3 import get_s3_client

import gebaeudeschatten_export
import ui_text
import work_dirs
from raster_jobs import Download

# The Gebäudeschatten view's affected masks: one canton COG per
# (variant, reach, minimum depth), addressed as metric=GEBAEUDESCHATTEN_METRIC and
# partition="<variant>_<reach_m>_<min_depth_cm>", e.g. "shadowing_building_100_10".
GEBAEUDESCHATTEN_METRIC = "gebaeudeschatten_affected_mask"
ZIP_NAMES = {"crop": "derivat_ausschnitt.zip", "kacheln": "derivat_kacheln.zip"}
CHUNK_SIZE = 1 << 20  # 1 MiB per read from S3 or a temp file
PREFETCH = 4  # files opened ahead: S3 GETs or crops, in parallel


def list_object_sizes(bucket: str, prefix: str) -> dict[str, int]:
    """Returns {key: size in bytes} for every object under prefix/, from the S3
    listing alone (no GET)."""
    sizes = {}
    for page in (
        get_s3_client()
        .get_paginator("list_objects_v2")
        .paginate(Bucket=bucket, Prefix=f"{prefix}/")
    ):
        sizes.update({obj["Key"]: obj["Size"] for obj in page.get("Contents", [])})
    return sizes


def canton_file_name(metric: str, partition: str | None) -> str:
    """Download name of a canton file served by derivate_bbox_server.py's
    /canton route: a derivate mosaic, e.g.
    derivat_trefferhaeufigkeit_fliesstiefe_kanton_bern.tif, or a
    Gebäudeschatten mask (partition '<variant>_<reach_m>_<min_depth_cm>'), e.g.
    gebaeudeschatten_maske_reichweite_50m_roh_ab_0_01m_kanton_bern.tif."""
    if metric == GEBAEUDESCHATTEN_METRIC:
        variant, reach, min_depth = partition.rsplit("_", 2)
        settings = gebaeudeschatten_export.settings_slug(int(reach), variant, int(min_depth))
        return f"gebaeudeschatten_maske_{settings}_kanton_bern.tif"
    return f"{ui_text.derivate_file_stem(metric, partition)}_kanton_bern.tif"


def estimate_zip_bytes(keys: list[str], sizes: dict[str, int]) -> int:
    """Size of a bundle from the S3 sizes of the kachel files it covers.

    Exact for the tiles bundle (the ZIP is uncompressed). An upper bound for the
    crop bundle: a crop holds the same DEFLATE data over the same or a smaller
    area; its kacheln measured 5-200 % larger than the crop. A key missing from the
    listing, e.g. written after it was cached, counts as the largest listed
    kachel of this bundle. The listing also holds the canton mosaic (up to
    ~365 MB), which must not stand in for a kachel.
    """
    listed = [sizes[key] for key in keys if key in sizes]
    fallback = max(listed, default=max(sizes.values(), default=0))
    return sum(listed) + (len(keys) - len(listed)) * fallback


@dataclass
class Entry:
    """One fetched file of a ZIP: a temp file, open for reading, deleted on close."""

    name: str
    path: Path
    body: BinaryIO

    @classmethod
    def of(cls, name: str, path: Path) -> "Entry":
        return cls(name, path, path.open("rb"))

    def zip_info(self) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(self.name, date_time=time.localtime()[:6])
        info.compress_type = zipfile.ZIP_STORED
        info.external_attr = 0o644 << 16
        info.file_size = self.path.stat().st_size  # zipfile picks ZIP64 headers from this
        return info

    def close(self) -> None:
        self.body.close()
        self.path.unlink(missing_ok=True)


class ZipSink:
    """The non-seekable file zipfile writes to. zipfile then puts each file's
    CRC and sizes in a data descriptor after its bytes, so nothing is ever
    rewritten. The handler takes the written bytes with drain()."""

    def __init__(self):
        self._chunks: list[bytes] = []

    def write(self, data) -> int:
        self._chunks.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


def _kachel_opener(index: int, name: str, key: str, temp_dir: Path) -> Callable[[], Entry]:
    def fetch_kachel():
        path = temp_dir / f"{index}.tif"
        body = get_s3_client().get_object(Bucket=S3_BUCKET_GOLD, Key=key)["Body"]
        try:
            with path.open("wb") as file:
                while chunk := body.read(CHUNK_SIZE):
                    file.write(chunk)
        finally:
            body.close()
        return Entry.of(name, path)

    return fetch_kachel


def _crop_opener(
    metric: str, partition: str | None, selection: dict, temp_dir: Path
) -> Callable[[], Entry | None]:
    def open_crop():
        path = temp_dir / f"{ui_text.derivate_file_stem(metric, partition)}_ausschnitt.tif"
        if not derivate_lake.crop_mosaic_to_selection(metric, partition, selection, str(path)):
            return None  # no mosaic, or it doesn't overlap the selection
        return Entry.of(path.name, path)

    return open_crop


def _openers(download: Download, temp_dir: Path) -> Iterator[Callable[[], Entry | None]]:
    if download.kind == "kacheln":
        return (
            _kachel_opener(index, name, key, temp_dir)
            for index, (name, key) in enumerate(download.items)
        )
    return (
        _crop_opener(metric, partition, download.selection, temp_dir)
        for metric, partition in download.items
    )


class Prefetcher:
    """Fetches a download's files into temp files, in order, up to PREFETCH ahead
    of the writer, in a thread pool, so several S3 GETs or crops run at once
    while memory holds one chunk per thread. close() blocks until running
    fetches finish, so the caller runs it in an executor."""

    def __init__(self, download: Download, ahead: int = PREFETCH):
        self._tmp = Path(tempfile.mkdtemp(dir=work_dirs.kind_dir(work_dirs.RASTER_JOBS)))
        self._openers = _openers(download, self._tmp)
        self._pool = ThreadPoolExecutor(max_workers=ahead, thread_name_prefix="derivate-zip")
        self._pending = deque(self._pool.submit(opener) for opener in islice(self._openers, ahead))

    def next(self) -> Future | None:
        """The next file's future (its result is an Entry, or None for a crop
        with no data), or None when all files were handed out."""
        if not self._pending:
            return None
        opener = next(self._openers, None)
        if opener is not None:
            self._pending.append(self._pool.submit(opener))
        return self._pending.popleft()

    def close(self) -> None:
        """Cancels the fetches not started, closes the files fetched but not
        taken, and deletes the temp folder."""
        self._pool.shutdown(wait=True, cancel_futures=True)
        for future in self._pending:
            if not future.cancelled() and future.exception() is None and future.result():
                future.result().close()
        shutil.rmtree(self._tmp, ignore_errors=True)
