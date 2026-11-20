"""Finished Raster-Karten jobs, requested Raster-Derivate ZIPs and single
result files (the Rohdaten of an area's IFK), by id, so derivate_bbox_server.py
can serve them over HTTP (/job/<id>/<var>.png|.f32|.tif, /download/<id>.zip,
/file/<id>) instead of the app pushing the bytes through the Streamlit
WebSocket.

The script threads register them and the sidecar handlers look them up. Both
run in the same process (run_app.py), so module-level registries are shared by
both. They must not live in app.py, which Streamlit re-executes on every rerun.

An id is a capability: anyone holding the URL can fetch the files, so ids are
unguessable (secrets.token_urlsafe) and expire after JOB_TTL_S. Each registry
keeps at most MAX_JOBS entries; registering one more evicts its oldest. Jobs,
downloads and files have separate registries, so ZIP requests never evict a
job. A registry only forgets its entries, it never deletes their files (the
view that wrote them owns those).

Running jobs that read gold (Raster-Karten, the IFK of an area) are also
limited here: at most MAX_RUNNING per process, the rest wait
(acquire_run_slot). Each job gets DuckDB's full memory
limit and already uses every CPU of the pod, so jobs side by side only
multiply the memory (up to an out-of-memory crash) without finishing sooner.
"""

import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path

VARIABLES = ("depth", "velocity", "pressure")
DOWNLOAD_KINDS = ("crop", "kacheln")
JOB_TTL_S = 3600
MAX_JOBS = 64
MAX_RUNNING = 1


@dataclass(frozen=True)
class Job:
    """paths: GeoTIFF per variable. meta: what the files alone don't say,
    e.g. {'mode': 'a'|'b', 'threshold': ..., 'return_period': ...}."""

    paths: dict[str, Path]
    meta: dict
    created: float


@dataclass(frozen=True)
class Download:
    """One Raster-Derivate ZIP. kind 'kacheln': items are (name in the ZIP, S3
    key) pairs. kind 'crop': items are (metric, partition) pairs, each cropped
    from its canton mosaic to selection."""

    kind: str
    items: tuple[tuple, ...]
    selection: dict | None
    created: float


@dataclass(frozen=True)
class File:
    """One file on disk, sent as an attachment named download_name."""

    path: Path
    download_name: str
    content_type: str
    created: float


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_downloads: dict[str, Download] = {}
_files: dict[str, File] = {}
_run_slots = threading.BoundedSemaphore(MAX_RUNNING)


def acquire_run_slot(abort: threading.Event, poll_s: float = 0.5) -> bool:
    """Waits for one of the MAX_RUNNING job slots. True once the caller holds
    one (give it back with release_run_slot), False if abort is set first --
    a job cancelled or replaced while it waits never runs."""
    while not _run_slots.acquire(timeout=poll_s):
        if abort.is_set():
            return False
    if abort.is_set():
        _run_slots.release()
        return False
    return True


def release_run_slot() -> None:
    _run_slots.release()


def register(paths: dict[str, str | Path], meta: dict) -> str:
    """Stores a finished job and returns its id.

    Args:
        paths: GeoTIFF path per variable; keys must be in VARIABLES.
        meta: job parameters the routes need (at least 'mode').

    Raises:
        ValueError: a key of paths is not a known variable.
    """
    unknown = set(paths) - set(VARIABLES)
    if unknown:
        raise ValueError(
            f"Unknown raster variables {sorted(unknown)}; expected some of {VARIABLES}"
        )
    return _store(
        _jobs, Job({var: Path(p) for var, p in paths.items()}, dict(meta), time.monotonic())
    )


def get(job_id: str) -> Job | None:
    """The job, or None if the id is unknown or expired."""
    return _lookup(_jobs, job_id)


def register_download(kind: str, items: list[tuple], selection: dict | None = None) -> str:
    """Stores a ZIP request and returns its id.

    Args:
        kind: 'kacheln' (items = (name in the ZIP, S3 key)) or 'crop'
            (items = (metric, partition), cropped to selection).
        items: the ZIP's files, in order.
        selection: the selection a crop is cut to; None for 'kacheln'.

    Raises:
        ValueError: an unknown kind, or a crop without a selection.
    """
    if kind not in DOWNLOAD_KINDS:
        raise ValueError(f"Unknown download kind {kind!r}; expected one of {DOWNLOAD_KINDS}")
    if kind == "crop" and selection is None:
        raise ValueError("A crop download needs the selection to cut to")
    return _store(
        _downloads,
        Download(
            kind,
            tuple(tuple(i) for i in items),
            dict(selection) if selection else None,
            time.monotonic(),
        ),
    )


def get_download(download_id: str) -> Download | None:
    """The ZIP request, or None if the id is unknown or expired."""
    return _lookup(_downloads, download_id)


def register_file(path: str | Path, download_name: str, content_type: str) -> str:
    """Stores one file to serve at /file/<id> and returns its id.

    Args:
        path: the file on disk; it must outlive the id (JOB_TTL_S).
        download_name: the name the browser saves it under.
        content_type: its media type.
    """
    return _store(_files, File(Path(path), download_name, content_type, time.monotonic()))


def get_file(file_id: str) -> File | None:
    """The file, or None if the id is unknown or expired."""
    return _lookup(_files, file_id)


def _store(registry: dict, entry: Job | Download | File) -> str:
    entry_id = secrets.token_urlsafe(32)
    with _lock:
        _drop_expired(registry, entry.created)
        while len(registry) >= MAX_JOBS:
            del registry[next(iter(registry))]  # dicts keep insertion order: oldest first
        registry[entry_id] = entry
    return entry_id


def _lookup(registry: dict, entry_id: str) -> Job | Download | File | None:
    now = time.monotonic()
    with _lock:
        _drop_expired(registry, now)
        return registry.get(entry_id)


def _drop_expired(registry: dict, now: float) -> None:
    for entry_id in [i for i, entry in registry.items() if now - entry.created >= JOB_TTL_S]:
        del registry[entry_id]
