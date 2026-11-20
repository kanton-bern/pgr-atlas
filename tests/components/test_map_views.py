"""View-specific interactions: area-class legend filters (Simulierte Ereignisse, IFK),
the IFK anriss colour legend, Raster-Karten's draw/clear buttons, variable
switch, raster legend and hover value, and the Raster-Derivate preview
against a fake crop server."""

import base64
import json
import math
import re
import struct
from unittest.mock import ANY

import pytest
from playwright.sync_api import expect
from pyproj import Transformer

from .conftest import COVERAGE_VERSION

pytestmark = pytest.mark.components

# 1x1 transparent PNG -- the overlay only has to be a loadable image.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
_CORNERS = [[7.44, 46.96], [7.46, 46.96], [7.46, 46.94], [7.44, 46.94]]
_JOB_ID = "test-job"
_JOB_PORT = 28599  # any port: _FakeJobServer answers every host
_TO_LV95 = Transformer.from_crs("EPSG:4326", "EPSG:2056", always_xy=True)
# 2x2 hover grids, row-major from the top left, as derivate_bbox_server.py's
# .f32 route sends them. No grid for pressure: its .f32 answers 404.
_GRIDS = {"depth": (1.5, math.nan, 2.0, 3.25), "velocity": (0.0, 0.0, 0.0, 0.5)}


def _overlay(var, label, unit, job_id=_JOB_ID, hover=None):
    return {
        "job_id": job_id,
        "var": var,
        "corners": _CORNERS,
        "gradient": "#000, #fff",
        "label": label,
        "unit": unit,
        "log_scale": False,
        "vmin_label": "0",
        "vmid_label": "1",
        "vmax_label": "2",
        "hover": hover,
    }


# ── Simulierte Ereignisse ────────────────────────────────────────────────────


def test_overview_area_rows_filter_circles(open_component):
    comp = open_component("overview", coverage_version=COVERAGE_VERSION)
    boxes = comp.page.locator("#area-rows input[type=checkbox]")
    expect(boxes).to_have_count(6)
    for i in range(6):
        expect(boxes.nth(i)).to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')") is None

    boxes.first.uncheck()
    shown = comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')")[2][1]
    assert 55 not in shown and 1100 in shown

    # Clicking the label text toggles too.
    comp.page.locator("#area-rows .legend-row").first.locator("span").click()
    expect(boxes.first).to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')") is None


def test_overview_all_and_none_tick_every_area_class(open_component):
    comp = open_component("overview", coverage_version=COVERAGE_VERSION)
    boxes = comp.page.locator("#area-rows input[type=checkbox]")
    none = comp.page.get_by_role("button", name="Alle Grössenklassen ausblenden")
    expect(none).to_have_text("Keine")

    none.click()
    for i in range(6):
        expect(boxes.nth(i)).not_to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')") == [
        "==",
        ["get", "A"],
        -1,
    ]

    # By keyboard, like any button.
    every = comp.page.get_by_role("button", name="Alle Grössenklassen anzeigen")
    expect(every).to_have_text("Alle")
    every.focus()
    comp.page.keyboard.press("Enter")
    for i in range(6):
        expect(boxes.nth(i)).to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')") is None
    assert comp.errors == []


def test_overview_mounts_with_no_area_class_for_an_empty_list(open_component):
    # "Keine", then an opened Anriss and back: Python sends [] and it stays none.
    comp = open_component("overview", coverage_version=COVERAGE_VERSION, initial_active_areas=[])
    boxes = comp.page.locator("#area-rows input[type=checkbox]")
    for i in range(6):
        expect(boxes.nth(i)).not_to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anrisse-circles-fill')") == [
        "==",
        ["get", "A"],
        -1,
    ]


def test_overview_outlines_fade_in_only_at_detail_scale(open_component):
    # At canton scale the 1 px black outlines merged into a black mass.
    comp = open_component("overview", coverage_version=COVERAGE_VERSION)
    paint = comp.page.evaluate(
        "() => ['line-opacity', 'line-width'].map("
        "p => window.__testMap.getPaintProperty('anrisse-circles-outline', p))"
    )
    zoom = ["interpolate", ["linear"], ["zoom"]]
    assert paint == [[*zoom, 13, 0, 15, 0.8], [*zoom, 13, 0.5, 15, 1]]


_HIGHLIGHT_LAYERS = ("anrisse-circles-highlight-halo", "anrisse-circles-highlight")
_NO_HIGHLIGHT = ["boolean", False]


def _highlight_filters(page):
    return [page.evaluate(f"window.__testMap.getFilter('{layer}')") for layer in _HIGHLIGHT_LAYERS]


def _rerun_overview(comp, highlight_id_anriss):
    comp.render(
        center_lat=46.8,
        center_lon=7.5,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        highlight_id_anriss=highlight_id_anriss,
    )


def _wait_for_highlight(page, expected):
    page.wait_for_function(
        "([layer, want]) => JSON.stringify(window.__testMap.getFilter(layer)) === want",
        arg=[_HIGHLIGHT_LAYERS[1], json.dumps(expected, separators=(",", ":"))],
    )
    assert _highlight_filters(page) == [expected, expected]


