"""Simulierte Ereignisse, the Anriss-ID lookup and the Anriss view (Specific Simulation)."""

import threading

import pytest

from tests.apptest.conftest import (
    assert_no_exception,
    current_view,
    labels,
    map_args,
    nav_links,
    new_app,
    open_page,
    run_until,
    run_view,
    texts,
)
from tests.lake_data import ANRISS_ID, UNKNOWN_ANRISS_ID

pytestmark = pytest.mark.apptest

OVERVIEW = "Overview (All Events)"
ANRISS_VIEW = "Specific Simulation"
_LINK_VIEW = {"z": "12.50", "lat": "46.75000", "lon": "7.63000"}


def _open_link(query_params, view=OVERVIEW, **state):
    at = new_app(view)
    at.query_params.update(query_params)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_no_exception(at)
    return at


def _lookup(at, anriss_id):
    at.sidebar.number_input(key="_anriss_input").set_value(anriss_id)
    next(b for b in at.sidebar.button if b.label == "Anriss öffnen").click()
    return at.run()


def test_overview_shows_the_data_summary_in_its_header():
    at = run_view(OVERVIEW)
    (popover,) = at.main.get("popover")
    assert popover.proto.popover.label.startswith("Datenstand · ")
    assert [m.label for m in at.metric] == [
        "Prozessquellen",
        "Anrisse",
        "Grössenklassen",
        "Simulationen",
        "Kacheln (1 km²)",
    ]


def test_a_link_with_a_map_view_starts_the_map_there():
    args = map_args(_open_link(_LINK_VIEW))
    assert (args["initial_zoom"], args["center_lat"], args["center_lon"]) == (12.5, 46.75, 7.63)


def test_a_link_with_a_bad_map_view_says_so_and_starts_the_map_as_usual():
    at = _open_link({**_LINK_VIEW, "z": "25"})
    assert any("keine gültige Kartenansicht" in w for w in texts(at.warning))
    assert map_args(at)["initial_zoom"] is None


def test_the_view_at_the_last_anriss_click_wins_over_the_link():
    last_click = {"lat": 46.6, "lon": 7.7, "zoom": 15.0}
    args = map_args(_open_link(_LINK_VIEW, _overview_last_view=last_click))
    assert (args["initial_zoom"], args["center_lat"], args["center_lon"]) == (15.0, 46.6, 7.7)


def test_deselecting_the_anriss_puts_the_overview_map_view_in_the_url():
    at = run_view(
        ANRISS_VIEW,
        selected_id_anriss=ANRISS_ID,
        _return_view=OVERVIEW,
        _overview_last_view={"lat": 46.75, "lon": 7.63, "zoom": 12.5},
    )
    next(b for b in at.button if b.key == "btn_zurueck").click()
    at.run()
    assert_no_exception(at)
    assert current_view(at) == OVERVIEW
    assert at.query_params == _LINK_VIEW
    args = map_args(at)
    assert (args["initial_zoom"], args["center_lat"], args["center_lon"]) == (12.5, 46.75, 7.63)


def test_lookup_of_a_known_anriss_opens_its_view_and_link():
    at = _lookup(run_view(OVERVIEW), ANRISS_ID)
    assert current_view(at) == ANRISS_VIEW
    assert at.session_state["selected_id_anriss"] == ANRISS_ID
    assert at.query_params == {"id": str(ANRISS_ID)}


def test_the_sidebar_anriss_link_opens_the_anriss():
    at = run_view(OVERVIEW, selected_id_anriss=ANRISS_ID)
    (link,) = [
        link for link in at.sidebar.get("page_link") if link.proto.label == f"Anriss {ANRISS_ID}"
    ]
    assert link.proto.query_string == f"id={ANRISS_ID}"
    open_page(at, ANRISS_VIEW).run()
    assert_no_exception(at)
    assert current_view(at) == ANRISS_VIEW


def test_a_link_opens_its_anriss():
    at = _open_link({"id": str(ANRISS_ID)}, view=ANRISS_VIEW)
    assert current_view(at) == ANRISS_VIEW
    assert at.session_state["selected_id_anriss"] == ANRISS_ID
    assert f"Anriss {ANRISS_ID}" in nav_links(at)
    assert int(at.metric[2].value) > 0


