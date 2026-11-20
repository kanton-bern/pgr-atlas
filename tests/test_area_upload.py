"""area_upload: an uploaded polygon becomes an LV95 selection."""

import math

from shapely.geometry import Polygon

import area_upload


def test_a_wgs84_polygon_is_reprojected_to_lv95():
    selection = area_upload.finalize_uploaded_polygon(
        Polygon([(7.44, 46.94), (7.45, 46.94), (7.45, 46.95), (7.44, 46.94)]), 4326
    )
    assert selection["type"] == "polygon"
    assert area_upload.ring_in_switzerland(selection["ring"])
    assert 2_590_000 < selection["ring"][0][0] < 2_610_000


def test_lv95_numbers_declared_as_wgs84_land_outside_switzerland():
    selection = area_upload.finalize_uploaded_polygon(
        Polygon([(2_600_000, 1_200_000), (2_600_100, 1_200_000), (2_600_100, 1_200_100)]), 4326
    )
    assert not area_upload.ring_in_switzerland(selection["ring"])


def _wiggly_circle(n_vertices):
    """A 500 m circle in LV95 whose vertices zigzag by 10 cm."""
    return Polygon(
        [
            (
                2_600_000 + 500 * math.cos(2 * math.pi * i / n_vertices) + (i % 2) * 0.1,
                1_200_000 + 500 * math.sin(2 * math.pi * i / n_vertices),
            )
            for i in range(n_vertices)
        ]
    )


def test_only_a_polygon_with_many_vertices_is_simplified():
    few, many = _wiggly_circle(400), _wiggly_circle(2000)
    assert len(area_upload.finalize_uploaded_polygon(few, 2056)["ring"]) == 401
    simplified = area_upload.finalize_uploaded_polygon(many, 2056)["ring"]
    assert len(simplified) < 2001
    assert Polygon(simplified).symmetric_difference(many).area < 0.01 * many.area