def test_overview_highlight_follows_a_rerun(open_component):
    # A rerun with another highlight_id_anriss moves the ring without a remount.
    comp = open_component("overview", coverage_version=COVERAGE_VERSION, highlight_id_anriss=1)
    assert _highlight_filters(comp.page) == [["==", ["get", "id_anriss"], 1]] * 2

    _rerun_overview(comp, 2)
    _wait_for_highlight(comp.page, ["==", ["get", "id_anriss"], 2])
    assert comp.errors == []


def test_overview_highlight_clears_and_returns(open_component):
    comp = open_component("overview", coverage_version=COVERAGE_VERSION, highlight_id_anriss=1)

    _rerun_overview(comp, None)
    _wait_for_highlight(comp.page, _NO_HIGHLIGHT)

    _rerun_overview(comp, 3)
    _wait_for_highlight(comp.page, ["==", ["get", "id_anriss"], 3])
    assert comp.errors == []


def test_overview_without_highlight_draws_no_ring(open_component):
    comp = open_component("overview", coverage_version=COVERAGE_VERSION)
    assert _highlight_filters(comp.page) == [_NO_HIGHLIGHT] * 2


# ── IFK ──────────────────────────────────────────────────────────────────────


def test_ifk_anriss_legend_hidden_until_payload_then_collapsible(open_component):
    comp = open_component("overview_ifk", coverage_version=COVERAGE_VERSION)
    anriss_legend = comp.page.locator("#anriss-legend")
    expect(anriss_legend).to_be_hidden()

    comp.render(
        center_lat=46.8,
        center_lon=7.5,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        anriss_circles_geojson={"type": "FeatureCollection", "features": []},
        anriss_legend={
            "gradient": "#ff0, #f00",
            "vmin_label": "1e-4",
            "vmid_label": "1e-3",
            "vmax_label": "1e-2",
        },
    )
    expect(anriss_legend).to_be_visible()
    expect(comp.page.locator("#al-max")).to_have_text("1e-2")

    anriss_legend.locator(".legend-close").click()
    expect(comp.page.locator("#al-max")).to_be_hidden()
    expect(comp.page.locator("#legend")).to_be_visible()

    # Stays collapsed across a rerun that sends the legend again; the chip reopens it.
    comp.render(
        center_lat=46.8,
        center_lon=7.5,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        anriss_circles_geojson={"type": "FeatureCollection", "features": []},
        anriss_legend={
            "gradient": "#ff0, #f00",
            "vmin_label": "1e-4",
            "vmid_label": "1e-3",
            "vmax_label": "1e-2",
        },
    )
    expect(comp.page.locator("#al-max")).to_be_hidden()
    anriss_legend.locator(".legend-open").click()
    expect(comp.page.locator("#al-max")).to_have_text("1e-2")


def test_ifk_pixel_popup_prefetches_and_names_its_client(open_component):
    comp = open_component(
        "overview_ifk", coverage_version=COVERAGE_VERSION, selected_pixel=[2600002.5, 1200002.5]
    )  # mounts at zoom 18
    page = comp.page
    posted = []

    def capture(route):
        posted.append(route.request)
        route.fulfill(status=202)

    page.route("**/prefetch-ifk?*", capture)

    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    button = page.locator(".popup-open-btn", has_text="IFK berechnen")
    expect(button).to_be_visible()
    page.wait_for_timeout(300)
    assert len(posted) == 1 and posted[0].method == "POST"
    query = dict(p.split("=") for p in posted[0].url.split("?")[1].split("&"))
    assert (float(query["x"]) - 2.5) % 5 == 0 and (float(query["y"]) - 2.5) % 5 == 0

    button.click()
    page.wait_for_function("window.__componentValues.length === 1")
    value = comp.values()[-1]
    assert value["prefetch_client"] == query["client"]
    assert (value["x"], value["y"]) == (float(query["x"]), float(query["y"]))
    assert comp.errors == []


def test_ifk_area_checkboxes_filter_circles(open_component):
    comp = open_component("overview_ifk", coverage_version=COVERAGE_VERSION)
    boxes = comp.page.locator("#anriss-area-rows input[type=checkbox]")
    expect(boxes).to_have_count(6)

    for i in range(6):
        boxes.nth(i).uncheck()
    # All classes off -> a filter that matches nothing.
    assert comp.page.evaluate("window.__testMap.getFilter('anriss-circles-fill')") == [
        "==",
        ["get", "anrissflaeche"],
        -1,
    ]

    for i in range(6):
        boxes.nth(i).check()
    assert comp.page.evaluate("window.__testMap.getFilter('anriss-circles-fill')") is None

    comp.page.locator("#anriss-area-all-none").get_by_role(
        "button", name="Alle Grössenklassen ausblenden"
    ).click()
    for i in range(6):
        expect(boxes.nth(i)).not_to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anriss-circles-fill')") == [
        "==",
        ["get", "anrissflaeche"],
        -1,
    ]
    comp.page.locator("#anriss-area-all-none").get_by_role(
        "button", name="Alle Grössenklassen anzeigen"
    ).click()
    for i in range(6):
        expect(boxes.nth(i)).to_be_checked()
    assert comp.page.evaluate("window.__testMap.getFilter('anriss-circles-fill')") is None


