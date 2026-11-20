"""IFK-Berechnung: a picked pixel (as the map would send it) and its result."""

import json

import pytest

from tests.apptest.conftest import assert_no_exception, labels, map_args, new_app, run_view, texts
from tests.lake_data import IFK_PIXEL, IFK_PIXEL_NO_PROCESS, IFK_PIXEL_OUTSIDE

pytestmark = pytest.mark.apptest


def test_pixel_shows_three_curves_their_downloads_and_the_anrisse():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    assert len(at.get("vega_lite_chart")) == 3
    downloads = labels(at.get("download_button"))
    assert downloads.count("📥 Daten (CSV)") == 3
    assert downloads.count("📥 Bild (PNG)") == 3
    assert "📥 Rohdaten (CSV) - alle Ereignisse für diesen Pixel" in downloads
    assert map_args(at)["anriss_circles_geojson"]["features"]


def _summary_of_result(at) -> str:
    """The return-period text the summary should show for the current result.
    Imported here: probe-core must not load before the _test_lake fixture."""
    from ui_text import ifk_summary_return_period
    from views.ifk import result_summary

    _, highest = result_summary(at.session_state["_ifk_result"]["data"])
    return ifk_summary_return_period(highest)


def _summary(at) -> list[str]:
    """The texts of the summary row above the curves; none without it."""
    return [
        text
        for text in texts(at.markdown)
        if text.startswith(("**Pixel (LV95)**", "Höchste Wiederkehrperiode"))
        or text.endswith((" beitragende Anrisse", " beitragender Anriss"))
    ]


def test_pixel_summary_names_the_pixel_its_anrisse_and_the_highest_return_period():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    assert _summary(at) == [
        "**Pixel (LV95)** 2'598'502.5 / 1'137'502.5",
        "**124** beitragende Anrisse",
        _summary_of_result(at),
    ]


def test_experten_modus_summary_follows_the_experten_modus_curves():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    production = _summary(at)[-1]
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    at.sidebar.slider(key="_expert_p_h_mean").set_value(0.2).run()
    assert_no_exception(at)
    assert _summary(at)[-1] == _summary_of_result(at)
    assert _summary(at)[-1] != production
    assert any("Experten-Modus aktiv" in w for w in texts(at.warning))


def test_pixel_in_a_finished_kachel_without_process_says_so():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL_NO_PROCESS)
    assert any(t.startswith("Kein simulierter Prozess erreicht Pixel") for t in texts(at.info))
    assert not at.get("vega_lite_chart")
    assert not _summary(at)


def test_pixel_outside_the_finished_kacheln_says_so():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL_OUTSIDE)
    assert any(t.startswith("Keine berechnete Kachel für Pixel") for t in texts(at.info))


def test_a_failed_ifk_computation_is_shown_and_logged(monkeypatch, caplog):
    from probe_core.derivate import ifk_and_raster

    def _fail(*_args, **_kwargs):
        raise RuntimeError("bucket-internal/key.parquet")

    monkeypatch.setattr(ifk_and_raster, "compute_ifk_default", _fail)
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    (error,) = texts(at.main.error)
    assert error.startswith("Die IFK-Berechnung ist fehlgeschlagen.")
    assert "bucket-internal" not in error
    assert "IFK computation failed for pixel" in caplog.text
    assert "bucket-internal/key.parquet" in caplog.text
    assert not _summary(at)


def test_deselect_removes_the_result_and_leaves_a_ghost_pixel():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    at.button(key="btn_pixel_abwaehlen").click().run()
    assert "_ifk_pending" not in at.session_state
    assert at.session_state["_ifk_deselected_pixel"] == IFK_PIXEL
    assert not at.get("vega_lite_chart")


def test_experten_modus_marks_the_curves():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    assert any("Experten-Modus aktiv" in w for w in texts(at.warning))
    assert labels(at.get("download_button")).count("📥 Wahrscheinlichkeiten/Raten") == 1


