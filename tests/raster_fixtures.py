"""Tiny LV95 GeoTIFFs written by the tests themselves."""

import numpy as np
import rasterio
from affine import Affine

ORIGIN = (2_600_000.0, 1_200_000.0)  # LV95 north-west corner
RES = 5.0


def write_geotiff(path, arr: np.ndarray, nodata=None):
    """Writes arr (row 0 = north) as a single-band LV95 GeoTIFF with 5 m pixels."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=arr.dtype,
        crs="EPSG:2056",
        nodata=nodata,
        transform=Affine(RES, 0, ORIGIN[0], 0, -RES, ORIGIN[1]),
    ) as dst:
        dst.write(arr, 1)
    return path