_PIXEL = [2600002.5, 1200002.5]
_IFK_ARGS = {
    "center_lat": 46.8,
    "center_lon": 7.5,
    "pmtiles_port": 0,
    "coverage_version": COVERAGE_VERSION,
    "selected_pixel": _PIXEL,
}


def _circle_at_map_centre(page, **props):
    """A small square (~30 m) around the map centre, shaped like app.py's anriss circles."""
    lon, lat = page.evaluate("window.__testMap.getCenter().toArray()")
    half_side_deg = 0.0002
    ring = [
        [lon - half_side_deg, lat - half_side_deg],
        [lon + half_side_deg, lat - half_side_deg],
        [lon + half_side_deg, lat + half_side_deg],
        [lon - half_side_deg, lat + half_side_deg],
        [lon - half_side_deg, lat - half_side_deg],
    ]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "fillColor": "#f00",
                    "anrissflaeche": 125,
                    "lambda_ereignis_sum": 0.000123,
                    **props,
                },
            }
        ],
    }


def _source_features(page, source_id):
    return page.evaluate(
        f"window.__testMap.getSource('{source_id}').serialize().data.features.length"
    )


def test_ifk_rerun_updates_circles_and_pixel_squares(open_component):
    comp = open_component("overview_ifk", **_IFK_ARGS)
    page = comp.page
    assert _source_features(page, "selected-pixel") == 1
    assert _source_features(page, "anriss-circles") == 0

    # The IFK result arrives a rerun later.
    comp.render(**_IFK_ARGS, anriss_circles_geojson=_circle_at_map_centre(page, id_anriss=7))
    page.wait_for_function(
        "window.__testMap.getSource('anriss-circles').serialize().data.features.length === 1"
    )

    # "Pixel abwählen": no selected pixel, a square where it was, no circles.
    comp.render(**{**_IFK_ARGS, "selected_pixel": None}, highlight_pixel=_PIXEL)
    page.wait_for_function(
        "window.__testMap.getSource('selected-pixel').serialize().data.features.length === 0"
    )
    assert _source_features(page, "deselected-pixel") == 1
    assert _source_features(page, "anriss-circles") == 0
    assert comp.errors == []


def test_ifk_draw_bbox_sends_the_area_and_picks_no_pixel(open_component):
    comp = open_component("overview_ifk", **_IFK_ARGS)  # mounts at zoom 18
    page = comp.page
    page.locator("#draw-btn").click()
    box = page.locator("#map").bounding_box()
    center_x, center_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(center_x - 80, center_y - 60)
    page.mouse.down()
    page.mouse.move(center_x, center_y, steps=5)
    page.mouse.move(center_x + 80, center_y + 60, steps=5)
    page.mouse.up()

    page.wait_for_function("window.__componentValues.length === 1")
    selection = comp.values()[-1]["selection"]
    assert selection["type"] == "bbox"
    assert all((v - 2.5) % 5 == 0 for pt in selection["ring"] for v in pt)
    # The drag belonged to the drawing: the area's popup, no pixel's.
    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("IFK des Gebiets berechnen")
    expect(popup).not_to_contain_text("IFK an diesem Pixel")

    # Its button computes the area it was opened on.
    popup.locator(".popup-open-btn", has_text="IFK berechnen").click()
    page.wait_for_function("window.__componentValues.length === 2")
    assert comp.values()[-1] == {**comp.values()[0], "compute": True, "nonce": ANY}

    # With the tool off again, a click outside the area picks a pixel as before.
    page.mouse.click(center_x + 200, center_y + 150)
    expect(page.locator(".popup-open-btn", has_text="IFK berechnen")).to_be_visible()
    expect(popup).to_contain_text("IFK an diesem Pixel")
    assert comp.errors == []


def test_ifk_click_inside_the_area_opens_its_popup_not_a_pixels(open_component):
    e, n = _PIXEL
    ring = [
        [e - 50, n - 50],
        [e + 50, n - 50],
        [e + 50, n + 50],
        [e - 50, n + 50],
        [e - 50, n - 50],
    ]
    area = {"type": "bbox", "ring": ring}
    area_args = {**_IFK_ARGS, "selected_pixel": None, "selected_selection": area}
    comp = open_component("overview_ifk", **area_args, area_too_large=False)
    page = comp.page
    prefetched = []
    page.route("**/prefetch-ifk?*", lambda route: (prefetched.append(1), route.fulfill(status=202)))
    page.wait_for_function(
        "window.__testMap.queryRenderedFeatures({layers: ['draw-bbox-fill']}).length > 0"
    )

    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("IFK des Gebiets berechnen")
    expect(popup).to_contain_text("105 m × 105 m")
    button = popup.locator(".popup-open-btn")
    expect(button).to_be_enabled()
    assert _source_features(page, "selected-pixel") == 0
    assert prefetched == []

    # Python's check of the limits updates the open popup.
    comp.render(**area_args, area_too_large=True)
    expect(popup).to_contain_text("Gebiet zu gross")
    expect(button).to_be_disabled()

    # Without an area ("Zurücksetzen" in the sidebar), its popup closes.
    comp.render(**{**area_args, "selected_selection": None}, area_too_large=False)
    expect(popup).to_have_count(0)
    assert comp.values() == []
    assert comp.errors == []


