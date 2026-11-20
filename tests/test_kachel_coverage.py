import json
import unittest

import geopandas as gpd
from shapely.geometry import box

from kachel_coverage import pixel_in_coverage

KACHEL_E, KACHEL_N = 2598000, 1135000  # kachel 25981135 (audit M17)


def _coverage(*corners):
    """WGS84 GeoJSON of 1 km LV95 squares, built like probe-core's
    load_kachel_coverage and ui_common.load_coverage."""
    squares = gpd.GeoDataFrame(
        {"region": [f"Kachel {e // 1000}{n // 1000}" for e, n in corners]},
        geometry=[box(e, n, e + 1000, n + 1000) for e, n in corners],
        crs="EPSG:2056",
    )
    return json.loads(squares.to_crs("EPSG:4326").to_json())


class PixelInCoverageTest(unittest.TestCase):
    def test_pixel_inside_a_finalized_kachel(self):
        coverage = _coverage((KACHEL_E, KACHEL_N))

        self.assertTrue(pixel_in_coverage(coverage, KACHEL_E + 502.5, KACHEL_N + 502.5))

    def test_edge_pixels_of_the_kachel_are_inside(self):
        coverage = _coverage((KACHEL_E, KACHEL_N))

        for e, n in ((KACHEL_E + 2.5, KACHEL_N + 2.5), (KACHEL_E + 997.5, KACHEL_N + 997.5)):
            with self.subTest(e=e, n=n):
                self.assertTrue(pixel_in_coverage(coverage, e, n))

    def test_pixel_just_outside_the_kachel(self):
        coverage = _coverage((KACHEL_E, KACHEL_N))

        for e, n in ((KACHEL_E - 2.5, KACHEL_N + 502.5), (KACHEL_E + 502.5, KACHEL_N + 1002.5)):
            with self.subTest(e=e, n=n):
                self.assertFalse(pixel_in_coverage(coverage, e, n))

    def test_pixel_in_any_of_several_kacheln(self):
        coverage = _coverage((KACHEL_E, KACHEL_N), (2607000, 1137000))

        self.assertTrue(pixel_in_coverage(coverage, 2607502.5, 1137502.5))

    def test_empty_coverage(self):
        self.assertFalse(pixel_in_coverage(_coverage(), KACHEL_E + 502.5, KACHEL_N + 502.5))
