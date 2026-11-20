"""Gebäudeschatten view: a building's pixels and a pixel's buildings, against
the full-canton copy in the test bucket."""

import pytest

from tests.apptest.conftest import map_args, nav_links, run_view
from tests.lake_data import GEBAEUDESCHATTEN_BUILDING, GEBAEUDESCHATTEN_PIXEL

pytestmark = pytest.mark.apptest

VIEW = "Gebäudeschatten"


def test_nav_link_appears_when_the_bucket_has_the_data():
    at = run_view("Overview (All Events)")
    assert nav_links(at)["Gebäudeschatten"] == VIEW


def test_building_shows_its_own_ring_and_shadow_pixels():
    at = run_view(VIEW, gs_reach=800, gs_building=GEBAEUDESCHATTEN_BUILDING)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Simulationen": "2", "Gebäudepixel": "4", "Nachbarpixel": "13"}
    args = map_args(at)
    assert len(args["cells_geojson"]["features"]) == 571
    assert args["mask"]["partition"] == "shadowing_building_surrounding_800_1"


@pytest.mark.parametrize("min_depth", [1, 10])
def test_mask_partition_and_label_name_the_minimum_depth(min_depth):
    at = run_view(VIEW, gs_reach=800, gs_min_depth=min_depth, gs_building=GEBAEUDESCHATTEN_BUILDING)
    mask = map_args(at)["mask"]
    assert mask["partition"] == f"shadowing_building_surrounding_800_{min_depth}"
    assert mask["label"].endswith(f"ab {min_depth / 100:.2f} m")


def test_pixel_lists_every_building_reaching_it():
    at = run_view(VIEW, gs_reach=800, gs_pixel=GEBAEUDESCHATTEN_PIXEL)
    (table,) = at.dataframe
    assert sorted(table.value["Gebäude"]) == [17681, 17689, 17776, 17780, 17801]
    assert set(table.value["zählt"]) == {"ja"}


def test_default_reach_is_50_m_and_25_m_is_offered():
    at = run_view(VIEW)
    reach = at.sidebar.radio(key="gs_reach")
    assert reach.value == 50
    assert list(reach.options)[0] == "25 m"


def test_default_minimum_depth_is_1_cm_and_10_cm_is_offered():
    at = run_view(VIEW)
    min_depth = at.sidebar.radio(key="gs_min_depth")
    assert min_depth.value == 1
    assert list(min_depth.options) == ["0.01 m", "0.10 m"]


def test_building_offers_its_csv_and_the_mask():
    at = run_view(VIEW, gs_reach=800, gs_building=GEBAEUDESCHATTEN_BUILDING)
    assert [b.proto.label for b in at.get("download_button")] == [
        "📥 Pixel des Gebäudes herunterladen (GeoTIFF)",
        "📥 Rohdaten des Gebäudes herunterladen (CSV)",
    ]
    (mask,) = at.sidebar.get("link_button")
    assert mask.proto.url.endswith(
        "/canton/gebaeudeschatten_affected_mask.tif?partition=shadowing_building_surrounding_800_1"
    )


def test_pixel_shows_only_the_pixel_and_offers_its_table():
    at = run_view(VIEW, gs_reach=800, gs_pixel=GEBAEUDESCHATTEN_PIXEL)
    assert not at.metric, "no building details next to the pixel"
    (csv,) = at.get("download_button")
    assert csv.proto.label == "📥 Tabelle herunterladen (CSV)"
