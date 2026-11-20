"""ifk_prefetch: one pending pixel per map instance, taken once, errors kept."""

import threading

import pytest

import ifk_prefetch as ip


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(ip, "_entries", ip.OrderedDict())
    calls = []
    gate = threading.Event()
    gate.set()

    def compute(x, y):
        gate.wait(5)
        calls.append((x, y))
        if x == 13:
            raise RuntimeError("kachel read failed")
        return f"ifk-{x}-{y}"

    monkeypatch.setattr(ip.ifk_and_raster, "compute_ifk_default", compute)
    return calls, gate


def test_prefetched_pixel_is_taken_once(fresh):
    calls, _ = fresh
    assert ip.request("a", 2.5, 7.5) is True
    assert ip.request("a", 2.5, 7.5) is False  # already pending: no second computation
    assert ip.take("a", 2.5, 7.5).result(5) == "ifk-2.5-7.5"
    assert ip.take("a", 2.5, 7.5) is None
    assert calls == [(2.5, 7.5)]


def test_another_pixel_replaces_the_previous_one(fresh):
    calls, gate = fresh
    gate.clear()  # hold the pool's workers
    ip.request("a", 2.5, 2.5)
    ip.request("b", 7.5, 7.5)  # both workers busy now
    ip.request("a", 12.5, 12.5)  # queued
    ip.request("a", 17.5, 17.5)  # replaces the queued one before it starts
    assert ip.take("a", 12.5, 12.5) is None and ip.take("a", 2.5, 2.5) is None
    gate.set()
    assert ip.take("a", 17.5, 17.5).result(5) == "ifk-17.5-17.5"
    assert ip.take("b", 7.5, 7.5).result(5) == "ifk-7.5-7.5"
    assert (12.5, 12.5) not in calls


def test_other_clients_and_pixels_find_nothing(fresh):
    ip.request("a", 2.5, 7.5)
    assert ip.take("b", 2.5, 7.5) is None
    assert ip.take("a", 7.5, 7.5) is None
    assert ip.take("a", 2.5, 7.5) is not None


def test_errors_reach_the_taker_unchanged(fresh):
    ip.request("a", 13, 2.5)
    with pytest.raises(RuntimeError, match="kachel read failed"):
        ip.take("a", 13, 2.5).result(5)


def test_oldest_clients_are_dropped(fresh, monkeypatch):
    monkeypatch.setattr(ip, "MAX_CLIENTS", 2)
    for client_id in ("a", "b", "c"):
        ip.request(client_id, 2.5, 2.5)
    assert list(ip._entries) == ["b", "c"]
