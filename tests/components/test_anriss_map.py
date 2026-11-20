"""The Anriss view's result map (app/anriss_map, MapLibre): value legend,
layer box with the outline overlays, hover value, and data updates on a
rerun that keep the viewport."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.components

_BOUNDS = [[46.600, 7.600], [46.610, 7.615]]


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


_CELLS = _feature_collection(_square(7.6070, 46.6045, fillColor="#21918c", value_label="0.42 m"))
_LEGEND = {
    "title": "Fliesstiefe [m]",
    "gradient": "#440154, #fde725",
    "vmin_label": "0.02",
    "vmid_label": "0.50",
    "vmax_label": "0.97",
}


_VARIABLES = [
    {"key": "depth", "label": "Fliesstiefe [m]"},
    {"key": "velocity", "label": "Fliessgeschwindigkeit [m/s]"},
    {"key": "pressure", "label": "Druck [kN/m²]"},
]


def _overlays(reach_visible=False, adhoc=None):
    return [
        {
            "id": "hull",
            "label": "Umhüllende",
            "geojson": _feature_collection(_square(7.601, 46.601, 0.012)),
            "color": "#0d47a1",
            "width": 2,
            "dash": None,
            "visible": True,
        },
        {
            "id": "hull_adhoc",
            "label": "Umhüllende (Ad-hoc)",
            "geojson": adhoc,
            "color": "#ff8f00",
            "width": 2,
            "dash": [3, 3],
            "visible": True,
        },
        {
            "id": "release",
            "label": "Anriss (Kreis)",
            "geojson": _feature_collection(_square(7.606, 46.606)),
            "color": "#000000",
            "width": 2,
            "dash": None,
            "visible": True,
        },
        {
            "id": "reach",
            "label": "800m-Grenze (max. Distanz)",
            "geojson": _feature_collection(_square(7.600, 46.600, 0.015)),
            "color": "#e53935",
            "width": 3,
            "dash": [3.3, 2],
            "opacity": 0.9,
            "visible": reach_visible,
        },
    ]


def _args(**overrides):
    args = dict(
        bounds=_BOUNDS,
        cells_geojson=_CELLS,
        cells_version="v1",
        cells_label="Fliesstiefe",
        legend=_LEGEND,
        overlays=_overlays(),
        variables=_VARIABLES,
        active_variable="depth",
    )
    args.update(overrides)
    return args


@pytest.fixture()
def anriss(open_component):
    comp = open_component("anriss_map", **_args())
    comp.page.wait_for_function("!!window.__testMap.getLayer('ov-reach')")
    yield comp
    assert comp.cdn_requests == []
    assert comp.errors == []


def test_overlay_colour_is_not_parsed_as_html(anriss):
    # The swatch colour goes through the CSSOM, not into innerHTML.
    bad = {**_overlays()[0], "id": "bad", "label": "<b>x</b>", "color": 'red"><img src=x>'}
    anriss.render(**_args(overlays=[*_overlays(), bad]))
    expect(anriss.page.locator("#row-bad")).to_have_text("<b>x</b>")
    expect(anriss.page.locator("#layer-rows img, #layer-rows b")).to_have_count(0)


def _cells_data(comp):
    return comp.page.evaluate("window.__testMap.getSource('cells').serialize().data")


def test_opens_on_bounds_with_legend_and_chrome(anriss):
    page = anriss.page
    center = page.evaluate("window.__testMap.getCenter().toArray()")
    assert center == pytest.approx([7.6075, 46.605], abs=1e-3)
    expect(page.locator("#vl-title")).to_have_text("Fliesstiefe [m]")
    expect(page.locator("#vl-max")).to_have_text("0.97")
    expect(page.locator("#map-tools")).to_be_visible()
    expect(page.get_by_role("button", name="Koordinateneingabe (LV95)")).to_be_visible()
    expect(page.get_by_role("button", name="Hintergrundkarte")).to_be_visible()
    expect(page.locator("#zoom-debug")).to_contain_text("Zoomstufe")


@pytest.mark.parametrize(
    "box, chip_text",
    [
        ("#value-legend", "Legende"),
        ("#legend", "Layer"),
        ("#var-box", "Visualisierungsvariable"),
    ],
)
def test_close_collapses_box_and_chip_reopens_it(anriss, box, chip_text):
    box = anriss.page.locator(box)
    chip = box.locator(".legend-open")
    box.locator(".legend-close").click()
    expect(chip).to_be_visible()
    expect(chip).to_contain_text(chip_text)
    chip.click()
    expect(chip).to_be_hidden()


def test_layer_box_lists_only_overlays_with_data(anriss):
    rows = anriss.page.locator("#layer-rows .legend-row:visible")
    expect(rows).to_have_text(
        ["Fliesstiefe", "Umhüllende", "Anriss (Kreis)", "800m-Grenze (max. Distanz)"]
    )
    assert anriss.page.evaluate("!!window.__testMap.getLayer('ov-hull_adhoc')") is False


def test_checkboxes_toggle_layers(anriss):
    cells = anriss.page.locator("#row-cells input")
    expect(cells).to_be_checked()
    cells.uncheck()
    assert anriss.layer_visibility("cells-fill") == "none"
    cells.check()
    assert anriss.layer_visibility("cells-fill") == "visible"

    anriss.page.locator("#row-hull input").uncheck()
    assert anriss.layer_visibility("ov-hull") == "none"


def test_reach_circle_follows_server_default_until_user_ticks_it(anriss):
    reach = anriss.page.locator("#row-reach input")
    expect(reach).not_to_be_checked()
    assert anriss.layer_visibility("ov-reach") == "none"

    anriss.render(**_args(overlays=_overlays(reach_visible=True)))
    expect(reach).to_be_checked()
    assert anriss.layer_visibility("ov-reach") == "visible"

    reach.uncheck()
    anriss.render(**_args(overlays=_overlays(reach_visible=True)))
    expect(reach).not_to_be_checked()
    assert anriss.layer_visibility("ov-reach") == "none"


def test_late_overlay_is_drawn_below_the_ones_listed_after_it(anriss):
    anriss.render(
        **_args(overlays=_overlays(adhoc=_feature_collection(_square(7.602, 46.602, 0.01))))
    )
    anriss.page.wait_for_function("!!window.__testMap.getLayer('ov-hull_adhoc')")
    order = anriss.page.evaluate(
        "window.__testMap.getStyle().layers.map(l => l.id).filter(id => id.startsWith('ov-'))"
    )
    assert order == ["ov-hull", "ov-hull_adhoc", "ov-release", "ov-reach"]
    expect(anriss.page.locator("#row-hull_adhoc")).to_be_visible()


def test_cells_reload_only_on_new_version_and_viewport_is_kept(anriss):
    page = anriss.page
    page.evaluate("window.__testMap.jumpTo({center: [7.62, 46.62], zoom: 15})")
    other = _feature_collection(
        _square(7.608, 46.605, fillColor="#fde725", value_label="1.20 m/s"),
        _square(7.609, 46.605, fillColor="#fde725", value_label="1.10 m/s"),
    )

    anriss.render(**_args(cells_geojson=other, cells_version="v1"))
    page.wait_for_timeout(200)
    assert len(_cells_data(anriss)["features"]) == 1

    anriss.render(
        **_args(
            cells_geojson=other,
            cells_version="v2",
            cells_label="Fliessgeschwindigkeit",
            legend={**_LEGEND, "title": "Fliessgeschwindigkeit [m/s]"},
        )
    )
    page.wait_for_function(
        "window.__testMap.getSource('cells').serialize().data.features.length === 2"
    )
    expect(page.locator("#row-cells")).to_have_text("Fliessgeschwindigkeit")
    expect(page.locator("#vl-title")).to_have_text("Fliessgeschwindigkeit [m/s]")
    assert page.evaluate("window.__testMap.getCenter().toArray()") == pytest.approx(
        [7.62, 46.62], abs=1e-6
    )


def test_hover_shows_value_under_pointer(anriss):
    page = anriss.page
    # `load` fires before the cells source is rendered; hovering earlier finds no feature.
    page.wait_for_function(
        "window.__testMap.queryRenderedFeatures({layers: ['cells-fill']}).length > 0"
    )
    point = page.evaluate(
        "(() => { const p = window.__testMap.project([7.60725, 46.60475]); return [p.x, p.y]; })()"
    )
    box = page.locator("#map").bounding_box()
    page.mouse.move(box["x"] + point[0], box["y"] + point[1])
    expect(page.locator(".cell-tooltip")).to_have_text("Fliesstiefe: 0.42 m")
    page.mouse.move(box["x"] + 5, box["y"] + box["height"] - 5)
    expect(page.locator(".cell-tooltip")).to_have_count(0)


def test_coordinate_search_jumps_to_lv95_point(anriss):
    page = anriss.page
    anriss.open_popover("search")
    page.locator("#search-x").fill("2600000")
    page.locator("#search-y").fill("1200000")
    page.locator("#search-go").click()
    page.wait_for_function("Math.abs(window.__testMap.getZoom() - 17) < 0.01", timeout=10_000)
    lon, lat = page.evaluate("window.__testMap.getCenter().toArray()")
    assert (lon, lat) == pytest.approx(
        (7.4386324, 46.9510828), abs=1e-6
    )  # pyproj EPSG:2056 -> 4326


def test_basemap_switch(anriss):
    ctrl = anriss.open_popover("basemap")
    ctrl.locator(".bm-btn[data-bm='relief']").click()
    expect(ctrl.locator(".bm-btn.active")).to_have_text("SwissTopo Relief")
    assert anriss.layer_visibility("bg-relief") == "visible"
    assert anriss.layer_visibility("bg-lk") == "none"


def test_layer_box_has_a_title(anriss):
    expect(anriss.page.locator("#legend .mc-ctrl-title")).to_have_text("Layer")


def test_variable_switch_sends_pick_and_follows_server(anriss):
    page = anriss.page
    buttons = page.locator("#var-btns .var-btn")
    expect(buttons).to_have_text(
        ["Fliesstiefe [m]", "Fliessgeschwindigkeit [m/s]", "Druck [kN/m²]"]
    )
    expect(page.locator(".var-btn.active")).to_have_text("Fliesstiefe [m]")

    buttons.nth(2).click()
    expect(page.locator(".var-btn.active")).to_have_text("Druck [kN/m²]")
    page.wait_for_function("window.__componentValues.length === 1")
    assert anriss.values()[-1] == {"variable": "pressure"}

    buttons.nth(2).click()  # already active: nothing sent
    page.wait_for_timeout(200)
    assert len(anriss.values()) == 1

    anriss.render(**_args(active_variable="velocity"))
    expect(page.locator(".var-btn.active")).to_have_text("Fliessgeschwindigkeit [m/s]")
