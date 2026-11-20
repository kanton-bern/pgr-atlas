"""Gebäudeschatten view: rows (one per simulation and pixel) -> one status per
pixel, and the colours the map gets."""

import colorsys
from types import SimpleNamespace

import pandas as pd

import gebaeudeschatten_view as gv
import ui_text
from probe_core import gebaeudeschatten as gs
from raster_utils import MASK_COLORS


def _rows(*rows):
    """(x, y, Fliesstiefe, own_building_mask, reason) per row, reason for the
    surrounding variant at 1 cm; every other column is left counting."""
    df = pd.DataFrame(
        rows,
        columns=[
            "x",
            "y",
            "Fliesstiefe",
            "own_building_mask",
            gs.reason_column("shadowing_building_surrounding", 1),
        ],
    )
    for variant in gs.VARIANTS:
        for min_depth_cm in gs.MIN_DEPTHS_CM:
            df[gs.reason_column(variant, min_depth_cm)] = df.get(
                gs.reason_column(variant, min_depth_cm)
            )
    return df


def test_a_pixel_counts_if_any_of_its_simulations_counts():
    pixel_status = gv._pixel_status(
        _rows(
            (2.5, 2.5, 0, 0, gs.REASON_BELOW_MIN_DEPTH),
            (2.5, 2.5, 12, 0, None),
        ),
        "shadowing_building_surrounding",
        1,
    )
    row = pixel_status.iloc[0]
    assert (row.counts, row.depth, row.n_sims, row.reason) == (True, 12, 2, None)


def test_a_structural_reason_explains_the_pixel_before_the_depth_one():
    pixel_status = gv._pixel_status(
        _rows(
            (7.5, 2.5, 0, 2, gs.REASON_BELOW_MIN_DEPTH),
            (7.5, 2.5, 30, 2, gs.REASON_OWN_NEIGHBOR),
        ),
        "shadowing_building_surrounding",
        1,
    )
    assert not pixel_status.iloc[0].counts
    assert pixel_status.iloc[0].reason == gs.REASON_OWN_NEIGHBOR


def test_colours_follow_mask_then_status():
    pixel_status = gv._pixel_status(
        _rows(
            (2.5, 2.5, 40, 1, gs.REASON_OWN_BUILDING),
            (7.5, 2.5, 40, 2, gs.REASON_OWN_NEIGHBOR),
            (12.5, 2.5, 20, 0, None),
            (17.5, 2.5, 0, 0, gs.REASON_BELOW_MIN_DEPTH),
        ),
        "shadowing_building_surrounding",
        1,
    )
    cells = gv._building_cells(pixel_status, 1).set_index("x")
    assert cells.loc[2.5, "color"] == gv.OWN_COLOR
    assert cells.loc[7.5, "color"] == gv.RING_COLOR
    assert cells.loc[12.5, "color"] == gv.SHADOW_COLOR
    assert cells.loc[17.5, "color"] == gv.EXCLUDED_COLOR
    assert "zählt als abgeschattet" in cells.loc[12.5, "tooltip"]
    assert "Fliesstiefe unter 0.01 m" in cells.loc[17.5, "tooltip"]


def test_every_probe_core_value_has_a_label():
    # The view builds the text keys from probe_core's values; a new one without a text raises.
    assert all(gv._variant_label(v) for v in gs.VARIANTS)
    assert all(gv._reach_label(r) for r in gs.REACHES_M)
    assert all(gv._reason_label(r, 10) for r in gs.REASONS)
    assert gv._reason_label(gs.REASON_BELOW_MIN_DEPTH, 10) == "Fliesstiefe unter 0.10 m"


def test_a_reason_in_a_download_stays_german(french_session):
    assert gv._reason_label(gs.REASON_BELOW_MIN_DEPTH, 10).startswith("[FR] ")
    german = gv._reason_label(gs.REASON_BELOW_MIN_DEPTH, 10, lang=ui_text.EXPORT_LANGUAGE)
    assert german == "Fliesstiefe unter 0.10 m"


