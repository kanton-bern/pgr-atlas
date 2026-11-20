"""Event catalog + in-memory gold manifest: no local database; lookups read an
id_anriss-sorted parquet, totals a precomputed JSON. S3 is replaced by a local parquet and fixed stats here."""

from datetime import datetime, timezone

import duckdb
import pandas as pd
import pytest

from probe_core.data_lake import data_interface as di

STATS = {
    "n_manifest_rows": 6,
    "n_anriss": 3,
    "n_areas": 2,
    "n_prozessquellen": 2,
    "center_x": 2600000.0,
    "center_y": 1200000.0,
    "home_kacheln": {
        26001200: {"n_anriss": 2, "n_rows": 4, "areas": [55, 125], "prozessquellen": [7]},
        26011200: {"n_anriss": 1, "n_rows": 2, "areas": [55], "prozessquellen": [8]},
    },
}


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    rows = pd.DataFrame(
        {
            "id_anriss": [1, 1, 2, 2, 3, 3],
            "id_prozessquelle": [7, 7, 7, 7, 8, 8],
            "x_anriss": [2600100.0] * 4 + [2601100.0] * 2,
            "y_anriss": [1200100.0] * 6,
            "d": [40, 40, 50, 50, 60, 60],
            "A": [55, 55, 125, 125, 55, 55],
            "h": [40, 70, 50, 90, 60, 80],
            "h_type": ["mean", "max"] * 3,
            "sort_key": [11, 12, 101, 102, 205, 206],
        }
    )
    path = tmp_path / "catalog.parquet"
    duckdb.connect().register("rows", rows).execute(f"COPY rows TO '{path}' (FORMAT parquet)")
    monkeypatch.setattr(di, "EVENT_CATALOG_S3_URI", str(path))
    monkeypatch.setattr(di, "_catalog_stats", lambda: STATS)
    di._catalog_con.cache_clear()
    di._catalog_rows.cache_clear()
    di._catalog_tls.__dict__.clear()
    di._expected_gold_kacheln.cache_clear()
    yield
    di._catalog_con.cache_clear()
    di._catalog_rows.cache_clear()
    di._catalog_tls.__dict__.clear()
    di._expected_gold_kacheln.cache_clear()


def test_point_lookups(catalog):
    assert di.id_anriss_exists(2) and not di.id_anriss_exists(4)
    params = di.get_event_params(1)
    assert sorted(params["h"].unique()) == [40, 70]
    assert len(params) == 2 * len(di._PHYSICS_GRID)
    with pytest.raises(ValueError):
        di.get_event_params(4)


def test_sort_key_drives_fragment_keys(catalog):
    # sort_key 205 -> batch 3 -> range 0
    assert di._hull_fragment_s3_key(3).endswith("batch_0000_umhuellende.parquet")
    assert di._sim_anriss_s3_key(3) is not None
    assert di._hull_fragment_s3_key(4) is None


def test_totals_come_from_stats(catalog, monkeypatch):
    assert di.count_simulations() == 6 * len(di._PHYSICS_GRID)
    overview = di.catalog_overview_stats()
    assert (overview["anriss_count"], overview["area_count"], overview["pq_count"]) == (3, 2, 2)
    assert 7.0 < overview["center_lon"] < 8.0 and 46.0 < overview["center_lat"] < 47.5

    monkeypatch.setattr(di, "_finalized", frozenset({26011200}))
    assert di.gold_coverage_stats() == {
        "anriss_count": 1,
        "area_count": 1,
        "pq_count": 1,
        "sim_count": 2 * len(di._PHYSICS_GRID),
    }
    monkeypatch.setattr(di, "_finalized", frozenset(STATS["home_kacheln"]))
    cov = di.gold_coverage_stats()
    assert (cov["anriss_count"], cov["area_count"], cov["pq_count"]) == (3, 2, 2)
    # 2 home kacheln -> the union of their 5x5 neighbourhoods
    assert di.expected_gold_kachel_count() == 30


def _fake_gold_listing(monkeypatch, modified: dict):
    """S3 answers the gold listing with one data.parquet per kachel in
    `modified` (id_kachel -> LastModified), plus a key that isn't one."""

    class FakeS3:
        def get_paginator(self, name):
            return self

        def paginate(self, Bucket, Prefix):
            keys = [
                {"Key": f"{Prefix}{id_kachel}/data.parquet", "LastModified": last_modified}
                for id_kachel, last_modified in modified.items()
            ]
            return [
                {"Contents": keys[:1]},
                {"Contents": keys[1:] + [{"Key": f"{Prefix}9/_tmp"}]},
                {},
            ]

    monkeypatch.setattr(di, "get_s3_client", FakeS3)


def test_gold_manifest_is_a_fresh_snapshot(monkeypatch):
    older, newer = (
        datetime(2026, 9, 12, tzinfo=timezone.utc),
        datetime(2026, 10, 6, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(di, "_finalized", None)
    _fake_gold_listing(monkeypatch, {1: older, 2: older})
    assert di._finalized_kacheln() == {1, 2}  # refreshes on first use
    _fake_gold_listing(monkeypatch, {2: older, 3: newer})
    assert di.refresh_gold_manifest() == {
        "new_kacheln": 1,
        "total_kacheln": 2,
        "newest_modified": newer,
    }
    assert di._finalized_kacheln() == {2, 3}  # kachel 1 is gone, not kept


def test_gold_manifest_without_gold_has_no_date(monkeypatch):
    monkeypatch.setattr(di, "_finalized", None)
    _fake_gold_listing(monkeypatch, {})
    assert di.refresh_gold_manifest() == {
        "new_kacheln": 0,
        "total_kacheln": 0,
        "newest_modified": None,
    }


def test_thread_cursors_carry_the_s3_settings():
    """SET s3_* is per connection; a cursor that doesn't repeat it reads S3
    anonymously (403)."""
    import threading

    di._catalog_con.cache_clear()
    di._catalog_tls.__dict__.clear()
    endpoints = []

    def probe():
        endpoints.append(
            di._catalog_cursor().execute("SELECT current_setting('s3_endpoint')").fetchone()[0]
        )

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join()
    base = di._catalog_con().execute("SELECT current_setting('s3_endpoint')").fetchone()[0]
    assert endpoints == [base] and base
    di._catalog_con.cache_clear()


def test_one_s3_read_per_anriss(catalog, monkeypatch):
    """Params, existence and both fragment keys share one catalog read."""
    reads = []
    cursor = di._catalog_cursor

    def counting():
        reads.append(1)
        return cursor()

    monkeypatch.setattr(di, "_catalog_cursor", counting)
    di.get_event_params(3)
    di.id_anriss_exists(3)
    di._hull_fragment_s3_key(3)
    di._sim_anriss_s3_key(3)
    assert len(reads) == 1
