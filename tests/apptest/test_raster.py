"""Raster-Karten (a selection as the map or an upload would set it, and the job
that runs on it) and Raster-Derivate."""

import json
import os

import pytest
import streamlit as st

from tests.apptest.conftest import map_args, run_until, run_view, texts
from tests.lake_data import DERIVATE_COMBO, IFK_PIXEL, RASTER_SELECTION, lv95_bbox

pytestmark = pytest.mark.apptest

# 20 km x 20 km: more kacheln than max_raster_kacheln() allows on any host.
_TOO_LARGE = {"type": "bbox", "ring": lv95_bbox(IFK_PIXEL, 10_000)}
# Four kacheln, so a job runs long enough to be cancelled between two of them.
_FOUR_KACHELN = {"type": "bbox", "ring": lv95_bbox((2598000.0, 1137000.0), 900)}


def _submit(at, threshold=None):
    if threshold is not None:
        at.sidebar.number_input(key="_raster_threshold_depth").set_value(threshold)
    at.sidebar.button(key="_raster_submit_btn").click()
    return at.run()


def _finished(at):
    return "_raster_result" in at.session_state


def _job_card(at):
    return at.main.get_by_key("pgr_job_card")


def _job_cards(at) -> list:
    """The job cards in the main area, if any: a plain success draws none,
    its downloads being below the map."""
    return [node for node in at.main if getattr(node, "key", None) == "pgr_job_card"]


def _card_is_above_the_map(at) -> bool:
    """The card comes before the map in the main area, so it pushes the map
    down instead of hiding below it (the IFK view does the same)."""
    order = [(node.type, getattr(node, "key", None)) for node in at.main]
    card = next(i for i, (_, key) in enumerate(order) if key == "pgr_job_card")
    map_index = next(
        i for i, (node_type, _) in enumerate(order) if node_type == "component_instance"
    )
    return card < map_index


def test_selection_over_the_kachel_limit_is_refused():
    at = run_view("Raster-Karten", _raster_selection=_TOO_LARGE)
    assert any(e.startswith("Zu gross") for e in texts(at.sidebar.error))
    assert at.sidebar.button(key="_raster_submit_btn").disabled


def test_mode_a_result_reaches_the_map_and_the_downloads():
    at = _submit(run_view("Raster-Karten", _raster_selection=RASTER_SELECTION), threshold=0.1)
    run_until(at, _finished)
    # The downloads are below the map, not in the sidebar card.
    assert "1 Raster erzeugt. Download unten:" in texts(at.main.success)
    assert not _job_cards(at)
    args = map_args(at)
    assert list(args["raster_overlays"]) == ["depth"]
    assert args["active_variable"] == "depth"
    # A descriptor: the map fetches the image and hover grid from the job routes.
    descriptor = args["raster_overlays"]["depth"]
    job_id = at.session_state["_raster_overlay_cache"]["job_id"]
    assert descriptor["job_id"] == job_id and descriptor["var"] == "depth"
    assert "data_url" not in descriptor and "grid_b64" not in (descriptor["hover"] or {})
    (link,) = at.main.get("link_button")
    assert link.proto.url.endswith(f"/job/{job_id}/depth.tif")
    assert link.proto.label.startswith("📥 Fliesstiefe ≥ 0.1 m, Wiederkehrperiode (GeoTIFF, ")
    assert any(
        c.startswith("Datei: adhoc_wiederkehrperiode_fliesstiefe_") for c in texts(at.main.caption)
    )


def test_threshold_zero_is_used_as_given():
    at = _submit(run_view("Raster-Karten", _raster_selection=RASTER_SELECTION), threshold=0.0)
    assert at.session_state["_raster_request"]["threshold"] == 0.0
    run_until(at, _finished)
    (path,) = at.session_state["_raster_result"]["value"]
    assert os.path.basename(path).startswith("depth_at_0.0m_")


def test_no_matching_pixels_says_so():
    at = _submit(run_view("Raster-Karten", _raster_selection=RASTER_SELECTION), threshold=1000.0)
    run_until(at, _finished)
    assert any(
        t.startswith("Keine Pixel erfüllen die gewählten Kriterien")
        for t in texts(_job_card(at).info)
    )
    assert map_args(at)["raster_overlays"] is None


