"""Downloads of the Anriss view ("Derivate & Export"): file names and the
Rohdaten CSV's columns. Kept out of app.py so they can be tested without
Streamlit or S3 (tests/test_anriss_export.py)."""

import io
import json

import geopandas as gpd
import pandas as pd
from rasterio.io import MemoryFile

import ui_text
from raster_overlay import VARIABLE_UNITS

# Gold stores Fliesstiefe, Fliessgeschwindigkeit, d and h as integer cm and
# cm/s (probe-core's GOLD_SCHEMA_SIM_DUCKDB); cm is internal to gold only, so
# the CSV gets them in m and m/s like the map and the GeoTIFFs. Druck is kPa
# == kN/m² already.
_GOLD_CM_COLUMNS = ["Fliesstiefe", "Fliessgeschwindigkeit", "d", "h"]
_ROHDATEN_RENAME = {
    "Fliesstiefe": "Fliesstiefe [m]",
    "Fliessgeschwindigkeit": "Fliessgeschwindigkeit [m/s]",
    "Druck": "Druck [kN/m²]",
    "p_ablauf": "p_Ablauf",
    "lambda_ereignis": "lambda_Ereignis",
}

# The app's display columns (views/anriss.py's _gold_to_display_df: the same values in
# m, m/s, kN/m²) -- not exported, they duplicate the German columns above.
_DISPLAY_COLUMNS = ["depth", "velocity", "pressure"]

# (column, key of its meaning under anriss.rohdaten_meaning in texts.toml), in
# the CSV's column order -- shown as the "Datenmodell" table next to the
# download button. The column names are the export's and stay fixed (Q9). Only
# the three intensities carry a unit (in their header); the parameters keep
# their plain names.
ROHDATEN_COLUMNS = [
    ("id_prozessquelle", "id_prozessquelle"),
    ("id_anriss", "id_anriss"),
    ("x_anriss, y_anriss", "anriss_xy"),
    ("A", "a"),
    ("d", "d"),
    ("h", "h"),
    ("mu, xsi, tau0", "friction"),
    ("x, y", "pixel_xy"),
    ("Fliesstiefe [m]", "depth"),
    ("Fliessgeschwindigkeit [m/s]", "velocity"),
    ("Druck [kN/m²]", "pressure"),
    ("lambda_Hangmuren", "lambda_hangmuren"),
    ("p_raeumlich", "p_raeumlich"),
    ("p_A", "p_a"),
    ("p_h", "p_h"),
    ("p_Ablauf", "p_ablauf"),
    ("lambda_Ereignis", "lambda_ereignis"),
]


def simulation_file_stem(id_anriss, area, h, mu, xsi, tau0) -> str:
    """One scenario's download name, e.g.
    anriss_26452249_a55_h0_59m_mu0_05_xsi100_tau0_0 (h arrives in gold's cm).
    mu, xsi, tau0 are spelled like the CSV's columns."""
    number = ui_text.file_number
    return (
        f"anriss_{int(id_anriss)}_a{int(area)}_h{number(int(h) / 100)}m"
        f"_mu{number(mu)}_xsi{int(xsi)}_tau0_{int(tau0)}"
    )


def geotiff_file_name(stem: str, variable: str) -> str:
    """variable is 'depth'/'velocity'/'pressure', e.g. <stem>_fliesstiefe.tif;
    the unit is in the band's description."""
    return f"{stem}_{ui_text.FILE_VARIABLES[variable]}.tif"


def label_geotiff(tif_bytes: bytes, variable: str) -> bytes:
    """The same GeoTIFF with its unit written into it: band description
    "Fliesstiefe [m]" (what QGIS shows as the band name) and a units tag."""
    with MemoryFile(tif_bytes) as src_file, src_file.open() as src:
        data, profile, tags = src.read(), src.profile, src.tags()
    out = MemoryFile()
    with out.open(**profile) as dst:
        dst.write(data)
        dst.update_tags(**tags, units=VARIABLE_UNITS[variable])
        dst.update_tags(1, units=VARIABLE_UNITS[variable])
        label = ui_text.t(f"variable.{variable}", lang=ui_text.EXPORT_LANGUAGE)
        dst.set_band_description(1, f"{label} [{VARIABLE_UNITS[variable]}]")
    return out.read()


