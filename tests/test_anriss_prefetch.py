"""anriss_prefetch: reads started once per anriss, taken once, errors kept."""

import threading
from unittest import mock

import pytest

import anriss_prefetch as ap

LOAD_SIM_DATA = ap.load_sim_data  # the real one; the fixture replaces it


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ap, "_entries", ap.OrderedDict())
    calls = {"params": [], "sim": [], "hull": []}
    gate = threading.Event()
    gate.set()

    def params(id_anriss):
        calls["params"].append(id_anriss)
        if id_anriss == 404:
            raise ValueError("not in the manifest")
        return f"params-{id_anriss}"

    def sim(id_anriss):
        gate.wait(5)
        calls["sim"].append(id_anriss)
        if id_anriss == 13:
            raise RuntimeError(f"gold not ready {id_anriss}")
        return f"sim-{id_anriss}"

    def hull(id_anriss):
        calls["hull"].append(id_anriss)
        return f"hull-{id_anriss}"

    monkeypatch.setattr(ap.data, "get_event_params", params)
    monkeypatch.setattr(ap, "load_sim_data", sim)
    monkeypatch.setattr(ap.data, "get_anriss_hull_fragment", hull)
    return calls, gate


def test_prefetched_parts_are_taken_once(fresh):
    calls, _ = fresh
    assert ap.request(1) is True
    assert ap.request(1) is False  # already pending: no second read
    assert ap.take(1, "sim").result(5) == "sim-1"
    assert ap.take(1, "hull").result(5) == "hull-1"
    assert ap.take(1, "sim") is None and 1 not in ap._entries
    assert calls["params"] == [1] and calls["sim"] == [1] and calls["hull"] == [1]


def test_nothing_prefetched_means_none():
    assert ap.take(99, "sim") is None


def test_errors_reach_the_taker_unchanged(fresh):
    ap.request(404)
    with pytest.raises(ValueError, match="not in the manifest"):
        ap.take(404, "sim").result(5)
    ap.request(13)
    with pytest.raises(RuntimeError, match="gold not ready 13"):
        ap.take(13, "sim").result(5)


def test_old_entries_are_dropped(fresh, monkeypatch):
    calls, gate = fresh
    monkeypatch.setattr(ap, "MAX_ENTRIES", 2)
    gate.clear()  # keep the pool busy
    for id_anriss in (1, 2, 3):
        ap.request(id_anriss)
    assert list(ap._entries) == [2, 3]
    gate.set()
    assert ap.take(3, "sim").result(5) == "sim-3"


def test_load_sim_data_falls_back_to_the_kachel_scan(monkeypatch):
    monkeypatch.setattr(
        ap.data, "get_anriss_sim_data", mock.Mock(side_effect=ap.data.SimAnrissNotIndexedError(5))
    )
    monkeypatch.setattr(
        ap.data, "get_anriss_all_scenarios_gold_data", mock.Mock(return_value="spatial-5")
    )
    assert LOAD_SIM_DATA(5) == "spatial-5"


def test_load_sim_data_announces_the_fallback_before_the_kachel_scan(monkeypatch):
    events = []
    monkeypatch.setattr(
        ap.data, "get_anriss_sim_data", mock.Mock(side_effect=ap.data.SimAnrissNotIndexedError(5))
    )
    monkeypatch.setattr(
        ap.data,
        "get_anriss_all_scenarios_gold_data",
        lambda i: events.append("scan") or f"spatial-{i}",
    )
    assert LOAD_SIM_DATA(5, on_fallback=lambda: events.append("fallback")) == "spatial-5"
    assert events == ["fallback", "scan"]


def test_load_sim_data_from_sim_anriss_takes_no_fallback(monkeypatch):
    monkeypatch.setattr(ap.data, "get_anriss_sim_data", mock.Mock(return_value="anriss-5"))
    on_fallback = mock.Mock()
    assert LOAD_SIM_DATA(5, on_fallback=on_fallback) == "anriss-5"
    on_fallback.assert_not_called()
