"""MAXI derivate: per-event GeoTIFF/envelope export for pgr-atlas.

Pure geometry/raster computation over an already-fetched gold DataFrame — no
data access lives here. data_lake/data_interface.py (S3-backed,
GoldNotReadyError-gated) fetches the raw rows; app.py hands the resulting
DataFrame to the functions below to turn it into bytes/GeoJSON for the UI.
No probabilities are used here: gold carries none (they are joined at query
time, see ifk_and_raster.py).
"""

import io
import json
import os
import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio import features
from rasterio.transform import from_origin
from shapely.geometry import shape

PIXEL_SIZE = 5
CRS_LV95 = "EPSG:2056"
# Envelope cache (one GeoJSON per event). PROBE_CACHE_DIR overrides the
# location (pgr-atlas's image and stages set it). Created on first write, not
# on import -- importing this module has no side effects.
CACHE_DIR = Path(os.getenv("PROBE_CACHE_DIR") or "~/.cache/probe-core").expanduser()


def event_layer_geotiff_bytes(df: pd.DataFrame, col: str) -> bytes:
    """In-memory GeoTIFF (LV95) of one value column of an event simulation df."""
    resolution = PIXEL_SIZE
    xmin, xmax = df["x"].min() - resolution / 2, df["x"].max() + resolution / 2
    ymin, ymax = df["y"].min() - resolution / 2, df["y"].max() + resolution / 2
    width, height = int((xmax - xmin) / resolution), int((ymax - ymin) / resolution)
    grid = np.full((height, width), np.nan, dtype=np.float32)
    column_index = ((df["x"].to_numpy() - xmin) / resolution).astype(int)
    row_index = ((ymax - df["y"].to_numpy()) / resolution).astype(int)
    inside = (column_index >= 0) & (column_index < width) & (row_index >= 0) & (row_index < height)
    grid[row_index[inside], column_index[inside]] = df[col].to_numpy()[inside]

    buffer = io.BytesIO()
    with rasterio.open(
        buffer,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs=CRS_LV95,
        transform=from_origin(xmin, ymax, resolution, resolution),
        compress="lzw",
        tiled=True,
    ) as dst:
        dst.write(grid, 1)
    return buffer.getvalue()


def export_event_envelope_geojson(df: pd.DataFrame, id_anriss: int):
    """Envelope of every simulated scenario of one event, built from
    data_interface.get_anriss_all_scenarios_gold_data's raw rows.
    Returns (geojson_dict_wgs84, cache_path) — GeoJSON is WGS84 for web maps,
    the cached file on disk stays LV95. Returns (None, None) if df is empty."""
    cache_path = CACHE_DIR / f"event_{id_anriss}_envelope.geojson"
    if cache_path.exists():
        cached_envelope = gpd.read_file(str(cache_path))
        return json.loads(cached_envelope.to_crs("EPSG:4326").to_json()), str(cache_path)

    if df.empty:
        return None, None
    pixels = df[["x", "y"]].drop_duplicates()

    x_min, x_max = pixels["x"].min(), pixels["x"].max()
    y_min, y_max = pixels["y"].min(), pixels["y"].max()

    west = x_min - (PIXEL_SIZE / 2)
    north = y_max + (PIXEL_SIZE / 2)

    width = int(round((x_max - x_min) / PIXEL_SIZE)) + 1
    height = int(round((y_max - y_min) / PIXEL_SIZE)) + 1

    grid = np.zeros((height, width), dtype=np.uint8)
    column_index = ((pixels["x"] - x_min) / PIXEL_SIZE).round().astype(int)
    row_index = ((y_max - pixels["y"]) / PIXEL_SIZE).round().astype(int)
    grid[row_index, column_index] = 1

    transform = from_origin(west, north, PIXEL_SIZE, PIXEL_SIZE)
    shapes = features.shapes(grid, transform=transform)
    polygons = [shape(geometry) for geometry, value in shapes if value == 1]

    if not polygons:
        return None, None

    envelope_geom = gpd.GeoSeries(polygons, crs=CRS_LV95).union_all()
    envelope_gdf_lv95 = gpd.GeoDataFrame(
        {"id_anriss": [id_anriss]}, geometry=[envelope_geom], crs=CRS_LV95
    )

    # Atomic: an interrupted write must not leave a truncated file at
    # cache_path, whose mere existence is trusted above. The temp name is
    # unique per call, not per process: Streamlit serves every browser
    # session as a thread of ONE process, and several pods can share the
    # cache volume. Concurrent writers of the same event produce identical
    # content, so whichever os.replace comes last simply wins; a reader
    # always sees either no file or a complete one.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    unfinished_path = cache_path.with_name(f".{cache_path.name}.{uuid.uuid4().hex}.tmp")
    envelope_gdf_lv95.to_file(str(unfinished_path), driver="GeoJSON")
    os.replace(unfinished_path, cache_path)
    geojson_data = json.loads(envelope_gdf_lv95.to_crs("EPSG:4326").to_json())
    return geojson_data, str(cache_path)