def rohdaten_file_name(id_anriss) -> str:
    """Every scenario of the anriss, so no parameter suffix."""
    return f"anriss_{int(id_anriss)}_rohdaten.csv"


def umhuellende_file_name(id_anriss, extension: str) -> str:
    """extension: 'gpkg' or 'geojson'."""
    return f"anriss_{int(id_anriss)}_umhuellende.{extension}"


def adhoc_umhuellende_file_name(id_anriss) -> str:
    return f"anriss_{int(id_anriss)}_umhuellende_adhoc.geojson"


def _umhuellende_feature(id_anriss, hull: dict) -> dict:
    """The precomputed Umhüllende (probe-core's get_anriss_hull_fragment) as
    one GeoJSON feature in WGS84: the envelope over every scenario of the
    Anriss. The bounding box in the properties is LV95 and spans the pixel
    CENTERS; the polygon follows the pixel edges, 2.5 m further out."""
    return {
        "type": "Feature",
        "geometry": hull["hull_geojson"],
        "properties": {
            "id_anriss": int(id_anriss),
            "id_prozessquelle": int(hull["id_prozessquelle"]),
            "xmin_lv95": float(hull["xmin"]),
            "ymin_lv95": float(hull["ymin"]),
            "xmax_lv95": float(hull["xmax"]),
            "ymax_lv95": float(hull["ymax"]),
        },
    }


def umhuellende_geojson_bytes(id_anriss, hull: dict) -> bytes:
    """The Umhüllende as a GeoJSON file in WGS84, as GeoJSON requires (RFC 7946)."""
    collection = {"type": "FeatureCollection", "features": [_umhuellende_feature(id_anriss, hull)]}
    return json.dumps(collection).encode("utf-8")


def umhuellende_geopackage_bytes(id_anriss, hull: dict) -> bytes:
    """The Umhüllende as a GeoPackage in LV95 (EPSG:2056), layer "umhuellende".

    The hull arrives in WGS84 (the map's copy) and is projected back here,
    which saves a second read of the hull fragment (14-20 s for the polygon
    column). WGS84 and back shifts every vertex by about 1 mm (measured:
    +0.6 mm east, +1.1 mm north across the canton). The hull's vertices are
    pixel edges, whole multiples of 5 m, so snapping to 1 cm restores them
    exactly."""
    wgs84 = gpd.GeoDataFrame.from_features([_umhuellende_feature(id_anriss, hull)], crs="EPSG:4326")
    lv95 = wgs84.to_crs("EPSG:2056")
    lv95.geometry = lv95.geometry.set_precision(0.01)
    file = io.BytesIO()
    lv95.to_file(file, driver="GPKG", layer="umhuellende")
    return file.getvalue()


def rohdaten_export_df(enriched: pd.DataFrame) -> pd.DataFrame:
    """enrich_with_probabilities(<display df>) -> the Rohdaten CSV's columns:
    the display duplicates dropped, gold's cm columns in m, units in the
    intensity headers,
    p_Ablauf/lambda_Ereignis spelled like the
    UI and lambda_Hangmuren."""
    out = enriched.drop(columns=_DISPLAY_COLUMNS, errors="ignore")
    cm_columns = [column for column in _GOLD_CM_COLUMNS if column in out.columns]
    out[cm_columns] = out[cm_columns] / 100.0
    return out.rename(columns=_ROHDATEN_RENAME)


def rohdaten_csv_bytes(enriched: pd.DataFrame) -> bytes:
    # utf-8-sig: Excel only reads the ² and ü in the headers right with a BOM.
    return rohdaten_export_df(enriched).to_csv(index=False).encode("utf-8-sig")