def test_a_running_job_shows_its_progress_above_the_map():
    at = run_view("Raster-Karten", _raster_selection=_FOUR_KACHELN)
    at.sidebar.number_input(key="_raster_threshold_depth").set_value(0.1).run()
    assert not _job_cards(at)
    assert not at.sidebar.get("progress")

    at.sidebar.button(key="_raster_submit_btn").click().run()
    card = _job_card(at)
    assert card.get("progress")
    assert card.button(key="raster_abort_btn").proto.label == "🛑 Abbrechen"
    assert _card_is_above_the_map(at)

    # Cancelled, not run to the end: four kacheln take about 8 min on a CI runner,
    # and the next test's job would wait for this one. A plain success leaving no
    # card is checked by test_mode_a_result_reaches_the_map_and_the_downloads.
    card.button(key="raster_abort_btn").click().run()
    run_until(at, _finished)


def test_cancel_stops_the_job():
    at = _submit(run_view("Raster-Karten", _raster_selection=_FOUR_KACHELN), threshold=0.1)
    _job_card(at).button(key="raster_abort_btn").click().run()
    run_until(at, _finished)
    assert "Raster-Berechnung abgebrochen." in texts(_job_card(at).warning)
    assert not at.main.get("link_button")


def test_a_failed_job_is_shown_and_logged(monkeypatch, caplog):
    from probe_core.derivate import ifk_and_raster

    def _fail(*_args, **_kwargs):
        raise RuntimeError("bucket-internal/key.parquet")

    monkeypatch.setattr(ifk_and_raster, "build_raster_for_bbox", _fail)
    at = _submit(run_view("Raster-Karten", _raster_selection=RASTER_SELECTION), threshold=0.1)
    run_until(at, _finished)
    (error,) = texts(_job_card(at).error)
    assert _card_is_above_the_map(at)
    assert error.startswith("Die Raster-Berechnung ist fehlgeschlagen.")
    assert "bucket-internal" not in error
    assert "Raster build failed (mode a, depth, threshold 0.1" in caplog.text
    assert "bucket-internal/key.parquet" in caplog.text


def test_experten_modus_marks_the_result():
    at = run_view("Raster-Karten", _raster_selection=RASTER_SELECTION)
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    at = _submit(at, threshold=0.1)
    run_until(at, _finished)
    assert any("Experten-Modus aktiv (Beta)" in w for w in texts(_job_card(at).warning))


def test_reset_clears_selection_and_result():
    at = _submit(run_view("Raster-Karten", _raster_selection=RASTER_SELECTION), threshold=0.1)
    run_until(at, _finished)
    at.sidebar.button(key="raster_reset_btn").click().run()
    for key in ("_raster_selection", "_raster_request", "_raster_result", "_raster_overlay_cache"):
        assert key not in at.session_state
    assert map_args(at)["raster_overlays"] is None


@pytest.fixture()
def sim_count_in_the_lake(monkeypatch):
    """The lake listings say sim_count has a mosaic and a kachel file under
    every kachel of RASTER_SELECTION, whatever the test bucket holds."""
    # Imported here: probe-core must not load before _test_lake sets the bucket.
    from probe_core.derivate import derivate_lake
    from probe_core.derivate.ifk_and_raster import kacheln_for_bbox, selection_bounds

    import derivate_download

    kacheln = set(kacheln_for_bbox(*selection_bounds(RASTER_SELECTION)))
    for name, fake in (
        ("list_partitions", lambda metric: [None] if metric == "sim_count" else []),
        ("list_kacheln", lambda metric, partition=None: kacheln),
        (
            "load_mosaic_bands",
            lambda metric, partition=None: [{"index": 1, "name": None, "vmin": 1.0, "vmax": 50.0}],
        ),
    ):
        monkeypatch.setattr(derivate_lake, name, fake)
    monkeypatch.setattr(derivate_download, "list_object_sizes", lambda bucket, prefix: {})
    st.cache_data.clear()
    yield kacheln
    st.cache_data.clear()


