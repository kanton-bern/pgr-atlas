"""Scratch folders for user-specific files: uploaded polygons while they are
parsed, Raster-Karten results and the Rohdaten of an area's IFK.

They live in ~/probe_data/app_work (PROBE_WORK_DIR) -- on the stages
~/probe_data is a pod-ephemeral emptyDir, unlike /tmp, which there is the
persistent DuckDB spill volume. A folder of their own, because locally
~/probe_data also holds pipeline and analysis data the sweep must never touch.
Every folder is private to one upload or one job: random name, mode 0700,
deleted by its owner when it's done with it (polygon_upload after parsing,
views/raster_karten.py and views/ifk_area.py when a job is replaced or reset).
Two folders are shared: raster_curves/, the exceedance curves of Raster-Karten
selections (probe-core build_exceedance_curves, one file per
curves_cache_key), and ifk_area_maxima/, the simulations' maxima over an IFK
area (build_area_event_maxima, one file per area_maxima_cache_key). Any
session asking for the same area reuses them, and no job deletes them -- only
sweep().
sweep() deletes whatever is older than MAX_AGE_S -- a session that was just
closed, or a pod that crashed mid-way; it runs at startup (run_app.py) and
whenever a new folder is made.
"""

import os
import shutil
import time
import uuid
from pathlib import Path

MAX_AGE_S = 7 * 24 * 3600
UPLOADS = "uploads"
RASTER_JOBS = "raster_jobs"
RASTER_CURVES = "raster_curves"
IFK_JOBS = "ifk_jobs"
IFK_AREA_MAXIMA = "ifk_area_maxima"


def root() -> Path:
    return Path(os.environ.get("PROBE_WORK_DIR", "~/probe_data/app_work")).expanduser()


def kind_dir(kind: str) -> Path:
    """The parent folder of one kind (created, 0700)."""
    folder = root() / kind
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder


def new_dir(kind: str) -> Path:
    """A fresh private folder for one upload/job; sweeps old ones first."""
    sweep()
    folder = kind_dir(kind) / uuid.uuid4().hex
    folder.mkdir(mode=0o700)
    return folder


def remove(path) -> None:
    """Deletes one folder made by new_dir; a missing one is fine."""
    if path:
        shutil.rmtree(path, ignore_errors=True)


def sweep(now: float | None = None) -> int:
    """Deletes every entry older than MAX_AGE_S in the work folders.
    Returns how many were deleted."""
    cutoff = (time.time() if now is None else now) - MAX_AGE_S
    removed = 0
    for kind in (UPLOADS, RASTER_JOBS, RASTER_CURVES, IFK_JOBS, IFK_AREA_MAXIMA):
        parent = root() / kind
        if not parent.is_dir():
            continue
        for entry in parent.iterdir():
            try:
                if entry.lstat().st_mtime >= cutoff:
                    continue
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue  # another sweep got there first
    return removed
