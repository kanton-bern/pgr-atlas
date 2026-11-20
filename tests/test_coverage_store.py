import gzip
import hashlib
import threading

import pytest

import coverage_store

_GEOJSON = '{"type": "FeatureCollection", "features": []}'
_OTHER = _GEOJSON.replace("[]", "[null]")


@pytest.fixture(autouse=True)
def _empty_store(monkeypatch):
    monkeypatch.setattr(coverage_store, "_by_name", {})


def test_unknown_version_is_none():
    assert coverage_store.get("0123456789abcdef") is None
    assert coverage_store.get("") is None


def test_version_is_a_short_sha256_of_the_body():
    version = coverage_store.publish("gold", _GEOJSON)

    assert version == hashlib.sha256(_GEOJSON.encode()).hexdigest()[:16]


def test_published_body_is_stored_plain_and_gzipped():
    version = coverage_store.publish("gold", _GEOJSON)

    coverage = coverage_store.get(version)
    assert coverage.version == version
    assert coverage.body == _GEOJSON.encode()
    assert gzip.decompress(coverage.gzipped) == _GEOJSON.encode()


def test_same_body_keeps_the_version_and_a_new_body_replaces_it():
    first = coverage_store.publish("gold", _GEOJSON)
    assert coverage_store.publish("gold", _GEOJSON) == first

    second = coverage_store.publish("gold", _OTHER)

    assert second != first
    assert coverage_store.get(second).body == _OTHER.encode()
    assert coverage_store.get(first) is None


def test_names_are_served_side_by_side():
    gold = coverage_store.publish("gold", _GEOJSON)
    derivate = coverage_store.publish("derivate/sim_count/None", _OTHER)

    assert coverage_store.get(gold).body == _GEOJSON.encode()
    assert coverage_store.get(derivate).body == _OTHER.encode()


def test_two_names_with_the_same_body_share_one_entry():
    first = coverage_store.publish("derivate/a/depth", _GEOJSON)
    second = coverage_store.publish("derivate/b/depth", _GEOJSON)

    assert second == first
    assert (
        coverage_store._by_name["derivate/a/depth"] is coverage_store._by_name["derivate/b/depth"]
    )

    coverage_store.publish("derivate/a/depth", _OTHER)

    assert coverage_store.get(first).body == _GEOJSON.encode()


def test_concurrent_publishes_leave_a_consistent_entry():
    bodies = [f'{{"n": {number}}}' for number in range(20)]
    threads = [
        threading.Thread(target=coverage_store.publish, args=("gold", body)) for body in bodies
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    (coverage,) = coverage_store._by_name.values()
    assert coverage.body.decode() in bodies
    assert coverage.version == hashlib.sha256(coverage.body).hexdigest()[:16]
    assert coverage_store.get(coverage.version) is coverage
