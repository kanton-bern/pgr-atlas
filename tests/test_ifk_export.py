import io

import pandas as pd
import pytest

import ifk_export

# The downloads stay German in a French session (Q9): every test below runs in one.
pytestmark = pytest.mark.usefixtures("french_session")


def test_file_names_cut_pixel_centers_down():
    assert (
        ifk_export.curve_file_stem("depth", 2600007.5, 1200002.5, False)
        == "ifk_fliesstiefe_2600007_1200002"
    )
    assert (
        ifk_export.curve_file_stem("pressure", 2600002.5, 1200002.5, True)
        == "ifk_druck_2600002_1200002_expertenmodus"
    )
    assert (
        ifk_export.rohdaten_file_name(2600007.5, 1200007.5, False)
        == "ifk_rohdaten_2600007_1200007.csv"
    )
    assert (
        ifk_export.wahrscheinlichkeiten_file_name(2600007.5, 1200007.5)
        == "ifk_wahrscheinlichkeiten_2600007_1200007_expertenmodus.json"
    )


def _read(b):
    return pd.read_csv(io.StringIO(b.decode("utf-8-sig")))


def test_curve_csv_names_intensity_with_unit():
    curve = pd.DataFrame(
        {"intensity": [0.1, 0.5], "p_exceedance": [1e-3, 1e-4], "return_period": [1e3, 1e4]}
    )
    out = _read(ifk_export.curve_csv_bytes(curve, "velocity"))
    assert list(out.columns) == [
        "Fliessgeschwindigkeit [m/s]",
        "lambda_Überschreitung",
        "Wiederkehrperiode [Jahre]",
    ]
    assert out["Fliessgeschwindigkeit [m/s]"].tolist() == [0.1, 0.5]


def test_curve_csv_adds_the_original_curve_per_intensity():
    curve = pd.DataFrame(
        {"intensity": [0.1, 0.5], "p_exceedance": [2e-3, 2e-4], "return_period": [5e2, 5e3]}
    )
    original = pd.DataFrame(
        {"intensity": [0.5, 0.1], "p_exceedance": [1e-4, 1e-3], "return_period": [1e4, 1e3]}
    )
    out = _read(ifk_export.curve_csv_bytes(curve, "depth", original))
    assert list(out.columns) == [
        "Fliesstiefe [m]",
        "lambda_Überschreitung",
        "Wiederkehrperiode [Jahre]",
        "lambda_Überschreitung_original",
        "Wiederkehrperiode_original [Jahre]",
    ]
    assert out["Fliesstiefe [m]"].tolist() == [0.1, 0.5]
    assert out["lambda_Überschreitung"].tolist() == [2e-3, 2e-4]
    assert out["lambda_Überschreitung_original"].tolist() == [1e-3, 1e-4]


def test_rohdaten_csv_renames_intensities_and_rates():
    events = pd.DataFrame(
        [
            {
                "id_anriss": 1,
                "p_ablauf": 0.01,
                "depth": 0.42,
                "velocity": 1.2,
                "pressure": 3.0,
                "lambda_ereignis": 8e-5,
            }
        ]
    )
    out = _read(ifk_export.rohdaten_csv_bytes(events))
    assert list(out.columns) == [
        "id_anriss",
        "p_Ablauf",
        "Fliesstiefe [m]",
        "Fliessgeschwindigkeit [m/s]",
        "Druck [kN/m²]",
        "lambda_Ereignis",
    ]


def test_area_rohdaten_names_the_maxima_with_units():
    assert ifk_export.area_rohdaten_column_names() == {
        "depth": "Fliesstiefe max [m]",
        "velocity": "Fliessgeschwindigkeit max [m/s]",
        "pressure": "Druck max [kN/m²]",
        "pixel_count": "Anzahl Pixel",
        "p_ablauf": "p_Ablauf",
        "lambda_ereignis": "lambda_Ereignis",
    }
