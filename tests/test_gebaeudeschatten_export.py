"""Gebäudeschatten downloads: the building CSV's columns and units, and the
file names."""

import numpy as np
import pandas as pd
import pytest
from rasterio.io import MemoryFile

import gebaeudeschatten_export as ge

# The downloads stay German in a French session (Q9): every test below runs in one.
pytestmark = pytest.mark.usefixtures("french_session")


def _rows():
    return pd.DataFrame(
        {
            "id_start": [7, 7],
            "A": [28, 28],
            "h": [50, 50],
            "mu": [0.025, 0.025],
            "xsi": [100, 100],
            "tau0": [0, 0],
            "x": [2600002.5, 2600007.5],
            "y": [1200002.5, 1200002.5],
            "Fliesstiefe": [3, 42],
            "Fliessgeschwindigkeit": [216, 120],
            "Druck": [5, 3],
            "own_building_mask": [2, 0],
            "in_own1_ring": [True, False],
            "reason_x": ["own_neighbor", None],
        }
    )


def test_building_csv_is_in_m_and_says_whether_each_row_counts():
    out = ge.building_export_df(_rows(), "reason_x", lambda r: f"label {r}")
    assert list(out.columns) == [
        "Gebaeude",
        "A [m²]",
        "h [m]",
        "mu",
        "xsi",
        "tau0",
        "x",
        "y",
        "Fliesstiefe [m]",
        "Fliessgeschwindigkeit [m/s]",
        "Druck [kN/m²]",
        "Maske",
        "Maske (Bedeutung)",
        "zählt",
        "Grund",
    ]
    assert out["h [m]"].tolist() == [0.5, 0.5]
    assert out["Fliesstiefe [m]"].tolist() == [0.03, 0.42]
    assert out["Fliessgeschwindigkeit [m/s]"].tolist() == [2.16, 1.2]
    assert out["Druck [kN/m²]"].tolist() == [5, 3]
    assert out["Maske"].tolist() == [2, 0]
    assert out["Maske (Bedeutung)"].tolist() == [
        "Nachbarpixel (Maske 2)",
        "übriger Pixel (Maske 0)",
    ]
    assert out["zählt"].tolist() == ["nein", "ja"]
    assert out["Grund"].tolist() == ["label own_neighbor", ""]


def test_csv_has_bom_for_excel():
    assert ge.csv_bytes(pd.DataFrame({"a": [1]})).startswith(b"\xef\xbb\xbf")


def test_file_names_carry_the_settings_in_m():
    assert ge.building_file_name(17681, 50, "raw", 10) == (
        "gebaeudeschatten_gebaeude_17681_reichweite_50m_roh_ab_0_1m.csv"
    )
    assert ge.pixel_file_name(2600002.5, 1200002.5, 800, "raw", 1) == (
        "gebaeudeschatten_pixel_2600002_1200002_reichweite_800m_roh_ab_0_01m.csv"
    )


def test_building_geotiff_puts_each_pixel_in_its_cell():
    pixels = pd.DataFrame(
        {
            "x": [2600002.5, 2600012.5],
            "y": [1200002.5, 1200007.5],
            "depth": [42, 3],
            "n_sims": [2, 1],
            "mask": [1, 0],
            "counts": [False, True],
        }
    )
    tif = ge.building_geotiff_bytes(pixels, {"Gebaeude": 7, "Variante": "raw"})
    with MemoryFile(tif) as f, f.open() as src:
        assert src.crs.to_epsg() == 2056 and src.res == (5.0, 5.0) and src.count == 4
        assert (src.width, src.height) == (3, 2)
        assert src.bounds == (2600000.0, 1200000.0, 2600015.0, 1200010.0)
        assert src.descriptions[2] == "Fliesstiefe max [m]"
        assert src.tags()["Variante"] == "raw"
        data = src.read()
    # Row 0 is the northern one (y 1200007.5), row 1 the southern (y 1200002.5).
    np.testing.assert_allclose(data[:, 1, 0], [1, 0, 0.42, 2], rtol=1e-6)
    np.testing.assert_allclose(data[:, 0, 2], [0, 1, 0.03, 1], rtol=1e-6)
    assert np.isnan(data[:, 0, 0]).all() and np.isnan(data[:, 1, 1]).all()