def test_ifk_draw_controls_are_buttons_that_report_pressed(open_component):
    page = open_component("overview_ifk", **_IFK_ARGS).page
    draw_button = page.get_by_role("button", name="Rechteck zeichnen")
    polygon_button = page.get_by_role("button", name="Polygon zeichnen")
    expect(draw_button).to_have_attribute("id", "draw-btn")
    expect(polygon_button).to_have_attribute("id", "draw-poly-btn")
    expect(draw_button).to_have_attribute("aria-pressed", "false")

    draw_button.click()
    expect(draw_button).to_have_attribute("aria-pressed", "true")
    expect(polygon_button).to_have_attribute("aria-pressed", "false")


def test_ifk_area_rerun_draws_the_area_and_one_outline_for_its_anrisse(open_component):
    comp = open_component("overview_ifk", **_IFK_ARGS)
    page = comp.page
    expect(page.locator("#anriss-outline-row")).to_be_hidden()
    expect(page.locator("#anriss-area-box")).to_be_visible()

    # Python's area (an upload, a link) replaces the pixel; its result arrives later.
    e, n = _PIXEL
    ring = [[e, n], [e + 100, n], [e + 100, n + 50], [e, n + 50], [e, n]]
    area_args = {
        **_IFK_ARGS,
        "selected_pixel": None,
        "selected_selection": {"type": "bbox", "ring": ring},
    }
    comp.render(**area_args)
    expect(page.locator("#bbox-readout")).to_have_text("105 m × 55 m · 5'775 m²")
    assert _source_features(page, "selected-pixel") == 0

    comp.render(**area_args, anriss_outline_geojson=_circle_at_map_centre(page, id_anriss=7))
    page.wait_for_function(
        "window.__testMap.getSource('anriss-outline').serialize().data.features.length === 1"
    )
    expect(page.locator("#anriss-outline-row")).to_be_visible()
    expect(page.locator("#anriss-area-box")).to_be_hidden()

    # A picked pixel: no area, no outline.
    comp.render(**_IFK_ARGS)
    page.wait_for_function(
        "window.__testMap.getSource('anriss-outline').serialize().data.features.length === 0"
    )
    expect(page.locator("#clear-btn")).to_be_hidden()
    expect(page.locator("#anriss-area-box")).to_be_visible()
    assert comp.errors == []


def test_ifk_anriss_popup_escapes_values_and_opens_the_anriss(open_component):
    comp = open_component("overview_ifk", **_IFK_ARGS, initial_active_areas=[125, 250])
    page = comp.page
    comp.render(
        **_IFK_ARGS, anriss_circles_geojson=_circle_at_map_centre(page, id_anriss="<b>7</b>")
    )
    page.wait_for_function(
        "window.__testMap.queryRenderedFeatures({layers: ['anriss-circles-fill']}).length > 0"
    )

    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    popup = page.locator(".maplibregl-popup-content")
    expect(popup).to_contain_text("Anriss <b>7</b>")
    expect(popup).to_contain_text("Fläche: 125 m²")
    expect(popup).to_contain_text("λ [1/Jahr]: 1.2 × 10⁻⁴")
    assert popup.locator("b b").count() == 0

    page.locator(".maplibregl-popup-close-button").click()
    comp.render(**_IFK_ARGS, anriss_circles_geojson=_circle_at_map_centre(page, id_anriss=7))
    page.wait_for_function(
        "window.__testMap.queryRenderedFeatures({layers: ['anriss-circles-fill']})[0]?.properties.id_anriss === 7"
    )
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.locator(".popup-open-btn", has_text="Anriss öffnen").click()
    page.wait_for_function("window.__componentValues.length === 1")
    value = comp.values()[-1]
    assert value["id_anriss"] == 7
    assert value["active_areas"] == [125, 250]
    assert value["view"]["zoom"] == pytest.approx(18)
    assert comp.errors == []


_LEN = r"([\d.]+) (m|km)"  # "406 m" or "16.73 km"


def _metres(value, unit):
    return float(value) * (1000 if unit == "km" else 1)


# ── Raster-Karten ────────────────────────────────────────────────────────────


class _FakeJobServer:
    """Answers /job/<id>/<var>.png|.f32 like derivate_bbox_server.py for the
    job _JOB_ID, and 404 for any other id. Records the requested paths."""

    def __init__(self, page):
        self.requests: list[str] = []
        page.route("**/job/**", self._fulfill)

    def _fulfill(self, route):
        path = "/" + route.request.url.split("/job/", 1)[1]
        self.requests.append(path)
        job_id, file_name = path[1:].split("/")
        var, ext = file_name.split(".")
        cors = {"Access-Control-Allow-Origin": "*"}
        if job_id != _JOB_ID or (ext == "f32" and var not in _GRIDS):
            route.fulfill(status=404, headers=cors, body="Not found")
        elif ext == "png":
            route.fulfill(headers=cors, content_type="image/png", body=_PNG)
        else:
            route.fulfill(
                headers=cors,
                content_type="application/octet-stream",
                body=struct.pack("<4f", *_GRIDS[var]),
            )