def _registered_download(link):
    """The raster_jobs download a link button points to (/download/<id>.zip)."""
    import raster_jobs

    assert link.proto.label.startswith("⬇️ ZIP herunterladen")
    return raster_jobs.get_download(link.proto.url.rsplit("/download/", 1)[1].removesuffix(".zip"))


def test_derivate_map_gets_its_coverage_by_version(sim_count_in_the_lake):
    import coverage_store

    at = run_view("Raster-Derivate")
    at.sidebar.selectbox(key="_derivate_metric").set_value("sim_count").run()

    args = map_args(at)
    assert "coverage_geojson" not in args
    coverage = coverage_store.get(args["coverage_version"])
    features = json.loads(coverage.body)["features"]
    assert sorted(f["properties"]["region"] for f in features) == sorted(
        f"Kachel {k}" for k in sim_count_in_the_lake
    )


def test_derivate_zip_is_registered_on_click_and_linked(sim_count_in_the_lake):
    at = run_view("Raster-Derivate", _derivate_selection=RASTER_SELECTION)
    at.sidebar.selectbox(key="_derivate_metric").set_value("sim_count").run()
    assert not at.get("link_button")

    at.button(key="derivate_build_kacheln_btn").click().run()
    (link,) = at.get("link_button")
    kacheln = _registered_download(link)
    assert kacheln.kind == "kacheln"
    assert [name for name, _ in kacheln.items] == [
        f"derivat_anzahl_simulationen/kachel_{k}.tif" for k in sorted(sim_count_in_the_lake)
    ]

    at.button(key="derivate_build_crop_btn").click().run()
    crop_link, _ = at.get("link_button")  # the crop column comes first
    crop = _registered_download(crop_link)
    assert (crop.kind, crop.items, crop.selection) == (
        "crop",
        (("sim_count", None),),
        RASTER_SELECTION,
    )


def test_derivate_kanton_links_need_no_area(sim_count_in_the_lake, monkeypatch):
    from probe_core.derivate import derivate_lake

    import derivate_download

    key = derivate_lake.mosaic_key("sim_count")
    monkeypatch.setattr(
        derivate_download, "list_object_sizes", lambda bucket, prefix: {key: 485_500_000}
    )
    at = run_view("Raster-Derivate")
    at.sidebar.selectbox(key="_derivate_metric").set_value("sim_count").run()

    assert "derivate_build_crop_btn" not in [b.key for b in at.button]
    # Without an area the left column still carries its title.
    assert "**📐 Ausschnitt (GeoTIFF)**" in [m.value for m in at.markdown]
    (link,) = at.get("link_button")
    assert link.proto.label == "⬇️ Anzahl Simulationen (486 MB)"
    assert link.proto.url.endswith("/canton/sim_count.tif")


def test_derivate_kanton_links_list_their_bands():
    at = run_view("Raster-Derivate", _derivate_metric="hit_rate")

    # Hit rates: one file per variable, one band per threshold.
    assert any(c.value.startswith("Band 1: ≥ ") and " · Band 2: ≥ " in c.value for c in at.caption)
    # The combination: rate and 80-year probability.
    assert "Band 1: Ereignisse pro Jahr · Band 2: Wahrscheinlichkeit in 80 Jahren" in [
        c.value for c in at.caption
    ]


@pytest.fixture()
def no_derivate_data(monkeypatch):
    """Every metric reports no data, whatever the test bucket holds. The app
    caches the listing (st.cache_data), so the cache is cleared before, and
    after so later tests don't see the empty listing."""
    # Imported here: probe-core reads its bucket at import, which conftest sets first.
    from probe_core.derivate import derivate_lake

    st.cache_data.clear()
    monkeypatch.setattr(derivate_lake, "list_partitions", lambda metric: [])
    yield
    st.cache_data.clear()


def test_derivate_metric_without_data_shows_a_note_instead_of_the_map(no_derivate_data):
    at = run_view("Raster-Derivate")
    metric = at.sidebar.selectbox(key="_derivate_metric")
    assert metric.options[metric.index].endswith("(noch keine Daten)")
    # The note is in the main area only, not repeated in the sidebar.
    assert not at.sidebar.info
    assert any(t.startswith("Für «") and "liegen noch keine Daten vor" in t for t in texts(at.info))
    assert not at.get("component_instance")


