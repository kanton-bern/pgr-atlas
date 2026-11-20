import io
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from rasterio.io import MemoryFile
from shapely.geometry import box
from probe_core.derivate.event_export import event_layer_geotiff_bytes

import anriss_export

# The downloads stay German in a French session (Q9): every test below runs in one.
pytestmark = pytest.mark.usefixtures("french_session")


def test_simulation_file_names():
    stem = anriss_export.simulation_file_stem(26452249, 55, 59, 0.05, 100, 0)
    assert stem == "anriss_26452249_a55_h0_59m_mu0_05_xsi100_tau0_0"
    assert anriss_export.geotiff_file_name(stem, "depth") == stem + "_fliesstiefe.tif"
    assert anriss_export.geotiff_file_name(stem, "velocity") == stem + "_fliessgeschwindigkeit.tif"
    assert anriss_export.geotiff_file_name(stem, "pressure") == stem + "_druck.tif"
    assert anriss_export.rohdaten_file_name(26452249) == "anriss_26452249_rohdaten.csv"


def test_mu_from_a_decimal_column_prints_short():
    assert "_mu0_3_" in anriss_export.simulation_file_stem(
        1, 55, 59, float(pd.Series([0.3]).iloc[0]), 100, 0
    )


def _enriched():
    # enrich_with_probabilities(views/anriss.py's _gold_to_display_df(gold)) for one row
    return pd.DataFrame(
        [
            {
                "id_prozessquelle": 7,
                "id_anriss": 1,
                "x_anriss": 2600000.0,
                "y_anriss": 1200000.0,
                "A": 55,
                "d": 59,
                "h": 59,
                "mu": 0.05,
                "xsi": 100,
                "tau0": 0,
                "x": 2600002.5,
                "y": 1200002.5,
                "Fliesstiefe": 42,
                "Fliessgeschwindigkeit": 120,
                "Druck": 3,
                "depth": 0.42,
                "velocity": 1.2,
                "pressure": 3.0,
                "lambda_Hangmuren": 0.1,
                "p_raeumlich": 0.5,
                "p_A": 0.2,
                "p_h": 0.8,
                "p_ablauf": 0.01,
                "lambda_ereignis": 8e-5,
            }
        ]
    )


def test_rohdaten_keeps_german_columns_with_units():
    out = anriss_export.rohdaten_export_df(_enriched())
    for gone in ("depth", "velocity", "pressure", "Fliesstiefe", "p_ablauf", "lambda_ereignis"):
        assert gone not in out.columns
    assert out["Fliesstiefe [m]"].iloc[0] == 0.42
    assert out["Fliessgeschwindigkeit [m/s]"].iloc[0] == 1.2
    assert out["h"].iloc[0] == 0.59 and out["d"].iloc[0] == 0.59
    assert out["Druck [kN/m²]"].iloc[0] == 3
    assert out["p_Ablauf"].iloc[0] == 0.01
    assert out["lambda_Ereignis"].iloc[0] == 8e-5


def test_column_docs_match_the_csv():
    out = anriss_export.rohdaten_export_df(_enriched())
    documented = [
        c.strip() for names, _ in anriss_export.ROHDATEN_COLUMNS for c in names.split(",")
    ]
    assert documented == list(out.columns)


def test_csv_has_bom_for_excel():
    assert anriss_export.rohdaten_csv_bytes(_enriched()).startswith(b"\xef\xbb\xbf")


def test_geotiff_carries_its_unit():
    df = pd.DataFrame(
        {"x": [2600002.5, 2600007.5], "y": [1200002.5, 1200002.5], "depth": [0.42, 1.5]}
    )
    out = anriss_export.label_geotiff(event_layer_geotiff_bytes(df, "depth"), "depth")
    with MemoryFile(out) as f, f.open() as src:
        assert src.descriptions == ("Fliesstiefe [m]",)
        assert src.tags()["units"] == "m" and src.tags(1)["units"] == "m"
        assert src.crs.to_epsg() == 2056
        np.testing.assert_allclose(src.read(1).ravel(), [0.42, 1.5], rtol=1e-6)


# A 100 x 50 m rectangle near Bern, as the app holds it: polygon in WGS84, bbox in LV95.
_HULL_LV95 = box(2600000.0, 1200000.0, 2600100.0, 1200050.0)
_HULL = {
    "id_prozessquelle": np.int16(12),
    "xmin": 2600000.0,
    "xmax": 2600100.0,
    "ymin": 1200000.0,
    "ymax": 1200050.0,
    "hull_geojson": json.loads(
        gpd.GeoSeries([_HULL_LV95], crs="EPSG:2056").to_crs("EPSG:4326").to_json()
    )["features"][0]["geometry"],
}
_HULL_PROPERTIES = {
    "id_anriss": 26452249,
    "id_prozessquelle": 12,
    "xmin_lv95": 2600000.0,
    "ymin_lv95": 1200000.0,
    "xmax_lv95": 2600100.0,
    "ymax_lv95": 1200050.0,
}


def test_umhuellende_geojson_is_one_wgs84_feature_with_the_anriss_ids():
    collection = json.loads(anriss_export.umhuellende_geojson_bytes(26452249, _HULL))
    (feature,) = collection["features"]
    assert collection["type"] == "FeatureCollection"
    assert feature["geometry"] == _HULL["hull_geojson"]
    assert feature["properties"] == _HULL_PROPERTIES


def test_umhuellende_geopackage_is_the_same_polygon_back_in_lv95():
    geopackage = anriss_export.umhuellende_geopackage_bytes(26452249, _HULL)
    layer = gpd.read_file(io.BytesIO(geopackage), layer="umhuellende")
    assert layer.crs.to_epsg() == 2056
    assert len(layer) == 1
    assert layer.iloc[0][list(_HULL_PROPERTIES)].to_dict() == _HULL_PROPERTIES
    # WGS84 and back is ~1 mm off; the 1 cm snap restores the pixel-edge coordinates exactly
    assert layer.geometry.iloc[0].equals(_HULL_LV95)


def test_umhuellende_file_names_tell_precomputed_from_adhoc():
    assert anriss_export.umhuellende_file_name(7, "gpkg") == "anriss_7_umhuellende.gpkg"
    assert anriss_export.umhuellende_file_name(7, "geojson") == "anriss_7_umhuellende.geojson"
    assert anriss_export.adhoc_umhuellende_file_name(7) == "anriss_7_umhuellende_adhoc.geojson"
