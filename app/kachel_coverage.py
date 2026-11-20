"""Is an LV95 pixel inside a finalized gold kachel?

Tested against the same WGS84 coverage GeoJSON the maps draw as
"Berechnete Kacheln" (ui_common.load_coverage), so the answer always
matches the tiles the user sees. Lives outside app.py so it can be tested
(app.py runs Streamlit code at import).
"""

from pyproj import Transformer
from shapely.geometry import Point, shape

_LV95_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)


def pixel_in_coverage(coverage_geojson: dict, e: float, n: float) -> bool:
    """True if the pixel at LV95 (e, n) lies in one of the coverage squares.

    Args:
        coverage_geojson: a WGS84 FeatureCollection of finalized kacheln.
        e: LV95 easting of the pixel centre.
        n: LV95 northing of the pixel centre.
    """
    point = Point(*_LV95_TO_WGS84.transform(e, n))
    return any(shape(f["geometry"]).covers(point) for f in coverage_geojson["features"])