@pytest.fixture()
def raster(open_component):
    comp = open_component(
        "raster_bbox_map",
        coverage_version=COVERAGE_VERSION,
        center_lat=46.95,
        center_lon=7.45,
        derivate_bbox_server_port=_JOB_PORT,
    )
    comp.jobs = _FakeJobServer(comp.page)
    return comp


def test_raster_draw_bbox_sends_selection_and_clear_resets_it(raster):
    page = raster.page
    draw_button, clear_button = page.locator("#draw-btn"), page.locator("#clear-btn")
    expect(clear_button).to_be_hidden()

    draw_button.click()
    expect(draw_button).to_contain_class("active")
    box = page.locator("#map").bounding_box()
    center_x, center_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(center_x - 80, center_y - 60)
    page.mouse.down()
    page.mouse.move(center_x, center_y, steps=5)
    page.mouse.move(center_x + 80, center_y + 60, steps=5)
    page.mouse.up()

    expect(draw_button).not_to_contain_class("active")
    # Size, not coordinates: width × height · area, and area = width × height for a bbox.
    readout = page.locator("#bbox-readout").inner_text()
    match = re.fullmatch(rf"{_LEN} × {_LEN} · ([\d']+) m²", readout)
    assert match, readout
    # Rounded lengths, so compare loosely.
    assert int(match[5].replace("'", "")) == pytest.approx(
        _metres(match[1], match[2]) * _metres(match[3], match[4]), rel=0.01
    )
    expect(clear_button).to_be_visible()
    page.wait_for_function("window.__componentValues.length === 1")
    selection = raster.values()[-1]["selection"]
    assert selection["type"] == "bbox"
    assert len(selection["ring"]) == 5 and selection["ring"][0] == selection["ring"][-1]
    # Corners snap to the 5 m gold-pixel lattice (k*5 + 2.5).
    assert all((v - 2.5) % 5 == 0 for pt in selection["ring"] for v in pt)

    clear_button.click()
    page.wait_for_function("window.__componentValues.length === 2")
    assert raster.values()[-1]["selection"] is None
    expect(clear_button).to_be_hidden()
    expect(page.locator("#bbox-readout")).to_have_text("")


def test_raster_bbox_button_toggles(raster):
    draw_button = raster.page.locator("#draw-btn")
    draw_button.click()
    expect(draw_button).to_contain_class("active")
    expect(raster.page.locator("#map")).to_contain_class("drawing")
    draw_button.click()
    expect(draw_button).not_to_contain_class("active")


def _wait_for_draw_tool(page):
    """mapbox-gl-draw sets itself up only once map.loaded() turns true, after the
    map's 'load' event; polygon mode before that ignores the clicks."""
    page.wait_for_function("!!window.__testMap.getLayer('gl-draw-polygon-fill.hot')")


def test_raster_draw_polygon_sends_selection(raster):
    page = raster.page
    _wait_for_draw_tool(page)
    page.locator("#draw-poly-btn").click()
    box = page.locator("#map").bounding_box()
    center_x, center_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    for dx, dy in ((-60, -60), (60, -60), (60, 60)):
        page.mouse.click(center_x + dx, center_y + dy)
    page.mouse.dblclick(center_x - 60, center_y + 60)

    page.wait_for_function("window.__componentValues.length === 1")
    selection = raster.values()[-1]["selection"]
    assert selection["type"] == "polygon"
    assert len(selection["ring"]) == 5 and selection["ring"][0] == selection["ring"][-1]
    expect(page.locator("#bbox-readout")).to_have_text(
        re.compile(rf"Polygon \(4 Eckpunkte\) · {_LEN} × {_LEN} · [\d']+ m²")
    )
    expect(page.locator("#clear-btn")).to_be_visible()
    assert raster.errors == []


def test_raster_polygon_button_highlights_and_toggles_off(raster):
    page = raster.page
    _wait_for_draw_tool(page)
    draw_button, polygon_button = page.locator("#draw-btn"), page.locator("#draw-poly-btn")
    draw_button.click()
    polygon_button.click()
    expect(draw_button).not_to_contain_class("active")
    expect(polygon_button).to_contain_class("active", timeout=2000)
    polygon_button.click()
    expect(polygon_button).not_to_contain_class("active")


_OVERLAYS = {
    "depth": _overlay("depth", "Tiefe", "m"),
    "velocity": _overlay("velocity", "Geschwindigkeit", "m/s"),
    "pressure": _overlay("pressure", "Druck", "kPa"),
}


def test_raster_var_switch_swaps_overlay(raster):
    page = raster.page
    switch = page.locator("#var-switch")
    expect(switch).to_be_hidden()

    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="velocity",
        raster_overlays=_OVERLAYS,
    )
    buttons = switch.locator(".var-btn")
    expect(buttons).to_have_count(3)
    expect(switch.locator(".var-btn.active")).to_have_text("Geschwindigkeit")
    expect(page.locator("#rl-title")).to_have_text("Geschwindigkeit [m/s]")

    for label, title in (("Tiefe", "Tiefe [m]"), ("Druck", "Druck [kPa]")):
        switch.locator(".var-btn", has_text=label).click()
        expect(switch.locator(".var-btn.active")).to_have_text(label)
        expect(page.locator("#rl-title")).to_have_text(title)
    assert page.evaluate("!!window.__testMap.getLayer('raster-overlay-layer')")

    raster.render(
        center_lat=46.95, center_lon=7.45, pmtiles_port=0, coverage_version=COVERAGE_VERSION
    )
    expect(switch).to_be_hidden()
    assert not page.evaluate("!!window.__testMap.getLayer('raster-overlay-layer')")
    assert raster.errors == []