def test_a_link_to_an_unknown_anriss_says_so_and_offers_the_lookup():
    at = _open_link({"id": str(UNKNOWN_ANRISS_ID)}, view=ANRISS_VIEW)
    # Still the Anriss page (its error, and the lookup in the sidebar), not
    # Simulierte Ereignisse: no Anriss is selected, so no nav link is marked.
    assert current_view(at) is None
    assert at.session_state["selected_id_anriss"] is None
    assert f"Anriss {UNKNOWN_ANRISS_ID} nicht im Manifest." in texts(at.error)
    assert at.sidebar.number_input(key="_anriss_input")


def test_a_link_with_a_bad_id_says_so():
    at = _open_link({"id": "abc"}, view=ANRISS_VIEW)
    assert at.session_state["selected_id_anriss"] is None
    assert any("keine gültige Anriss-ID" in e for e in texts(at.error))


def test_a_bad_link_keeps_the_anriss_already_open():
    at = _open_link({"id": str(UNKNOWN_ANRISS_ID)}, view=ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    assert f"Anriss {UNKNOWN_ANRISS_ID} nicht im Manifest." in texts(at.error)
    assert at.session_state["selected_id_anriss"] == ANRISS_ID
    assert int(at.metric[2].value) > 0


def test_lookup_of_an_unknown_anriss_says_so():
    at = _lookup(run_view(OVERVIEW), UNKNOWN_ANRISS_ID)
    assert current_view(at) == OVERVIEW
    assert f"Anriss {UNKNOWN_ANRISS_ID} nicht im Manifest." in texts(at.sidebar.error)


@pytest.fixture(scope="module")
def anriss_view():
    return run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)


def test_anriss_view_shows_the_scenario(anriss_view):
    at = anriss_view
    # The rate and return period next to the values, in the Statistik.
    assert [m.label for m in at.metric] == [
        "Max Fliesstiefe [m]",
        "Durchschnitt Fliesstiefe [m]",
        "Datenpunkte",
        "Ereignisrate λ [1/Jahr]",
        "Wiederkehrperiode [Jahre]",
    ]
    assert int(at.metric[2].value) > 0
    assert "× 10" in at.metric[3].value
    args = map_args(at)
    assert args["cells_geojson"]["features"]
    assert args["active_variable"] == "depth"


def test_anriss_view_offers_the_scenario_downloads(anriss_view):
    downloads = labels(anriss_view.main.get("download_button"))
    for label in (
        "📥 Fliesstiefe [m] (GeoTIFF, ",
        "📥 Fliessgeschwindigkeit [m/s] (GeoTIFF, ",
        "📥 Druck [kN/m²] (GeoTIFF, ",
        "📥 Rohdaten (CSV, ",
    ):
        assert any(d.startswith(label) for d in downloads), label


def test_anriss_view_variable_picked_on_the_map_changes_statistics_and_map():
    # The map's variable switch stores its pick in _anriss_view_target.
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID, _anriss_view_target="velocity")
    assert at.metric[0].label == "Max Fliessgeschwindigkeit [m/s]"
    assert map_args(at)["active_variable"] == "velocity"


@pytest.fixture()
def gold_not_ready(monkeypatch):
    from probe_core.data_lake import data_interface

    def _raise(_id_anriss):
        raise data_interface.GoldNotReadyError([12345678])

    monkeypatch.setattr(data_interface, "get_anriss_sim_data", _raise)


def test_anriss_in_unfinished_kacheln_names_them(gold_not_ready):
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    assert any("noch nicht berechnete Kachel(n): [12345678]" in w for w in texts(at.warning))


def test_anriss_not_in_the_hull_index_says_so_without_the_script(monkeypatch):
    from probe_core.data_lake import data_interface

    def _not_indexed(id_anriss):
        raise data_interface.HullFragmentNotIndexedError(id_anriss)

    monkeypatch.setattr(data_interface, "get_anriss_sim_data", _not_indexed)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    (warning,) = [w for w in texts(at.warning) if "Umhüllende" in w]
    assert warning == (
        f"Anriss {ANRISS_ID}: Die Umhüllende ist noch nicht berechnet. "
        "Bitte später erneut versuchen."
    )


