"""The coverage GeoJSONs the maps show, shared by the Streamlit script threads
(which publish them) and pmtiles_server.py (which serves them as
/coverage.geojson?v=<version>). Both run in the same process (run_app.py), so
a module-level store is shared by both. It must not live in app.py, which
Streamlit re-executes on every rerun.

Each coverage has a name: "gold" for the finalized gold kacheln (see
ui_common.load_coverage), one per (metric, partition) for Raster-Derivate
(see views/raster_derivate.py's _coverage_version). A name holds its latest body only,
so the store stays as small as the set of names.

The version is derived from the body, so the same coverage always gets the
same URL and the browser can cache it for good. The route finds a coverage
by its version alone.
"""

import gzip
import hashlib
import threading
from typing import NamedTuple


class Coverage(NamedTuple):
    version: str
    body: bytes
    gzipped: bytes


_lock = threading.Lock()
_by_name: dict[str, Coverage] = {}


def publish(name: str, geojson: str) -> str:
    """Makes geojson the coverage served for `name` and returns its version.

    Args:
        name: which coverage this is, e.g. "gold". Replaces the body
            published earlier under the same name.
        geojson: the serialized FeatureCollection.

    Returns:
        The first 16 hex chars of the body's sha256.
    """
    body = geojson.encode()
    version = hashlib.sha256(body).hexdigest()[:16]
    with _lock:
        # Raster-Derivate's metrics mostly share their kacheln: one copy each.
        _by_name[name] = _find(version) or Coverage(version, body, gzip.compress(body))
    return version


def get(version: str) -> Coverage | None:
    """Returns the published coverage with this version, or None if no name
    holds it (never published, or replaced since)."""
    with _lock:
        return _find(version)


def _find(version: str) -> Coverage | None:
    return next((c for c in _by_name.values() if c.version == version), None)