def test_raster_var_switch_shows_labels_as_text(raster):
    overlays = {
        "depth": _overlay("depth", "<b>Tiefe</b>", "m"),
        "velocity": _overlay("velocity", "Geschwindigkeit", "m/s"),
    }
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="depth",
        raster_overlays=overlays,
    )
    switch = raster.page.locator("#var-switch")
    expect(switch.locator(".var-btn.active")).to_have_text("<b>Tiefe</b>")
    assert switch.locator("b").count() == 0
    expect(raster.page.locator("#rl-title")).to_have_text("<b>Tiefe</b> [m]")


def test_raster_selection_sent_on_a_rerun_is_drawn_and_zoomed_to(raster):
    # The sidebar upload sets the selection in Python; the map gets it on the next render.
    page = raster.page
    ring = [
        [2600002.5, 1200002.5],
        [2600102.5, 1200002.5],
        [2600102.5, 1200052.5],
        [2600002.5, 1200052.5],
        [2600002.5, 1200002.5],
    ]
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        selected_selection={"type": "polygon", "ring": ring},
    )
    expect(page.locator("#bbox-readout")).to_have_text(
        re.compile(r"Polygon \(4 Eckpunkte\) · 95 m × 45 m · 4.275 m²")
    )
    expect(page.locator("#clear-btn")).to_be_visible()
    page.wait_for_function("window.__testMap.getZoom() > 15 && !window.__testMap.isMoving()")
    lon, lat = page.evaluate("window.__testMap.getCenter().toArray()")
    east, north = _TO_LV95.transform(lon, lat)
    assert (east, north) == pytest.approx((2600052.5, 1200027.5), abs=5)
    assert raster.values() == []


def test_raster_legend_shown_with_overlay_and_collapsible(raster):
    page = raster.page
    legend = page.locator("#raster-legend")
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="depth",
        raster_overlays=_OVERLAYS,
    )
    expect(legend).to_be_visible(timeout=3000)
    legend.locator(".legend-close").click()
    expect(page.locator("#rl-title")).to_be_hidden()
    legend.locator(".legend-open").click()
    expect(page.locator("#rl-title")).to_have_text("Tiefe [m]")

    # Collapsed, then the overlay goes away: the view hides the whole box, chip included.
    legend.locator(".legend-close").click()
    raster.render(
        center_lat=46.95, center_lon=7.45, pmtiles_port=0, coverage_version=COVERAGE_VERSION
    )
    expect(legend).to_be_hidden()


def _hover_at_map_centre(page):
    """A 2x2 hover section of 2 km pixels whose bottom-right pixel holds the
    map's centre, half a pixel away from every edge."""
    lon, lat = page.evaluate("window.__testMap.getCenter().toArray()")
    east, north = _TO_LV95.transform(lon, lat)
    res = 2000
    return {
        "width": 2,
        "height": 2,
        "xmin": east - 1.5 * res,
        "ymax": north + 1.5 * res,
        "res": res,
    }


def _tooltip_at_map_centre(page, text):
    """Moves the mouse onto the map centre until the pixel tooltip shows
    `text`; the grid arrives asynchronously, and only a mousemove redraws."""
    box = page.locator("#map").bounding_box()
    tooltip = page.locator("#pixel-tooltip")
    for _ in range(50):
        page.mouse.move(box["x"] + 5, box["y"] + 5)
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        if tooltip.is_visible() and tooltip.text_content() == text:
            return
        page.wait_for_timeout(100)
    expect(tooltip).to_have_text(text)


def test_raster_overlay_and_hover_values_come_from_the_job(raster):
    page = raster.page
    hover = _hover_at_map_centre(page)
    overlays = {
        "depth": _overlay("depth", "Tiefe", "m", hover=hover),
        "velocity": _overlay("velocity", "Geschwindigkeit", "m/s", hover=hover),
    }
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="depth",
        raster_overlays=overlays,
    )

    expect(page.locator("#rl-title")).to_have_text("Tiefe [m]")
    png_url = page.evaluate("window.__testMap.getSource('raster-overlay').serialize().url")
    assert png_url == f"http://127.0.0.1:{_JOB_PORT}/job/{_JOB_ID}/depth.png"
    _tooltip_at_map_centre(page, "Tiefe: 3.25 m")

    # Switching back and forth fetches each grid once; a rerun with the same job changes nothing.
    switch = page.locator("#var-switch")
    switch.locator(".var-btn", has_text="Geschwindigkeit").click()
    _tooltip_at_map_centre(page, "Geschwindigkeit: 0.50 m/s")
    switch.locator(".var-btn", has_text="Tiefe").click()
    _tooltip_at_map_centre(page, "Tiefe: 3.25 m")
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="depth",
        raster_overlays=overlays,
    )
    _tooltip_at_map_centre(page, "Tiefe: 3.25 m")
    grids = [r for r in raster.jobs.requests if r.endswith(".f32")]
    assert sorted(grids) == [f"/{_JOB_ID}/depth.f32", f"/{_JOB_ID}/velocity.f32"]
    assert raster.errors == []


