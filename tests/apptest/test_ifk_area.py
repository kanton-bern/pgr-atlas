"""IFK-Berechnung for an area: a selected area (as the map or an upload would
set it), its job and its result."""

import pandas as pd
import pytest

from tests.apptest.conftest import labels, map_args, new_app, run_until, run_view, texts
from tests.lake_data import IFK_PIXEL, IFK_PIXEL_NO_PROCESS, RASTER_SELECTION, lv95_bbox

pytestmark = pytest.mark.apptest

# The one pixel IFK_PIXEL: a drawn rectangle's corners are pixel centres.
_ONE_PIXEL = {"type": "bbox", "ring": lv95_bbox(IFK_PIXEL, 0)}
# 20 km x 20 km: more kacheln than max_raster_kacheln() allows on any host.
_TOO_LARGE = {"type": "bbox", "ring": lv95_bbox(IFK_PIXEL, 10_000)}


def _submit(at):
    at.sidebar.button(key="_ifk_area_submit_btn").click().run()
    return at


def _finished(at) -> bool:
    return "_ifk_area_result" in at.session_state


def _area_result(selection):
    """The app after the area's job: its curves are computed on the same run."""
    at = _submit(run_view("IFK", _ifk_area_selection=selection))
    run_until(at, _finished)
    assert at.session_state["_ifk_area_result"]["error"] is None
    return at


def test_area_over_the_kachel_limit_is_refused():
    at = run_view("IFK", _ifk_area_selection=_TOO_LARGE)
    assert any("Zu gross" in e for e in texts(at.sidebar.error))
    assert at.sidebar.button(key="_ifk_area_submit_btn").disabled
    assert map_args(at)["area_too_large"] is True


def test_area_shows_three_curves_its_downloads_and_the_outline():
    at = _area_result(RASTER_SELECTION)
    assert len(at.get("vega_lite_chart")) == 3
    downloads = labels(at.get("download_button"))
    assert downloads.count("📥 Daten (CSV)") == 3
    assert downloads.count("📥 Bild (PNG)") == 3
    (rohdaten,) = at.get("link_button")
    assert rohdaten.proto.label.startswith("📥 Rohdaten (CSV) - alle ")
    assert "/file/" in rohdaten.proto.url
    args = map_args(at)
    assert args["selected_selection"] == RASTER_SELECTION
    assert args["anriss_outline_geojson"]["features"]
    assert args["anriss_circles_geojson"] is None


def test_the_rohdaten_file_has_a_row_per_simulation_with_its_maxima():
    at = _area_result(RASTER_SELECTION)
    rohdaten = at.session_state["_ifk_area_ifk"]["rohdaten"]
    rows = pd.read_csv(rohdaten["path"], encoding="utf-8-sig")
    assert len(rows) == rohdaten["n"] > 0
    assert {"Fliesstiefe max [m]", "Druck max [kN/m²]", "Anzahl Pixel", "lambda_Ereignis"} <= set(
        rows.columns
    )
    assert not rows.duplicated(["id_anriss", "A", "h", "mu", "xsi", "tau0"]).any()


def test_a_one_pixel_area_has_the_curves_of_that_pixel():
    area = _area_result(_ONE_PIXEL).session_state["_ifk_area_ifk"]["data"]["curves"]
    pixel = run_view("IFK", _ifk_pending=IFK_PIXEL).session_state["_ifk_result"]["data"]["curves"]
    for variable in ("depth", "velocity", "pressure"):
        pd.testing.assert_frame_equal(
            area[variable].reset_index(drop=True),
            pixel[variable].reset_index(drop=True),
            check_dtype=False,
        )


def test_area_without_process_says_so():
    at = _area_result({"type": "bbox", "ring": lv95_bbox(IFK_PIXEL_NO_PROCESS, 10)})
    assert "Kein simulierter Prozess erreicht das Gebiet." in texts(at.info)
    assert not at.get("vega_lite_chart")


