"""The Gebäudeschatten map (app/gebaeudeschatten_map): the affected-mask crop,
the layer box with the cells' colour key, outline overlays, the focus on a
sidebar selection, and what a click sends back.

The buildings tileset answers 404 here (conftest), so building hover and
clicks are covered by the unit tests of frontend/src/gebaeudeschatten_map/."""

import base64
import json

import pytest
from playwright.sync_api import expect
from pyproj import Transformer

pytestmark = pytest.mark.components

_BOUNDS = [[46.600, 7.600], [46.610, 7.615]]
_TO_LV95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
# 1x1 transparent PNG: the mask only has to be a loadable image.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_CORNERS = [[7.60, 46.61], [7.615, 46.61], [7.615, 46.60], [7.60, 46.60]]
_KEY = [
    {"color": "#1b9e77", "label": "zählt"},
    {"color": "#bdbdbd", "label": "zählt nicht"},
    {"color": "#d95f02", "label": "ausserhalb"},
]


def _square(lon, lat, size_deg=0.0005, **props):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [lon, lat],
                    [lon + size_deg, lat],
                    [lon + size_deg, lat + size_deg],
                    [lon, lat + size_deg],
                    [lon, lat],
                ]
            ],
        },
    }


def _feature_collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


_CELLS = _feature_collection(
    _square(
        7.6070,
        46.6045,
        fillColor="#1b9e77",
        fillOpacity=0.8,
        tooltip="Pixel 2612345 / 1178901\nFliesstiefe 0.42 m",
    )
)
_FOOTPRINT = {
    "id": "b_foot",
    "label": "Gewähltes Gebäude (Simulationsstart)",
    "geojson": _feature_collection(_square(7.605, 46.605)),
    "color": "#263238",
    "width": 2,
    "dash": None,
    "fill": "#37474f",
    "visible": True,
}
_PIXEL = {
    "id": "p_pixel",
    "label": "Gewählter Pixel",
    "geojson": _feature_collection(_square(7.608, 46.606, 0.0001)),
    "color": "#e377c2",
    "width": 3.5,
    "dash": None,
    "fill": None,
    "visible": True,
}


class _FakeMaskServer:
    """Answers /bbox.png like derivate_bbox_server.py; `status` other than 200 fails."""

    def __init__(self, page):
        self.crops = []
        self.status = 200
        page.route("**/bbox.png?*", self._crop)

    def _crop(self, route):
        self.crops.append(route.request.url)
        if self.status != 200:
            route.fulfill(status=self.status)
            return
        route.fulfill(
            body=_PNG, content_type="image/png", headers={"X-Corners": json.dumps(_CORNERS)}
        )


def _open(page, open_component, component_server):
    mask_server = _FakeMaskServer(page)
    mask = {
        "metric": "gebaeudeschatten",
        "partition": "strict_100_10",
        "label": "Im Schatten (Kanton): streng, 100 m, ab 0.10 m",
        "server_port": component_server,
        "path_prefix": "",
    }

    def args(**overrides):
        base = dict(
            bounds=_BOUNDS,
            buildings_pmtiles="buildings.pmtiles",
            buildings_layer="buildings",
            mask=mask,
            cells_geojson=_CELLS,
            cells_version="v1",
            cells_label="Pixel der gewählten Gebäude",
            cells_legend=_KEY,
            overlays=[_FOOTPRINT, _PIXEL],
            focus=None,
        )
        return base | overrides

    comp = open_component("gebaeudeschatten_map", **args())
    comp.page.wait_for_function("!!window.__testMap.getLayer('mask-image')")
    comp.mask_server = mask_server
    comp.args = args
    comp.mask = mask
    return comp


@pytest.fixture()
def gebaeudeschatten(page, open_component, component_server):
    comp = _open(page, open_component, component_server)
    yield comp
    assert comp.cdn_requests == []
    assert comp.errors == []


def _wait_until(page, condition, what):
    for _ in range(50):
        if condition():
            return
        page.wait_for_timeout(100)
    raise AssertionError(f"timed out waiting for {what}")


def _layer_ids(comp):
    return comp.page.evaluate("window.__testMap.getStyle().layers.map(l => l.id)")


def test_layer_box_lists_mask_buildings_cells_and_overlays(gebaeudeschatten):
    rows = gebaeudeschatten.page.locator("#layer-rows .legend-row:visible")
    expect(rows).to_have_text(
        [
            "Im Schatten (Kanton): streng, 100 m, ab 0.10 m",
            "Gebäude (Simulationsstart)",
            "Pixel der gewählten Gebäude",
            "Gewähltes Gebäude (Simulationsstart)",
            "Gewählter Pixel",
        ]
    )


