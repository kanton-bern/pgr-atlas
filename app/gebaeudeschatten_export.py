"""Downloads of the Gebäudeschatten view: the selected building's pixels as a
GeoTIFF (what the map shows), its rows (one per simulation and pixel, which no
raster can hold) and the selected pixel's buildings as CSV. (The canton mask is served, and named, by
derivate_bbox_server's /canton route.) Kept out of
gebaeudeschatten_view so they can be tested without Streamlit or S3
(tests/test_gebaeudeschatten_export.py).

Gold stores Fliesstiefe, Fliessgeschwindigkeit and h as integer cm and cm/s;
the CSVs give them in m and m/s like everything else the user sees. Druck
is kPa == kN/m² already."""

import numpy as np
import pandas as pd
from rasterio.crs import CRS
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

import ui_text

RESOLUTION_M = 5.0  # gold's pixel grid (probe_core.gebaeudeschatten.RESOLUTION_M)

# Gold column -> CSV header, in the CSV's column order.
_BUILDING_COLUMNS = {
    "id_start": "Gebaeude",
    "A": "A [m²]",
    "h": "h [m]",
    "mu": "mu",
    "xsi": "xsi",
    "tau0": "tau0",
    "x": "x",
    "y": "y",
    "Fliesstiefe": "Fliesstiefe [m]",
    "Fliessgeschwindigkeit": "Fliessgeschwindigkeit [m/s]",
    "Druck": "Druck [kN/m²]",
}
_CM_COLUMNS = ["h", "Fliesstiefe", "Fliessgeschwindigkeit"]


def building_export_df(rows: pd.DataFrame, reason_column: str, reason_label) -> pd.DataFrame:
    """gs.building_rows (one row per simulation and pixel) -> the CSV: units
    in m, the pixel's mask as text, and whether the row counts under the
    chosen variant and minimum depth (reason_column), with reason_label(reason)
    saying why not."""
    out = rows[list(_BUILDING_COLUMNS)].copy()
    out[_CM_COLUMNS] = out[_CM_COLUMNS] / 100.0
    out = out.rename(columns=_BUILDING_COLUMNS)
    mask = rows["own_building_mask"]
    lang = ui_text.EXPORT_LANGUAGE
    mask_labels = {
        1: ui_text.t("gs.own_pixel", lang=lang),
        2: ui_text.t("gs.ring_pixel", lang=lang),
    }
    out[ui_text.GS_CSV_MASK] = mask.to_numpy()
    out[ui_text.GS_CSV_MASK_MEANING] = (
        mask.map(mask_labels).fillna(ui_text.GS_CSV_MASK_NONE).to_numpy()
    )
    reason = rows[reason_column]
    yes_no = {True: ui_text.t("gs.yes", lang=lang), False: ui_text.t("gs.no", lang=lang)}
    out[ui_text.t("gs.col_counts", lang=lang)] = reason.isna().map(yes_no).to_numpy()
    out[ui_text.t("gs.col_reason", lang=lang)] = [
        reason_label(excluded) if isinstance(excluded, str) else "" for excluded in reason
    ]
    return out


def building_geotiff_bytes(pixels: pd.DataFrame, tags: dict) -> bytes:
    """gebaeudeschatten_view._pixel_status (one row per pixel: x, y, depth in
    cm, n_sims, mask, counts) -> a 4-band float32 GeoTIFF (LV95, 5 m) over the
    pixels' bounding box, NaN outside them: the mask (0/1/2), whether the pixel
    counts as shadowed (1/0), the max Fliesstiefe [m] and the number of
    simulations. tags (the view's settings) go into the file's metadata."""
    # Pixel centres sit half a pixel inside the edges the GeoTIFF is placed by.
    half_pixel = RESOLUTION_M / 2
    xmin, ymax = pixels["x"].min() - half_pixel, pixels["y"].max() + half_pixel
    width = int(round((pixels["x"].max() + half_pixel - xmin) / RESOLUTION_M))
    height = int(round((ymax - (pixels["y"].min() - half_pixel)) / RESOLUTION_M))
    columns = np.floor((pixels["x"].to_numpy() - xmin) / RESOLUTION_M).astype(int)
    rows = np.floor((ymax - pixels["y"].to_numpy()) / RESOLUTION_M).astype(int)
    bands = [
        (ui_text.GS_TIF_BAND_MASK, pixels["mask"]),
        (ui_text.GS_TIF_BAND_COUNTS, pixels["counts"].astype(float)),
        (ui_text.GS_TIF_BAND_DEPTH, pixels["depth"] / 100.0),
        (ui_text.GS_TIF_BAND_SIMS, pixels["n_sims"]),
    ]
    data = np.full((len(bands), height, width), np.nan, dtype=np.float32)
    for band_index, (_, values) in enumerate(bands):
        data[band_index, rows, columns] = values.to_numpy(dtype=np.float32)
    out = MemoryFile()
    with out.open(
        driver="GTiff",
        height=height,
        width=width,
        count=len(bands),
        dtype="float32",
        crs=CRS.from_epsg(2056),
        transform=from_origin(xmin, ymax, RESOLUTION_M, RESOLUTION_M),
        nodata=np.nan,
        compress="deflate",
    ) as tif:
        tif.write(data)
        tif.update_tags(**{name: str(value) for name, value in tags.items()})
        for band_number, (description, _) in enumerate(bands, start=1):
            tif.set_band_description(band_number, description)
    return out.read()


def csv_bytes(df: pd.DataFrame) -> bytes:
    # utf-8-sig: Excel only reads the ² and ä in the headers right with a BOM.
    return df.to_csv(index=False).encode("utf-8-sig")


def building_file_name(id_start: int, reach_m: int, variant: str, min_depth_cm: int) -> str:
    return f"gebaeudeschatten_gebaeude_{int(id_start)}_{settings_slug(reach_m, variant, min_depth_cm)}.csv"


def building_geotiff_name(id_start: int, reach_m: int, variant: str, min_depth_cm: int) -> str:
    return f"gebaeudeschatten_gebaeude_{int(id_start)}_{settings_slug(reach_m, variant, min_depth_cm)}.tif"


def pixel_file_name(e: float, n: float, reach_m: int, variant: str, min_depth_cm: int) -> str:
    """Pixel centres are cut down to whole metres, like the IFK names."""
    return (
        f"gebaeudeschatten_pixel_{int(e)}_{int(n)}"
        f"_{settings_slug(reach_m, variant, min_depth_cm)}.csv"
    )


def settings_slug(reach_m: int, variant: str, min_depth_cm: int) -> str:
    """e.g. 'reichweite_50m_ohne_eigenes_gebaeude_ab_0_01m' (depth in m, as the
    user sees it)."""
    return (
        f"reichweite_{int(reach_m)}m_{ui_text.FILE_GS_VARIANTS.get(variant, variant)}"
        f"_ab_{ui_text.file_number(int(min_depth_cm) / 100)}m"
    )