_STEP_SIM = "Simulationsdaten"
_STEP_FALLBACK = "Dort noch nicht vorhanden: Suche in den berechneten Kacheln (dauert länger)"


def _anriss_load_status(at):
    """The Anriss view's load status; app.py's start-up status is in at.status too."""
    return [
        s for s in at.main.status if s.label in ("Anriss wird geladen…", "Anriss nicht geladen")
    ]


def test_a_loaded_anriss_leaves_no_load_status(anriss_view):
    assert _anriss_load_status(anriss_view) == []


def test_an_anriss_that_did_not_load_keeps_its_load_steps(gold_not_ready):
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    (status,) = _anriss_load_status(at)
    assert (status.label, status.state) == ("Anriss nicht geladen", "error")
    assert texts(status.markdown) == [_STEP_SIM]


def test_the_load_status_shows_the_sim_spatial_fallback(monkeypatch):
    from probe_core.data_lake import data_interface

    def _not_in_sim_anriss(id_anriss):
        raise data_interface.SimAnrissNotIndexedError(id_anriss)

    def _not_ready(_id_anriss):
        raise data_interface.GoldNotReadyError([12345678])

    monkeypatch.setattr(data_interface, "get_anriss_sim_data", _not_in_sim_anriss)
    monkeypatch.setattr(data_interface, "get_anriss_all_scenarios_gold_data", _not_ready)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    (status,) = _anriss_load_status(at)
    assert texts(status.markdown) == [_STEP_SIM, _STEP_FALLBACK]


_HULL_LOADING = "⏳ Umhüllende wird geladen…"
# The start of each Umhüllende download's label; the size follows.
_HULL_DOWNLOADS = ("📥 Umhüllende, LV95 (GeoPackage, ", "📥 Umhüllende, WGS84 (GeoJSON, ")


def _hull_downloads(at) -> list[str]:
    return [
        label
        for label in labels(at.main.get("download_button"))
        if label.startswith(_HULL_DOWNLOADS)
    ]


def _hull_overlay(at):
    return next(o for o in map_args(at)["overlays"] if o["id"] == "hull")


@pytest.fixture()
def slow_hull(monkeypatch):
    """The hull read waits until the test sets the returned event."""
    from probe_core.data_lake import data_interface

    gate = threading.Event()
    read = data_interface.get_anriss_hull_fragment

    def _read_when_released(id_anriss):
        if not gate.wait(120):
            raise TimeoutError("the test never released the hull read")
        return read(id_anriss)

    monkeypatch.setattr(data_interface, "get_anriss_hull_fragment", _read_when_released)
    yield gate
    gate.set()


def test_the_page_does_not_wait_for_the_hull(slow_hull):
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    assert int(at.metric[2].value) > 0
    assert _hull_overlay(at)["geojson"] is None
    assert _HULL_LOADING in texts(at.sidebar.caption)
    assert not _hull_downloads(at)

    slow_hull.set()
    run_until(at, lambda at: _hull_overlay(at)["geojson"] is not None, timeout_s=120)
    assert _HULL_LOADING not in texts(at.sidebar.caption)
    assert len(_hull_downloads(at)) == 2


# The text of the exceptions the fakes below raise: the log gets it, the page doesn't.
_INTERNAL = "bucket-internal/key.parquet"


def test_a_failed_hull_read_is_shown_and_logged(monkeypatch, caplog):
    from probe_core.data_lake import data_interface

    def _fail(_id_anriss):
        raise RuntimeError(_INTERNAL)

    monkeypatch.setattr(data_interface, "get_anriss_hull_fragment", _fail)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    run_until(at, lambda at: at.sidebar.error, timeout_s=60)
    (error,) = texts(at.sidebar.error)
    assert error.startswith("Vorberechnete Umhüllende konnte nicht geladen werden.")
    assert _INTERNAL not in error
    assert f"Precomputed hull read failed for Anriss {ANRISS_ID}" in caplog.text
    assert _INTERNAL in caplog.text