def test_cells_key_sits_below_the_cells_row(gebaeudeschatten):
    key = gebaeudeschatten.page.locator("#row-cells + #cells-legend .cl-row")
    expect(key).to_have_text(["zählt", "zählt nicht", "ausserhalb"])

    gebaeudeschatten.render(**gebaeudeschatten.args(cells_geojson=None, cells_version="v2"))
    expect(gebaeudeschatten.page.locator("#row-cells")).to_be_hidden()
    expect(gebaeudeschatten.page.locator("#cells-legend")).to_be_hidden()


def test_mask_crop_is_drawn_below_the_buildings(gebaeudeschatten):
    url = gebaeudeschatten.mask_server.crops[-1]
    assert (
        "metric=gebaeudeschatten&partition=strict_100_10&band=1&scale=mask&mask_color=purple" in url
    )
    layers = _layer_ids(gebaeudeschatten)
    assert layers.index("mask-image") < layers.index("buildings-fill")


def test_mask_refetches_on_new_settings_only(gebaeudeschatten):
    gebaeudeschatten.page.wait_for_timeout(500)  # past the move debounce
    before = len(gebaeudeschatten.mask_server.crops)
    gebaeudeschatten.render(**gebaeudeschatten.args())
    gebaeudeschatten.page.wait_for_timeout(600)
    assert len(gebaeudeschatten.mask_server.crops) == before

    gebaeudeschatten.render(
        **gebaeudeschatten.args(mask={**gebaeudeschatten.mask, "partition": "strict_50_10"})
    )
    _wait_until(
        gebaeudeschatten.page,
        lambda: "partition=strict_50_10" in gebaeudeschatten.mask_server.crops[-1],
        "the new crop",
    )


def test_unticked_mask_is_removed_and_not_fetched(gebaeudeschatten):
    page = gebaeudeschatten.page
    page.locator("#row-mask input").uncheck()
    page.evaluate("window.__testMap.panBy([40, 0])")
    page.wait_for_function("!window.__testMap.getLayer('mask-image')")
    before = len(gebaeudeschatten.mask_server.crops)
    page.evaluate("window.__testMap.panBy([40, 0])")
    page.wait_for_timeout(600)
    assert len(gebaeudeschatten.mask_server.crops) == before

    page.locator("#row-mask input").check()
    page.wait_for_function("!!window.__testMap.getLayer('mask-image')")


def test_mask_opacity_slider_and_an_unticked_mask_stays_off_with_new_settings(gebaeudeschatten):
    page = gebaeudeschatten.page
    opacity = "window.__testMap.getPaintProperty('mask-image', 'raster-opacity')"
    slider = page.locator("#row-mask-opacity input")
    expect(slider).to_have_value("45")
    expect(slider).to_have_attribute(
        "aria-label", "Im Schatten (Kanton): streng, 100 m, ab 0.10 m: Deckkraft"
    )
    assert page.evaluate(opacity) == 0.45
    slider.fill("70")
    assert page.evaluate(opacity) == 0.7

    # Unticked, then another reach: the mask stays off and nothing is fetched.
    page.locator("#row-mask input").uncheck()
    expect(slider).to_be_disabled()
    page.wait_for_timeout(500)  # past the move debounce
    before = len(gebaeudeschatten.mask_server.crops)
    gebaeudeschatten.render(
        **gebaeudeschatten.args(mask={**gebaeudeschatten.mask, "partition": "strict_50_10"})
    )
    page.wait_for_function("!window.__testMap.getLayer('mask-image')")
    page.wait_for_timeout(600)
    expect(page.locator("#row-mask input")).not_to_be_checked()
    assert len(gebaeudeschatten.mask_server.crops) == before

    # Ticked again: the new settings' crop, at 70 %.
    page.locator("#row-mask input").check()
    _wait_until(
        page,
        lambda: "partition=strict_50_10" in gebaeudeschatten.mask_server.crops[-1],
        "the new crop",
    )
    page.wait_for_function("!!window.__testMap.getLayer('mask-image')")
    assert gebaeudeschatten.layer_visibility("mask-image") == "visible"
    assert page.evaluate(opacity) == 0.7


def test_mask_without_data_here_is_removed_quietly(gebaeudeschatten):
    gebaeudeschatten.mask_server.status = 404
    gebaeudeschatten.page.evaluate("window.__testMap.panBy([40, 0])")
    gebaeudeschatten.page.wait_for_function("!window.__testMap.getLayer('mask-image')")
    expect(gebaeudeschatten.page.locator("#map-status")).not_to_have_text(
        "Betroffenheitsmaske konnte nicht geladen werden."
    )


