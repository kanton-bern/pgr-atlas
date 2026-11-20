"""Prefetch of one anriss's data while its map popup is open.

Clicking an anriss on a map only opens a popup in the browser; Python hears
about it when "Anriss öffnen" is clicked, and only then reads the anriss's
catalog row, its simulation data (SIM_ANRISS, fallback SIM_SPATIAL) and its
hull fragment from S3 -- about a second in total. The popup also calls
`POST /prefetch?id_anriss=N` on pmtiles_server (same process), which starts
those reads in the background, so the Ereignis view usually finds them done.

Shared by pmtiles_server.py (which requests) and views/anriss.py (which takes): both run
in one process (run_app.py), so this module-level state is shared, like
coverage_store. It must not live in app.py, which Streamlit re-executes on every
rerun.

- A result is a Future that holds the value or the exception of the same call
  views/anriss.py would have made, so its error handling doesn't change.
- take() pops the entry: a transient failure is retried by the next open, not
  cached here. Anrisse that are clicked but never opened are simply dropped
  once MAX_ENTRIES newer ones arrive (a started read runs to the end, the
  result is ignored).
- Only the data read lives here; turning it into display columns stays in
  views/anriss.py.
"""

import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from probe_core.data_lake import data_interface as data

MAX_ENTRIES = 16
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="anriss-prefetch")
_lock = threading.Lock()
_entries: "OrderedDict[int, dict[str, Future]]" = OrderedDict()


def load_sim_data(id_anriss: int, on_fallback: Callable[[], None] | None = None):
    """The anriss's simulation rows: SIM_ANRISS, or the SIM_SPATIAL kachel scan
    if its range isn't in SIM_ANRISS (raises what those raise). on_fallback is
    called before the kachel scan starts."""
    try:
        return data.get_anriss_sim_data(id_anriss)
    except data.SimAnrissNotIndexedError:
        if on_fallback is not None:
            on_fallback()
        return data.get_anriss_all_scenarios_gold_data(id_anriss)


def _submit(id_anriss: int) -> dict[str, Future]:
    # The catalog row first (get_event_params warms probe-core's per-anriss
    # cache that id_anriss_exists and both fragment keys read), then both
    # reads in parallel.
    catalog = _pool.submit(data.get_event_params, id_anriss)

    def after_catalog(fetch):
        def run():
            catalog.result()  # an unknown id raises here, for every entry
            return fetch(id_anriss)

        return run

    return {
        "catalog": catalog,
        "sim": _pool.submit(after_catalog(load_sim_data)),
        "hull": _pool.submit(after_catalog(data.get_anriss_hull_fragment)),
    }


def request(id_anriss: int) -> bool:
    """Starts the reads for id_anriss unless they're already pending or done.
    Returns True if it started them."""
    with _lock:
        if id_anriss in _entries:
            _entries.move_to_end(id_anriss)
            return False
        _entries[id_anriss] = _submit(id_anriss)
        while len(_entries) > MAX_ENTRIES:
            _, old = _entries.popitem(last=False)
            for f in old.values():
                f.cancel()  # only cancels reads that haven't started
        return True


def take(id_anriss: int, part: str) -> Future | None:
    """The prefetched Future for one part ('sim' or 'hull') of id_anriss, or
    None if nothing was prefetched. Each part can be taken once."""
    with _lock:
        entry = _entries.get(id_anriss)
        if entry is None:
            return None
        future = entry.pop(part, None)
        if not (entry.keys() - {"catalog"}):
            del _entries[id_anriss]
        return None if future is None or future.cancelled() else future
