"""Prefetch of one pixel's IFK while its map popup is open.

Clicking a pixel on the IFK map only opens a popup in the browser; Python
hears about it when "IFK berechnen" is clicked, and only then runs
compute_ifk_default (a gold kachel read plus the probability joins, a few
seconds). The popup also calls `POST /prefetch-ifk?x=..&y=..&client=..`
on pmtiles_server (same process), which starts that computation in the
background, so the IFK view usually finds it done.

Same shape as anriss_prefetch, with one difference: entries are kept per
map instance (`client`, a random id each IFK map iframe makes for itself),
one pixel each. Picking another pixel on the same map replaces the entry:
a replaced computation that hasn't started is cancelled, a running one runs
to the end and its result is dropped. Maps that never click "IFK berechnen"
fall out once MAX_CLIENTS newer ones have asked.

Only the production computation is prefetched. With Experten-Modus
overrides the view computes the overridden curves itself and uses the
prefetched result as the original to compare with (views/ifk.py, _result).
"""

import threading
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor

from probe_core.derivate import ifk_and_raster

MAX_CLIENTS = 16
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ifk-prefetch")
_lock = threading.Lock()
_entries: "OrderedDict[str, tuple[tuple[float, float], Future]]" = OrderedDict()


def request(client: str, x: float, y: float) -> bool:
    """Starts compute_ifk_default(x, y) for this map instance unless that
    pixel is already its pending one. Returns True if it started it."""
    pixel = (float(x), float(y))
    with _lock:
        old = _entries.pop(client, None)
        if old is not None and old[0] == pixel:
            _entries[client] = old
            return False
        if old is not None:
            old[1].cancel()  # only cancels one that hasn't started
        _entries[client] = (pixel, _pool.submit(ifk_and_raster.compute_ifk_default, *pixel))
        while len(_entries) > MAX_CLIENTS:
            _, (_, dropped) = _entries.popitem(last=False)
            dropped.cancel()
        return True


def take(client: str, x: float, y: float) -> Future | None:
    """The prefetched Future for this map instance's pixel (x, y), or None if
    nothing matching was prefetched. Taken once."""
    with _lock:
        entry = _entries.get(client)
        if entry is None or entry[0] != (float(x), float(y)):
            return None
        del _entries[client]
        return None if entry[1].cancelled() else entry[1]
