"""Envelope cache: created on first write, written atomically, reused."""

import pandas as pd

from probe_core.derivate import event_export


def test_envelope_cache_is_created_on_write_and_reused(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setattr(event_export, "CACHE_DIR", cache)
    # two adjacent pixel centres (k*5 + 2.5)
    df = pd.DataFrame({"x": [2600002.5, 2600007.5], "y": [1200002.5, 1200002.5]})

    geojson, path = event_export.export_event_envelope_geojson(df, 42)
    assert geojson["features"] and path == str(cache / "event_42_envelope.geojson")
    assert sorted(entry.name for entry in cache.iterdir()) == [
        "event_42_envelope.geojson"
    ]  # no temp file left

    again, _ = event_export.export_event_envelope_geojson(
        df.iloc[0:0], 42
    )  # empty df: must come from the cache
    assert again == geojson


def test_concurrent_writers_of_one_event_leave_one_complete_file(tmp_path, monkeypatch):
    """Streamlit sessions are threads of one process: same pid, same event."""
    import threading

    cache = tmp_path / "cache"
    monkeypatch.setattr(event_export, "CACHE_DIR", cache)
    df = pd.DataFrame({"x": [2600002.5, 2600007.5], "y": [1200002.5, 1200002.5]})
    results, errors = [], []

    def write():
        try:
            results.append(event_export.export_event_envelope_geojson(df, 7)[0])
        except Exception as error:  # noqa: BLE001 -- surfaced by the assert below
            errors.append(error)

    threads = [threading.Thread(target=write) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(results) == 8
    assert sorted(entry.name for entry in cache.iterdir()) == ["event_7_envelope.geojson"]
    assert event_export.export_event_envelope_geojson(df.iloc[0:0], 7)[0] == results[0]
