"""Session-state defaults and the per-Anriss cache."""

from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field

import streamlit as st

# Enough to switch back and forth between a few Anrisse without refetching;
# each entry can hold every scenario of an Anriss as a DataFrame.
ANRISS_CACHE_SIZE = 5


@dataclass
class AnrissEntry:
    """Everything the Anriss view has loaded or derived for one Anriss.

    Attributes:
        all_scenarios: Gold data for every scenario, as
            {'df', 'gold_not_ready', 'hull_not_indexed', 'failed'}; None until fetched.
        rohdaten: The enriched Rohdaten export, as {'df', 'failed'}; None until built.
        hull_read: The running read of the precomputed hull; None when none runs.
        hull_fetched: Whether a precomputed hull read has finished.
        hull: The precomputed hull fragment, or None if not indexed yet or failed.
        hull_failed: Whether the hull read failed for another reason (logged).
        release_geojson: The release-area circle per area A (m²), in WGS84.
        reach_circle_geojson: The GOLD_PIXEL_MAX_REACH_M circle, in WGS84.
        map_bounds: The map viewport as [[lat_min, lon_min], [lat_max, lon_max]].
    """

    all_scenarios: dict | None = None
    rohdaten: dict | None = None
    hull_read: Future | None = None
    hull_fetched: bool = False
    hull: dict | None = None
    hull_failed: bool = False
    release_geojson: dict[int, dict] = field(default_factory=dict)
    reach_circle_geojson: dict | None = None
    map_bounds: list | None = None

    def needs_scenarios_fetch(self) -> bool:
        """True if never fetched, or the last fetch found the data not ready yet.

        The campaign keeps finalising kacheln in the background, so a "not ready"
        result is retried on every rerun. A success or a hard error is kept.
        """
        entry = self.all_scenarios
        return entry is None or (entry["df"] is None and not entry["failed"])

    def needs_hull_fetch(self) -> bool:
        """True if no read runs and none has finished, or the last one found the
        hull not indexed yet."""
        if self.hull_read is not None:
            return False
        return not self.hull_fetched or (self.hull is None and not self.hull_failed)


class AnrissCache:
    """The entries of the most recently used Anrisse; the oldest is evicted first."""

    def __init__(self, max_entries: int = ANRISS_CACHE_SIZE) -> None:
        if max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, got {max_entries}")
        self._max_entries = max_entries
        self._entries: OrderedDict[int, AnrissEntry] = OrderedDict()

    def get(self, id_anriss: int) -> AnrissEntry:
        """Return the entry for an Anriss, creating an empty one if needed.

        Marks the Anriss as most recently used. Creating an entry evicts the least
        recently used one when the cache is full.
        """
        key = int(id_anriss)
        if key in self._entries:
            self._entries.move_to_end(key)
            return self._entries[key]
        entry = AnrissEntry()
        self._entries[key] = entry
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return entry

    def __contains__(self, id_anriss: int) -> bool:
        return int(id_anriss) in self._entries

    def __len__(self) -> int:
        return len(self._entries)


def init_session_state() -> None:
    """Set the default of every app-wide session-state key that isn't set yet."""
    defaults = {
        "selected_id_anriss": None,
        "tiff_bytes": {"depth": None, "velocity": None, "pressure": None},
        "hull_geojson": None,
        "hull_geojson_path": None,
        "anriss_cache": AnrissCache(),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