def test_experten_modus_p_h_sliders_move_each_other():
    at = new_app("IFK")
    at.session_state["_expert_active"] = True
    at.run()
    at.sidebar.slider(key="_expert_p_h_max").set_value(1.0).run()
    assert_no_exception(at)
    assert at.sidebar.slider(key="_expert_p_h_mean").value == 0.0
    at.sidebar.slider(key="_expert_p_h_mean").set_value(0.7).run()
    assert at.sidebar.slider(key="_expert_p_h_max").value == 0.3
    at.sidebar.button(key="_expert_p_h_reset_btn").click().run()
    assert at.sidebar.slider(key="_expert_p_h_mean").value == 0.8
    assert at.sidebar.slider(key="_expert_p_h_max").value == 0.2


def _series_of(chart):
    """The curve names a chart's layers are drawn as (none for a single curve)."""
    spec = json.loads(chart.proto.spec)
    return [layer["transform"][0]["calculate"] for layer in spec.get("layer", [])]


def test_experten_modus_keeps_the_original_curve_in_grey():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    assert all(_series_of(chart) == [] for chart in at.get("vega_lite_chart"))
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    at.sidebar.slider(key="_expert_p_h_mean").set_value(0.2).run()
    assert_no_exception(at)
    charts = at.get("vega_lite_chart")
    assert len(charts) == 3
    for chart in charts:
        assert _series_of(chart) == ['"Original"', '"Experten-Modus"']
    assert at.session_state["_ifk_result"]["original"] is at.session_state["_ifk_original"]


def test_experten_modus_without_an_original_still_shows_its_curve(monkeypatch):
    from probe_core.derivate import ifk_and_raster

    compute = ifk_and_raster.compute_ifk_default

    def _only_with_overrides(*args, **kwargs):
        if not kwargs:
            raise RuntimeError("production read failed")
        return compute(*args, **kwargs)

    at = new_app("IFK")
    at.session_state["_ifk_pending"] = IFK_PIXEL
    at.session_state["_expert_active"] = True
    monkeypatch.setattr(ifk_and_raster, "compute_ifk_default", _only_with_overrides)
    at.run()
    assert_no_exception(at)
    charts = at.get("vega_lite_chart")
    assert len(charts) == 3
    assert all(_series_of(chart) == [] for chart in charts)
    assert at.session_state["_ifk_result"]["original"] is None


_LINK = {"x": "2598501", "y": "1137504"}  # inside IFK_PIXEL, off its centre


def _open_link(query_params, **state):
    at = new_app("IFK")
    at.query_params.update(query_params)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_no_exception(at)
    return at


def test_a_link_selects_its_pixel_and_the_url_shows_the_pixel_centre():
    at = _open_link(_LINK)
    assert at.session_state["_ifk_pending"] == IFK_PIXEL
    assert len(at.get("vega_lite_chart")) == 3
    assert at.query_params == {"x": "2598502.5", "y": "1137502.5"}


def test_a_link_with_a_bad_pixel_says_so_and_selects_nothing():
    at = _open_link({"x": "2598501", "y": "north"})
    assert any("keinen gültigen Pixel" in w for w in texts(at.warning))
    assert "_ifk_pending" not in at.session_state
    assert not at.get("vega_lite_chart")


def test_deselecting_the_pixel_removes_it_from_the_url():
    at = _open_link(_LINK)
    at.button(key="btn_pixel_abwaehlen").click().run()
    assert_no_exception(at)
    assert "_ifk_pending" not in at.session_state
    assert at.query_params == {}


def test_the_url_keeps_french_when_the_pixel_changes(french_texts):
    at = _open_link({**_LINK, "lang": "fr"})
    assert at.query_params == {"x": "2598502.5", "y": "1137502.5", "lang": "fr"}
    at.button(key="btn_pixel_abwaehlen").click().run()
    assert_no_exception(at)
    assert at.query_params == {"lang": "fr"}