def test_raster_overlay_of_unknown_job_shows_error(raster):
    page = raster.page
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="depth",
        raster_overlays={"depth": _overlay("depth", "Tiefe", "m", job_id="expired")},
    )
    status = page.locator("#map-status")
    expect(status).to_have_class("error")
    expect(status).to_have_text("Rasterbild konnte nicht geladen werden.")


def test_raster_hover_grid_error_shows_error_and_keeps_the_image(raster):
    page = raster.page
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable="pressure",
        raster_overlays={
            "pressure": _overlay("pressure", "Druck", "kPa", hover=_hover_at_map_centre(page))
        },
    )
    status = page.locator("#map-status")
    expect(status).to_have_class("error")
    expect(status).to_have_text("Pixelwerte konnten nicht geladen werden.")
    expect(page.locator("#rl-title")).to_have_text("Druck [kPa]")
    assert page.evaluate("!!window.__testMap.getLayer('raster-overlay-layer')")


def _raster_opacity(page, layer_id):
    return page.evaluate("id => window.__testMap.getPaintProperty(id, 'raster-opacity')", layer_id)


def _render_overlays(raster, overlays, active_variable="depth"):
    raster.render(
        center_lat=46.95,
        center_lon=7.45,
        pmtiles_port=0,
        coverage_version=COVERAGE_VERSION,
        active_variable=active_variable,
        raster_overlays=overlays,
    )


def test_raster_layer_row_hides_the_overlay_its_legend_and_values(raster):
    page = raster.page
    row = page.locator("#row-raster-overlay")
    slider = page.locator("#row-raster-overlay-opacity input")
    expect(row).to_be_hidden()
    expect(slider).to_be_hidden()

    hover = _hover_at_map_centre(page)
    _render_overlays(raster, {"depth": _overlay("depth", "Tiefe", "m", hover=hover)})
    expect(row).to_have_text("Raster")
    expect(row.locator("input")).to_be_checked()
    expect(slider).to_have_value("75")
    expect(slider).to_have_attribute("aria-label", "Raster: Deckkraft")
    page.wait_for_function("!!window.__testMap.getLayer('raster-overlay-layer')")
    assert _raster_opacity(page, "raster-overlay-layer") == 0.75
    _tooltip_at_map_centre(page, "Tiefe: 3.25 m")

    row.locator("input").uncheck()
    assert raster.layer_visibility("raster-overlay-layer") == "none"
    expect(page.locator("#raster-legend")).to_be_hidden()
    expect(slider).to_be_disabled()
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2 + 1, box["y"] + box["height"] / 2)
    expect(page.locator("#pixel-tooltip")).to_be_hidden()

    row.locator("input").check()
    assert raster.layer_visibility("raster-overlay-layer") == "visible"
    expect(page.locator("#rl-title")).to_have_text("Tiefe [m]")
    expect(slider).to_be_enabled()

    raster.render(
        center_lat=46.95, center_lon=7.45, pmtiles_port=0, coverage_version=COVERAGE_VERSION
    )
    expect(row).to_be_hidden()
    expect(slider).to_be_hidden()
    assert raster.errors == []


def test_raster_opacity_slider_holds_for_a_new_job_which_shows_itself(raster):
    page = raster.page
    _render_overlays(raster, {"depth": _overlay("depth", "Tiefe", "m")})
    slider = page.locator("#row-raster-overlay-opacity input")
    slider.fill("30")
    expect(page.locator("#row-raster-overlay-opacity")).to_contain_text("30 %")
    assert _raster_opacity(page, "raster-overlay-layer") == 0.3
    # The keyboard moves it in steps of 5 %.
    slider.press("ArrowRight")
    expect(slider).to_have_attribute("aria-valuetext", "35 %")
    assert _raster_opacity(page, "raster-overlay-layer") == 0.35

    # A rerun of the same job keeps the layer off; a new job shows itself, at 35 %.
    page.locator("#row-raster-overlay input").uncheck()
    _render_overlays(raster, {"depth": _overlay("depth", "Tiefe", "m")})
    expect(page.locator("#row-raster-overlay input")).not_to_be_checked()
    _render_overlays(
        raster, {"velocity": _overlay("velocity", "Geschwindigkeit", "m/s")}, "velocity"
    )
    expect(page.locator("#row-raster-overlay input")).to_be_checked()
    expect(page.locator("#rl-title")).to_have_text("Geschwindigkeit [m/s]")
    assert raster.layer_visibility("raster-overlay-layer") == "visible"
    assert _raster_opacity(page, "raster-overlay-layer") == 0.35
    expect(slider).to_have_value("35")
    assert raster.errors == []


# ── Raster-Derivate ──────────────────────────────────────────────────────────