def test_a_failed_anriss_load_is_shown_and_logged(monkeypatch, caplog):
    from probe_core.data_lake import data_interface

    def _fail(_id_anriss):
        raise RuntimeError(_INTERNAL)

    monkeypatch.setattr(data_interface, "get_anriss_sim_data", _fail)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    (error,) = [e for e in texts(at.main.error) if "Anriss" in e]
    assert error.startswith(f"Fehler beim Laden der Daten für Anriss {ANRISS_ID}.")
    assert _INTERNAL not in error
    assert f"Loading the scenarios of Anriss {ANRISS_ID} failed" in caplog.text
    assert _INTERNAL in caplog.text


def test_a_failed_probability_join_is_shown_and_logged(monkeypatch, caplog):
    # lambda_Ereignis (Statistik) and the Rohdaten export both join the probabilities.
    from probe_core.derivate import ifk_and_raster

    def _fail(_df):
        raise RuntimeError(_INTERNAL)

    monkeypatch.setattr(ifk_and_raster, "enrich_with_probabilities", _fail)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    assert "⚠️ Die Ereignisrate λ konnte nicht berechnet werden." in texts(at.main.caption)
    (error,) = texts(at.main.error)
    assert error.startswith("Rohdaten-Berechnung fehlgeschlagen.")
    assert not any(_INTERNAL in t for t in texts(at.main.caption) + texts(at.main.error))
    assert "lambda_Ereignis failed" in caplog.text
    assert f"Rohdaten export failed for Anriss {ANRISS_ID}" in caplog.text
    assert _INTERNAL in caplog.text


def test_the_adhoc_hull_error_is_still_shown_after_its_rerun(gold_not_ready, monkeypatch):
    from views import anriss

    monkeypatch.setattr(anriss, "_SHOW_ADHOC_HULL_BUTTON", True)
    at = run_view(ANRISS_VIEW, selected_id_anriss=ANRISS_ID)
    next(b for b in at.sidebar.button if b.label == "🛡️ Ad-hoc Umhüllende berechnen").click()
    at.run()
    assert_no_exception(at)
    assert "Noch nicht alle benötigten Kacheln fertig: [12345678]" in texts(at.sidebar.error)
    at.run()
    assert "Noch nicht alle benötigten Kacheln fertig: [12345678]" not in texts(at.sidebar.error)


@pytest.fixture()
def fresh_startup():
    """The startup reads are cached (st.cache_resource): cleared before, so
    the test's failure is hit, and after, so later tests read the lake again."""
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_startup_status_groups_the_counts_the_swiss_way(fresh_startup, monkeypatch):
    from probe_core.data_lake import data_interface

    real_stats = data_interface.catalog_overview_stats
    monkeypatch.setattr(
        data_interface,
        "catalog_overview_stats",
        lambda: {**real_stats(), "pq_count": 4754, "area_count": 1234},
    )

    # The status box empties once startup is done; a failure in the next step
    # leaves it standing, with the lines written so far.
    def _stop_after_the_manifest():
        raise RuntimeError("stop after the manifest step")

    monkeypatch.setattr(data_interface, "count_simulations", _stop_after_the_manifest)

    at = new_app(OVERVIEW).run()

    shown = [m.value for m in at.markdown]
    assert any(line.endswith("4'754 Prozessquellen, 1'234 Grössenklassen") for line in shown)


@pytest.mark.parametrize(
    "has_key, message",
    [
        (False, "Die Zugangsdaten für den Datenspeicher (S3) fehlen."),
        (True, "Der Datenspeicher (S3) ist mit den hinterlegten Zugangsdaten nicht erreichbar."),
    ],
)
def test_unreachable_s3_shows_a_message_instead_of_a_traceback(
    fresh_startup, monkeypatch, has_key, message
):
    import botocore.exceptions
    from probe_core.data_lake import data_interface

    import s3_target

    def no_s3():
        raise botocore.exceptions.NoCredentialsError()

    monkeypatch.setattr(data_interface, "catalog_overview_stats", no_s3)
    monkeypatch.setattr(s3_target, "has_credentials", lambda: has_key)

    at = new_app(OVERVIEW).run()

    assert not at.exception
    assert [e.value for e in at.error if e.value.startswith(message)]