# ── Raster-Derivate on the test bucket's own derivate lake ──────────────────


def _sidebar_labels(at):
    return [s.proto.label for s in at.sidebar.selectbox]


def test_derivate_pickers_carry_their_help():
    at = run_view("Raster-Derivate", _derivate_metric="return_period")
    assert _sidebar_labels(at) == ["Anzeige auf der Karte", "Variable", "Schwellenwert [m]"]
    assert all(s.proto.help for s in at.sidebar.selectbox)


def test_derivate_intensity_opens_on_300_years():
    at = run_view("Raster-Derivate", _derivate_metric="intensity")
    band = at.sidebar.selectbox[2]
    assert band.proto.label == "Wiederkehrperiode [Jahre]"
    assert band.proto.options[band.index] == "300 Jahre"


def test_derivate_hit_rate_offers_the_combination_as_a_variable():
    at = run_view("Raster-Derivate", _derivate_metric="hit_rate")
    assert not any("Kombinierte" in o for o in at.sidebar.selectbox(key="_derivate_metric").options)
    variable = at.sidebar.selectbox(key="_derivate_variable__hit_rate")
    assert list(variable.proto.options) == [
        "Fliesstiefe",
        "Fliessgeschwindigkeit",
        "Druck",
        "Fliesstiefe und Druck",
    ]
    assert not any("Poisson" in c for c in texts(at.sidebar.caption))

    variable.set_value(("combined_hit_rate", DERIVATE_COMBO)).run()
    assert _sidebar_labels(at) == [
        "Anzeige auf der Karte",
        "Variable",
        "Schwellenwert",
        "Darstellung",
    ]
    threshold = at.sidebar.selectbox[2]
    assert list(threshold.proto.options) == ["Fliesstiefe ≥ 0.1 m und Druck ≥ 3 kN/m²"]
    assert list(at.sidebar.selectbox[3].proto.options) == [
        "Ereignisse pro Jahr",
        "Wahrscheinlichkeit in 80 Jahren",
    ]
    assert any("Poisson" in c for c in texts(at.sidebar.caption))
    assert map_args(at)["derivate_bbox_label"] == (
        "Fliesstiefe ≥ 0.1 m und Druck ≥ 3 kN/m², Trefferhäufigkeit"
    )


def test_derivate_area_caption_and_hit_rate_download_cover_both_datasets():
    at = run_view(
        "Raster-Derivate", _derivate_metric="hit_rate", _derivate_selection=RASTER_SELECTION
    )
    assert any(
        c.startswith("Rechteck: ") and c.endswith(" in 1 km² Kacheln")
        for c in texts(at.sidebar.caption)
    )
    labels = [c.proto.label for c in at.checkbox]
    assert "Trefferhäufigkeit (bei Schwellenwert)" in labels
    assert not any("Kombinierte" in label for label in labels)
    assert at.checkbox(key="_derivate_dl__hit_rate").value

    at.button(key="derivate_build_crop_btn").click().run()
    crop = _registered_download(at.get("link_button")[0])
    assert {m for m, _ in crop.items} == {"hit_rate", "combined_hit_rate"}


def test_derivate_metric_picked_for_the_map_is_ticked_for_download():
    at = run_view("Raster-Derivate", _derivate_metric="return_period")
    assert at.checkbox(key="_derivate_dl__return_period").value
    assert not at.checkbox(key="_derivate_dl__intensity").value
    at.sidebar.selectbox(key="_derivate_metric").set_value("intensity").run()
    assert at.checkbox(key="_derivate_dl__intensity").value
    # Picking a metric adds it; the one ticked before stays ticked.
    assert at.checkbox(key="_derivate_dl__return_period").value
    # Unticked, then picked again for the map: ticked again.
    at.checkbox(key="_derivate_dl__intensity").uncheck().run()
    at.sidebar.selectbox(key="_derivate_metric").set_value("return_period").run()
    at.sidebar.selectbox(key="_derivate_metric").set_value("intensity").run()
    assert at.checkbox(key="_derivate_dl__intensity").value