def test_experten_modus_recomputes_from_the_kept_maxima_and_keeps_the_original():
    at = _area_result(RASTER_SELECTION)
    production = at.session_state["_ifk_area_ifk"]["data"]
    at.sidebar.toggle(key="_expert_active").set_value(True).run()
    at.sidebar.slider(key="_expert_p_h_max").set_value(1.0).run()
    result = at.session_state["_ifk_area_ifk"]
    assert any("Experten-Modus aktiv" in w for w in texts(at.warning))
    assert result["data"]["expert_mode"] and result["original"] is production
    assert "_ifk_area_job" not in at.session_state  # no second gold read
    assert labels(at.get("download_button")).count("📥 Wahrscheinlichkeiten/Raten") == 1


def test_a_picked_pixel_replaces_the_area():
    at = _area_result(RASTER_SELECTION)
    at.session_state["_ifk_pending"] = IFK_PIXEL
    at.session_state["_ifk_area_selection"] = None
    at.run()
    assert "_ifk_area_ifk" not in at.session_state
    assert map_args(at)["anriss_outline_geojson"] is None


def test_a_new_area_replaces_the_pixel():
    at = run_view("IFK", _ifk_pending=IFK_PIXEL)
    at.session_state["_ifk_area_selection"] = RASTER_SELECTION
    at.run()
    assert "_ifk_pending" not in at.session_state
    assert not at.get("vega_lite_chart")


def test_a_link_selects_its_rectangle_and_waits_for_the_button():
    at = new_app("IFK")
    at.query_params.update(
        {"xmin": "2598452", "ymin": "1137452", "xmax": "2598552", "ymax": "1137552"}
    )
    at.run()
    assert at.session_state["_ifk_area_selection"] == RASTER_SELECTION
    assert "_ifk_area_request" not in at.session_state
    assert map_args(at)["area_too_large"] is False
    assert at.query_params["xmin"] == "2598452.5"


def test_a_link_with_a_bad_rectangle_says_so_and_selects_nothing():
    at = new_app("IFK")
    at.query_params.update({"xmin": "2598452", "ymin": "1137452"})
    at.run()
    assert any(w.startswith("Der Link enthält kein gültiges Rechteck") for w in texts(at.warning))
    assert "_ifk_area_selection" not in at.session_state


def test_reset_removes_the_area_and_its_result():
    at = _area_result(RASTER_SELECTION)
    at.sidebar.button(key="ifk_area_reset_btn").click().run()
    for key in ("_ifk_area_request", "_ifk_area_result", "_ifk_area_ifk"):
        assert key not in at.session_state
    assert map_args(at)["selected_selection"] is None
    assert not at.get("vega_lite_chart")


def test_a_failed_area_job_is_shown_and_logged(monkeypatch, caplog):
    from probe_core.derivate import ifk_and_raster

    def _fail(*_args, **_kwargs):
        raise RuntimeError("bucket-internal/key.parquet")

    monkeypatch.setattr(ifk_and_raster, "build_area_event_maxima", _fail)
    # An area no other test computes, so its maxima aren't kept yet.
    at = _submit(
        run_view("IFK", _ifk_area_selection={"type": "bbox", "ring": lv95_bbox(IFK_PIXEL, 15)})
    )
    run_until(at, _finished)
    (error,) = texts(at.main.error)
    assert error.startswith("Die IFK-Berechnung ist fehlgeschlagen.")
    assert "bucket-internal" not in error
    assert "IFK area maxima failed (bbox" in caplog.text


def test_header_names_the_selected_area():
    at = run_view("IFK", _ifk_area_selection=_ONE_PIXEL)
    (header,) = [h for h in at.main.get("html") if 'class="pgr-page-title"' in h.proto.body]
    assert '<span class="pgr-chip">Gebiet: Rechteck</span>' in header.proto.body
