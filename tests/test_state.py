from concurrent.futures import Future

import numpy as np
import pytest
import streamlit as st

import state
from state import AnrissCache, AnrissEntry


def test_get_creates_an_empty_entry_and_returns_the_same_one_after():
    cache = AnrissCache()
    entry = cache.get(977441)
    entry.map_bounds = [[46.0, 7.0], [46.1, 7.1]]
    assert cache.get(977441) is entry
    assert len(cache) == 1


def test_numpy_and_python_ids_share_an_entry():
    cache = AnrissCache()
    assert cache.get(np.int64(5)) is cache.get(5)


def test_the_least_recently_created_entry_is_evicted_first():
    cache = AnrissCache(max_entries=2)
    cache.get(1)
    cache.get(2)
    cache.get(3)
    assert 1 not in cache
    assert 2 in cache and 3 in cache


def test_get_refreshes_recency():
    cache = AnrissCache(max_entries=2)
    cache.get(1)
    cache.get(2)
    cache.get(1)
    cache.get(3)
    assert 2 not in cache
    assert 1 in cache and 3 in cache


def test_an_evicted_anriss_comes_back_empty():
    cache = AnrissCache(max_entries=1)
    cache.get(1).hull_fetched = True
    cache.get(2)
    assert cache.get(1).hull_fetched is False


def test_default_size_keeps_five_anrisse():
    cache = AnrissCache()
    for id_anriss in range(6):
        cache.get(id_anriss)
    assert len(cache) == 5
    assert 0 not in cache


def test_max_entries_below_one_is_rejected():
    with pytest.raises(ValueError, match="at least 1"):
        AnrissCache(max_entries=0)


def _scenarios(df=None, failed=False):
    return {"df": df, "gold_not_ready": None, "hull_not_indexed": None, "failed": failed}


@pytest.mark.parametrize(
    ("all_scenarios", "expected"),
    [
        (None, True),
        (_scenarios(), True),
        (_scenarios(df="rows"), False),
        (_scenarios(failed=True), False),
    ],
    ids=["never-fetched", "not-ready-yet", "loaded", "hard-error"],
)
def test_needs_scenarios_fetch(all_scenarios, expected):
    assert AnrissEntry(all_scenarios=all_scenarios).needs_scenarios_fetch() is expected


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (AnrissEntry(), True),
        (AnrissEntry(hull_fetched=True), True),
        (AnrissEntry(hull_fetched=True, hull={"xmin": 0}), False),
        (AnrissEntry(hull_fetched=True, hull_failed=True), False),
        (AnrissEntry(hull_read=Future()), False),
        (AnrissEntry(hull_fetched=True, hull_read=Future()), False),
    ],
    ids=[
        "never-fetched",
        "not-indexed-yet",
        "loaded",
        "hard-error",
        "first-read-running",
        "retry-running",
    ],
)
def test_needs_hull_fetch(entry, expected):
    assert entry.needs_hull_fetch() is expected


def test_init_session_state_fills_missing_keys_and_keeps_set_ones(monkeypatch):
    session = {"selected_id_anriss": 977441}
    monkeypatch.setattr(st, "session_state", session)
    state.init_session_state()
    assert session["selected_id_anriss"] == 977441
    assert session["hull_geojson"] is None
    assert isinstance(session["anriss_cache"], AnrissCache)


def test_init_session_state_keeps_the_existing_cache(monkeypatch):
    session = {}
    monkeypatch.setattr(st, "session_state", session)
    state.init_session_state()
    cache = session["anriss_cache"]
    state.init_session_state()
    assert session["anriss_cache"] is cache