def test_a_simulation_label_follows_the_session_language_and_its_tag_stays_german(
    french_session,
):
    row = SimpleNamespace(A=400, h=50, mu=0.025, xsi=100, tau0=0)
    assert gv._sim_label(row) == "A=400 m², h=[FR] 0,50 m, μ=0,025, ξ=100, τ₀=0"
    tag = gv._sim_label(row, lang=ui_text.EXPORT_LANGUAGE)
    assert tag == "A=400 m², h=0.50 m, μ=0.025, ξ=100, τ₀=0"


def test_pixel_table_is_shown_in_the_session_language_and_downloaded_in_german(french_session):
    p_bld = pd.DataFrame(
        {
            "id_start": [7, 8],
            "depth": [42, 3],
            "n_sims": [2, 1],
            "counts": [True, False],
            "reason": [None, gs.REASON_BELOW_MIN_DEPTH],
        }
    )
    shown = gv._pixel_table(p_bld, 10)
    assert all(column.startswith("[FR] ") for column in shown.columns)
    csv = gv._pixel_table(p_bld, 10, lang=ui_text.EXPORT_LANGUAGE)
    assert csv.to_dict("list") == {
        "Gebäude": [7, 8],
        "Fliesstiefe max [m]": [0.42, 0.03],
        "Simulationen": [2, 1],
        "zählt": ["ja", "nein"],
        "Grund": ["", "Fliesstiefe unter 0.10 m"],
    }


def _hue_degrees(rgb):
    return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0] * 360


def test_selection_shadow_differs_in_hue_from_the_canton_mask():
    # The selection's shadow sits on the canton's "Im Schatten" mask; a
    # darker lilac read as the same layer.
    shadow = tuple(int(gv.SHADOW_COLOR[i : i + 2], 16) for i in (1, 3, 5))
    mask = MASK_COLORS["purple"]
    diff = abs(_hue_degrees(shadow) - _hue_degrees(mask))
    assert min(diff, 360 - diff) >= 30


def test_cells_are_closed_5_m_squares():
    pixel_status = gv._pixel_status(
        _rows((2600002.5, 1200002.5, 20, 0, None)), "shadowing_building_surrounding", 1
    )
    (feature,) = gv._cells_geojson(gv._building_cells(pixel_status, 1))["features"]
    ring = feature["geometry"]["coordinates"][0]
    assert len(ring) == 5 and ring[0] == ring[-1]
    assert feature["properties"]["fillColor"] == gv.SHADOW_COLOR


def test_a_failed_availability_check_hides_the_view_and_is_logged(monkeypatch, caplog):
    def _fail():
        raise RuntimeError("bucket-internal/gebaeudeschatten")

    monkeypatch.setattr(gs, "is_available", _fail)
    gv.is_available.clear()
    try:
        assert gv.is_available() is False
    finally:
        gv.is_available.clear()
    assert "Gebäudeschatten availability check failed" in caplog.text
    assert "bucket-internal/gebaeudeschatten" in caplog.text


def _session(monkeypatch, **state):
    session = SimpleNamespace(**{"gs_building": None, "gs_pixel": None, "gs_focus": None} | state)
    monkeypatch.setattr(gv.st, "session_state", session)
    return session


def test_a_pixel_replaces_the_building(monkeypatch):
    session = _session(monkeypatch, gs_building=17681)
    gv._select_pixel(2600002.5, 1200002.5)
    assert (session.gs_building, session.gs_pixel) == (None, (2600002.5, 1200002.5))


def test_a_building_replaces_the_pixel(monkeypatch):
    session = _session(monkeypatch)
    session.gs_pixel = (2600002.5, 1200002.5)
    gv._select_building(17681)
    assert (session.gs_building, session.gs_pixel) == (17681, None)
