"""IFK of an area: its link, its file names, the Anriss outline and the BOM of
its Rohdaten CSV."""

import pandas as pd
import pytest
from shapely.geometry import Point, shape

import ifk_export
from tests.lake_data import IFK_PIXEL, IFK_PIXEL_OUTSIDE, RASTER_SELECTION, lv95_bbox
from views import ifk_area

_LINK = {"xmin": "2598452.5", "ymin": "1137452.5", "xmax": "2598552.5", "ymax": "1137552.5"}
_POLYGON = {"type": "polygon", "ring": RASTER_SELECTION["ring"]}


def test_a_link_gives_the_rectangle_snapped_to_pixel_centres():
    link = {"xmin": "2598451", "ymin": "1137454.9", "xmax": "2598553", "ymax": "1137550.1"}
    assert ifk_area.area_from_query(link) == RASTER_SELECTION


def test_a_link_without_a_rectangle_gives_none():
    assert ifk_area.area_from_query({}) is None
    assert ifk_area.area_from_query({"x": "2598502.5", "y": "1137502.5"}) is None


@pytest.mark.parametrize(
    "params",
    [
        {k: v for k, v in _LINK.items() if k != "ymax"},
        {**_LINK, "xmin": "west"},
        {**_LINK, "xmin": "nan"},
        {**_LINK, "xmin": _LINK["xmax"], "xmax": _LINK["xmin"]},  # inside out
        {**_LINK, "xmax": str(IFK_PIXEL_OUTSIDE[0]), "ymax": str(IFK_PIXEL_OUTSIDE[1])},
    ],
)
def test_a_bad_rectangle_link_raises(params):
    with pytest.raises(ValueError):
        ifk_area.area_from_query(params)


def test_a_rectangle_written_to_a_link_reads_back():
    assert ifk_area.area_query(RASTER_SELECTION) == _LINK
    assert ifk_area.area_from_query(_LINK) == RASTER_SELECTION


def test_a_polygon_and_an_area_outside_the_canton_give_no_link():
    assert ifk_area.area_query(_POLYGON) is None
    assert ifk_area.area_query({"type": "bbox", "ring": lv95_bbox(IFK_PIXEL_OUTSIDE, 50)}) is None
    assert ifk_area.area_query(None) is None


def test_file_names_carry_the_areas_rectangle():
    assert ifk_export.area_slug(_POLYGON) == "2598452_1137452_2598552_1137552"
    assert (
        ifk_export.area_curve_file_stem("depth", RASTER_SELECTION, False)
        == "ifk_gebiet_fliesstiefe_2598452_1137452_2598552_1137552"
    )
    assert (
        ifk_export.area_rohdaten_file_name(RASTER_SELECTION, True, "parquet")
        == "ifk_gebiet_rohdaten_2598452_1137452_2598552_1137552_expertenmodus.parquet"
    )
    assert (
        ifk_export.area_wahrscheinlichkeiten_file_name(RASTER_SELECTION)
        == "ifk_gebiet_wahrscheinlichkeiten_2598452_1137452_2598552_1137552_expertenmodus.json"
    )


def _anriss_events(rows):
    return pd.DataFrame(
        rows, columns=["id_anriss", "x", "y", "anrissflaeche", "lambda_ereignis_sum"]
    )


def test_the_outline_is_one_shape_around_the_contributing_anrisse():
    e, n = IFK_PIXEL
    # Two overlapping circles (radius ~5.6 m, 5 m apart), one far away, and
    # one that contributes nothing.
    events = _anriss_events(
        [
            (1, e, n, 100, 1e-9),
            (2, e + 5, n, 100, 2e-9),
            (3, e + 500, n, 100, 1e-9),
            (4, e, n + 500, 100, 0.0),
        ]  # fmt: skip
    )
    (feature,) = ifk_area.anriss_outline_geojson(events)["features"]
    outline = shape(feature["geometry"])
    assert len(outline.geoms) == 2
    assert 7.4 < outline.centroid.x < 7.5 and 46.3 < outline.centroid.y < 46.4  # WGS84
    assert not outline.contains(Point(outline.geoms[0].centroid.x, outline.centroid.y + 0.004))


def test_no_contributing_anriss_gives_no_outline():
    assert ifk_area.anriss_outline_geojson(_anriss_events([(1, *IFK_PIXEL, 100, 0.0)])) is None
    assert ifk_area.anriss_outline_geojson(_anriss_events([])) is None


def test_the_rohdaten_csv_gets_a_bom_in_front(tmp_path):
    path = tmp_path / "rohdaten_abc.csv"
    path.write_bytes("Druck max [kN/m²]\n12\n".encode())
    ifk_area._prepend_bom(path)
    assert path.read_bytes() == b"\xef\xbb\xbf" + "Druck max [kN/m²]\n12\n".encode()
    assert list(tmp_path.iterdir()) == [path]