def test_derivate_coverage_is_fetched_again_when_its_version_changes(open_component):
    # Raster-Derivate's coverage changes with the metric.
    comp = open_component(
        "raster_bbox_map", coverage_version=COVERAGE_VERSION, center_lat=46.95, center_lon=7.45
    )
    comp.page.wait_for_function(
        "window.__testMap.querySourceFeatures('gold-coverage').length > 0", timeout=10_000
    )

    with comp.page.expect_request("**/coverage.geojson?v=fedcba9876543210"):
        comp.render(
            center_lat=46.95, center_lon=7.45, pmtiles_port=0, coverage_version="fedcba9876543210"
        )

    assert [url.rsplit("=", 1)[1] for url in comp.coverage_requests[:1]] == [COVERAGE_VERSION]
    assert comp.errors == []


_DERIVATE_ARGS = {
    "derivate_bbox_metric": "return_period",
    "derivate_bbox_partition": "depth",
    "derivate_bbox_band": 1,
    "derivate_bbox_label": "Wiederkehrperiode",
    "derivate_bbox_unit": "Jahre",
    "derivate_bbox_scale": "log",
    "derivate_bbox_ramp": "viridis",
    "derivate_bbox_vmin": 1,
    "derivate_bbox_vmax": 10000,
}


class _FakeCropServer:
    """Answers the component's /bbox.png and /value.json like derivate_bbox_server.py."""

    def __init__(self, page, value=42.0):
        self.crops = []
        page.route("**/bbox.png?*", self._crop)
        page.route("**/value.json?*", lambda route: route.fulfill(json={"value": value}))

    def _crop(self, route):
        self.crops.append(route.request.url)
        route.fulfill(
            body=_PNG, content_type="image/png", headers={"X-Corners": json.dumps(_CORNERS)}
        )


@pytest.fixture()
def derivate(page, open_component, component_server):
    server = _FakeCropServer(page)
    comp = open_component(
        "raster_bbox_map",
        coverage_version=COVERAGE_VERSION,
        center_lat=46.95,
        center_lon=7.45,
        derivate_bbox_server_port=component_server,
        **_DERIVATE_ARGS,
    )
    comp.page.wait_for_function("!!window.__testMap.getLayer('derivate-bbox-layer')")
    comp.crop_server = server
    comp.args = {
        "center_lat": 46.95,
        "center_lon": 7.45,
        "pmtiles_port": component_server,
        "coverage_version": COVERAGE_VERSION,
        "derivate_bbox_server_port": component_server,
        **_DERIVATE_ARGS,
    }
    return comp


def test_derivate_preview_shows_the_crop_and_its_legend(derivate):
    expect(derivate.page.locator("#raster-legend")).to_be_visible()
    expect(derivate.page.locator("#rl-title")).to_contain_text("Wiederkehrperiode")
    assert "metric=return_period&partition=depth&band=1" in derivate.crop_server.crops[-1]
    assert derivate.errors == []


def test_derivate_click_shows_the_pixel_value(derivate):
    box = derivate.page.locator("#map").bounding_box()
    derivate.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(derivate.page.locator("#pixel-tooltip")).to_have_text("Wiederkehrperiode: 42 Jahre")


def test_derivate_failed_crop_says_so(page, derivate):
    page.unroute("**/bbox.png?*")
    page.route("**/bbox.png?*", lambda route: route.fulfill(status=500))
    derivate.page.evaluate("window.__testMap.panBy([50, 0])")
    expect(page.locator("#map-status")).to_have_text(
        "Rasterausschnitt konnte nicht geladen werden."
    )


def test_derivate_rerun_with_the_same_args_fetches_no_new_crop(derivate):
    derivate.page.wait_for_timeout(500)  # past the pan debounce
    crops_before = len(derivate.crop_server.crops)
    derivate.render(**derivate.args)
    derivate.page.wait_for_timeout(1000)
    assert len(derivate.crop_server.crops) == crops_before


def test_derivate_unticked_layer_is_not_fetched_and_hides_its_legend(derivate):
    page = derivate.page
    row = page.locator("#row-derivate")
    slider = page.locator("#row-derivate-opacity input")
    expect(row).to_have_text("Raster")
    expect(slider).to_have_value("85")
    assert _raster_opacity(page, "derivate-bbox-layer") == 0.85

    row.locator("input").uncheck()
    page.wait_for_function("!window.__testMap.getLayer('derivate-bbox-layer')")
    expect(page.locator("#raster-legend")).to_be_hidden()
    crops_before = len(derivate.crop_server.crops)
    page.evaluate("window.__testMap.panBy([50, 0])")
    page.wait_for_timeout(600)  # past the pan debounce
    assert len(derivate.crop_server.crops) == crops_before
    box = page.locator("#map").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.locator("#pixel-tooltip")).to_be_hidden()

    row.locator("input").check()
    page.wait_for_function("!!window.__testMap.getLayer('derivate-bbox-layer')")
    expect(page.locator("#raster-legend")).to_be_visible()
    slider.fill("50")
    assert _raster_opacity(page, "derivate-bbox-layer") == 0.5

    # The crop after a pan replaces the layer, at the chosen opacity.
    crop_url = "window.__testMap.getSource('derivate-bbox-src')?.serialize().url"
    before = page.evaluate(crop_url)
    page.evaluate("window.__testMap.panBy([50, 0])")
    page.wait_for_function(f"(u => u && u !== {json.dumps(before)})({crop_url})")
    assert _raster_opacity(page, "derivate-bbox-layer") == 0.5
    assert derivate.errors == []