def test_failed_mask_says_so_and_the_next_crop_clears_it(gebaeudeschatten):
    status = gebaeudeschatten.page.locator("#map-status")
    gebaeudeschatten.mask_server.status = 500
    gebaeudeschatten.page.evaluate("window.__testMap.panBy([40, 0])")
    expect(status).to_have_text("Betroffenheitsmaske konnte nicht geladen werden.")
    assert gebaeudeschatten.page.evaluate("!window.__testMap.getLayer('mask-image')")

    gebaeudeschatten.mask_server.status = 200
    gebaeudeschatten.page.evaluate("window.__testMap.panBy([40, 0])")
    gebaeudeschatten.page.wait_for_function("!!window.__testMap.getLayer('mask-image')")
    expect(status).to_have_text("")


def test_no_mask_hides_its_row(gebaeudeschatten):
    gebaeudeschatten.render(**gebaeudeschatten.args(mask=None))
    expect(gebaeudeschatten.page.locator("#row-mask")).to_be_hidden()
    gebaeudeschatten.page.wait_for_function("!window.__testMap.getLayer('mask-image')")


def test_overlay_fill_and_a_dropped_overlay(gebaeudeschatten):
    page = gebaeudeschatten.page
    assert "ov-b_foot-fill" in _layer_ids(gebaeudeschatten)
    page.locator("#row-b_foot input").uncheck()
    assert gebaeudeschatten.layer_visibility("ov-b_foot") == "none"
    assert gebaeudeschatten.layer_visibility("ov-b_foot-fill") == "none"

    gebaeudeschatten.render(**gebaeudeschatten.args(overlays=[_FOOTPRINT]))
    expect(page.locator("#row-p_pixel")).to_be_hidden()
    page.wait_for_function(
        "window.__testMap.getSource('ov-p_pixel').serialize().data.features.length === 0"
    )


def test_overlay_colour_is_not_parsed_as_html(gebaeudeschatten):
    # The swatch colour goes through the CSSOM, not into innerHTML.
    bad = {**_PIXEL, "id": "bad", "label": "<b>x</b>", "color": 'red"><img src=x>'}
    gebaeudeschatten.render(**gebaeudeschatten.args(overlays=[_FOOTPRINT, _PIXEL, bad]))
    expect(gebaeudeschatten.page.locator("#row-bad")).to_have_text("<b>x</b>")
    expect(gebaeudeschatten.page.locator("#layer-rows img, #layer-rows b")).to_have_count(0)


def test_cell_hover_shows_its_tooltip(gebaeudeschatten):
    page = gebaeudeschatten.page
    page.wait_for_function(
        "window.__testMap.queryRenderedFeatures({layers: ['cells-fill']}).length > 0"
    )
    point = page.evaluate(
        "(() => { const p = window.__testMap.project([7.60725, 46.60475]); return [p.x, p.y]; })()"
    )
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + point[0], box["y"] + point[1])
    expect(page.locator(".cell-tooltip")).to_have_text(
        "Pixel 2612345 / 1178901\nFliesstiefe 0.42 m"
    )


def test_new_focus_frames_its_bounds_once(gebaeudeschatten):
    page = gebaeudeschatten.page
    focus = {"bounds": [[46.6040, 7.6060], [46.6050, 7.6075]], "nonce": 1.5}
    gebaeudeschatten.render(**gebaeudeschatten.args(focus=focus))
    page.wait_for_function("window.__testMap.getZoom() > 16", timeout=10_000)
    page.wait_for_function("!window.__testMap.isMoving()")
    page.evaluate("window.__testMap.jumpTo({center: [7.62, 46.62]})")

    gebaeudeschatten.render(**gebaeudeschatten.args(focus=focus))
    page.wait_for_timeout(300)
    assert page.evaluate("window.__testMap.getCenter().toArray()") == pytest.approx(
        [7.62, 46.62], abs=1e-6
    )


@pytest.mark.parametrize("shift", [False, True])
def test_click_sends_the_pixel_centre(gebaeudeschatten, shift):
    page = gebaeudeschatten.page
    box = page.locator("#map").bounding_box()
    x, y = box["width"] / 2, box["height"] / 2
    lon, lat = page.evaluate(f"window.__testMap.unproject([{x}, {y}]).toArray()")
    page.locator("#map canvas").click(
        position={"x": x, "y": y}, modifiers=["Shift"] if shift else []
    )
    page.wait_for_function("window.__componentValues.length === 1")
    value = gebaeudeschatten.values()[-1]
    east, north = _TO_LV95.transform(lon, lat)
    assert value["type"] == "pixel"
    assert value["e"] == pytest.approx(5 * round((east - 2.5) / 5) + 2.5, abs=0.01)
    assert value["n"] == pytest.approx(5 * round((north - 2.5) / 5) + 2.5, abs=0.01)
    assert isinstance(value["nonce"], float)
