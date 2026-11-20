"""Chrome shared by the map components (frontend/src/shared/map-controls.ts): legend
box + its close button, Gold/Prozessquellen toggles, the control column (zoom
buttons, "Zoom Kanton Bern", coordinate search and basemap popovers).

The chrome is one module, so its behaviour is tested once, on Simulierte Ereignisse. Each
component that uses it gets one smoke test: it loads, shows the chrome, and a
toggle responds. The input rules of the coordinate search are in
frontend/src/shared/search-input.test.ts, the popover rules in
frontend/src/shared/popover.test.ts."""

import pytest
from playwright.sync_api import Page, expect

from .conftest import COVERAGE_VERSION

pytestmark = pytest.mark.components

# The control column, top to bottom.
_COLUMN = [
    "Hineinzoomen",
    "Herauszoomen",
    "Zoom Kanton Bern",
    "Koordinateneingabe (LV95)",
    "Hintergrundkarte",
]


# Every basemap layer and the basemap it draws.
_BASEMAP_LAYERS = {
    "bg-lk": "lk",
    "bg-lk-10k": "lk",
    "bg-relief": "relief",
    "bg-osm": "osm",
}


@pytest.fixture()
def comp(open_component):
    return open_component("overview", coverage_version=COVERAGE_VERSION)


def column_labels(page: Page) -> list[str | None]:
    """The labels of the buttons in the map's right-hand column, top to bottom."""
    return page.locator(".maplibregl-ctrl-top-right .maplibregl-ctrl-group button").evaluate_all(
        "els => els.map(el => el.getAttribute('aria-label'))"
    )


@pytest.mark.parametrize("component", ["overview", "overview_ifk", "raster_bbox_map"])
def test_loads_without_js_errors(open_component, component):
    comp = open_component(component, coverage_version=COVERAGE_VERSION)
    page = comp.page
    expect(page.locator("#legend")).to_be_visible()
    assert column_labels(page) == _COLUMN
    expect(page.locator("#basemap-ctrl")).to_be_hidden()
    expect(page.locator("#search-ctrl")).to_be_hidden()
    expect(page.locator("#zoom-debug")).to_contain_text("Zoomstufe")

    # Each component sets the coverage URL itself (Raster-Karten on a render).
    page.wait_for_function(
        "window.__testMap.querySourceFeatures('gold-coverage').length > 0", timeout=10_000
    )
    page.locator("#gold-toggle").uncheck()
    assert comp.layer_visibility("gold-coverage-fill") == "none"

    # Built from frontend/, the page bundles MapLibre, pmtiles and proj4.
    assert comp.cdn_requests == []
    assert comp.errors == []


def test_a_language_switch_changes_the_texts_and_keeps_the_map(comp):
    # I18N-1: a rerun with French texts updates them in place; the map and its view stay.
    page = comp.page
    page.evaluate("() => { window.__testMap.jumpTo({center: [7.45, 46.95], zoom: 12}); }")
    page.evaluate("() => { window.__testMap.__sameMap = true; }")
    french = {key: f"[FR] {text}" for key, text in comp.texts["labels"].items()}
    comp.render(coverage_version=COVERAGE_VERSION, labels=french, locale="fr-CH")

    expect(page.locator("#zoom-debug")).to_contain_text("[FR] Zoomstufe")
    assert column_labels(page) == [f"[FR] {label}" for label in _COLUMN]
    assert page.evaluate("() => window.debugMap.__sameMap") is True
    assert page.evaluate("() => window.debugMap.getZoom()") == 12
    assert comp.errors == []


def test_map_text_is_set_in_roboto_from_the_bundle(comp):
    # The map page is an iframe in the app, so the app's theme fonts do not
    # reach it. Its own bundle declares Roboto and the chrome text uses it.
    page = comp.page
    page.evaluate("() => document.fonts.load('500 16px Roboto')")
    loaded = page.evaluate(
        "() => [...document.fonts].filter(f => f.family === 'Roboto' && f.status === 'loaded')"
        ".map(f => f.weight).sort()"
    )
    assert "500" in loaded
    # MapLibre's own scale bar and attribution too, not its default Helvetica Neue.
    scale, attribution = (
        page.locator(".maplibregl-ctrl-scale"),
        page.locator(".maplibregl-ctrl-attrib"),
    )
    for shown_text in (page.locator("#legend"), scale, attribution, comp.open_popover("basemap")):
        family = shown_text.evaluate("el => getComputedStyle(el).fontFamily")
        assert family.startswith("Roboto"), f"{shown_text} is set in {family}"
    assert comp.errors == []


def test_label_glyphs_come_from_the_component_itself(comp):
    # The map's style points at the glyphs built into the component, and
    # the one range the number labels need is there for the font the label layer uses.
    template = comp.page.evaluate("() => window.debugMap.getStyle().glyphs")
    assert template.startswith(comp.page.url.rsplit("/", 1)[0] + "/glyphs/")
    fontstack = comp.page.evaluate(
        "() => window.debugMap.getLayoutProperty('prozessquelle-label-text', 'text-font')[0]"
    )
    assert fontstack == "roboto-regular"
    url = template.replace("{fontstack}", fontstack).replace("{range}", "0-255")
    status = comp.page.evaluate("url => fetch(url).then(r => r.status)", url)
    assert status == 200


def test_map_chrome_uses_the_shared_tokens(comp):
    # app/styles/tokens.css is bundled into the component, and the active
    # basemap button takes the app's accent from it.
    brand = comp.page.evaluate(
        "() => getComputedStyle(document.documentElement).getPropertyValue('--pgr-brand').trim()"
    )
    assert brand.lower() == "#4e4e4e"
    active = comp.open_popover("basemap").locator(".bm-btn.active")
    assert active.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(78, 78, 78)"


def test_failed_data_tiles_show_a_map_error_that_a_keyboard_closes(comp):
    # open_component answers every PMTiles archive with 404, like a tile
    # sidecar that can't reach its bucket.
    status = comp.page.get_by_role("button", name="Kartendaten konnten nicht geladen werden.")
    expect(status).to_be_visible()
    status.focus()
    comp.page.keyboard.press("Enter")
    expect(comp.page.locator("#map-status")).to_be_hidden()


def test_close_collapses_box_and_chip_reopens_it(comp):
    box = comp.page.locator("#legend")
    content = box.locator(".legend-row").first
    chip = box.locator(".legend-open")
    expect(chip).to_be_hidden()

    box.locator(".legend-close").click()
    expect(content).to_be_hidden()
    expect(chip).to_be_visible()
    expect(chip).to_contain_text("Layer")

    chip.click()
    expect(content).to_be_visible()
    expect(chip).to_be_hidden()
    assert comp.errors == []


def test_coverage_is_fetched_from_the_tile_sidecar_by_version(comp):
    # The request itself, not the source's data: MapLibre 6 replaces the URL
    # with the loaded GeoJSON once it has arrived.
    port = comp.page.evaluate("location.port")
    comp.page.wait_for_function(
        "window.__testMap.querySourceFeatures('gold-coverage').length > 0", timeout=10_000
    )
    assert comp.coverage_requests == [
        f"http://127.0.0.1:{port}/coverage.geojson?v={COVERAGE_VERSION}"
    ]


def test_gold_toggle_hides_and_shows_coverage(comp):
    toggle = comp.page.locator("#gold-toggle")
    expect(toggle).to_be_checked()
    assert comp.layer_visibility("gold-coverage-fill") == "visible"

    toggle.uncheck()
    assert comp.layer_visibility("gold-coverage-fill") == "none"
    assert comp.layer_visibility("gold-coverage-outline") == "none"

    toggle.check()
    assert comp.layer_visibility("gold-coverage-fill") == "visible"


def _paint(comp, layer_id, prop):
    return comp.page.evaluate(
        "([id, prop]) => window.__testMap.getPaintProperty(id, prop)", [layer_id, prop]
    )


def test_coverage_fill_fades_out_at_street_scale_and_the_outline_stays(comp):
    # The gold fill tinted the whole basemap at street scale.
    zoom = ["interpolate", ["linear"], ["zoom"]]
    assert _paint(comp, "gold-coverage-fill", "fill-opacity") == [*zoom, 11, 0.25, 13, 0]
    assert _paint(comp, "gold-coverage-outline", "line-width") == 1.5


def test_raster_coverage_without_fill_stays_without_fill(open_component):
    # Raster-Derivate passes 0: borders only, its data is an image.
    comp = open_component(
        "raster_bbox_map", coverage_version=COVERAGE_VERSION, coverage_fill_opacity=0
    )
    zoom = ["interpolate", ["linear"], ["zoom"]]
    assert _paint(comp, "gold-coverage-fill", "fill-opacity") == [*zoom, 11, 0, 13, 0]


def test_prozessquelle_toggle_shows_and_hides_layer(comp):
    toggle = comp.page.locator("#prozessquelle-toggle")
    expect(toggle).not_to_be_checked()
    assert comp.layer_visibility("prozessquelle-fill") == "none"

    toggle.check()
    for layer in ("prozessquelle-fill", "prozessquelle-outline", "prozessquelle-label-text"):
        assert comp.layer_visibility(layer) == "visible"

    toggle.uncheck()
    assert comp.layer_visibility("prozessquelle-fill") == "none"


def test_basemap_switcher_cycles_through_all_basemaps(comp):
    # The popover stays open after a pick, so basemaps can be compared.
    buttons = comp.open_popover("basemap").locator(".bm-btn")
    expect(buttons).to_have_count(3)
    for i in range(3):
        button = buttons.nth(i)
        button.click()
        expect(button).to_have_class("bm-btn active")
        basemap = button.get_attribute("data-bm")
        for layer, owner in _BASEMAP_LAYERS.items():
            assert comp.layer_visibility(layer) == ("visible" if owner == basemap else "none")


def test_lk_basemap_switches_to_the_10k_map_at_zoom_14(comp):
    # The national map series below zoom 14, the 1:10'000 map from 14; the two
    # bands meet without a gap.
    bands = comp.page.evaluate(
        """() => ["bg-lk", "bg-lk-10k"].map((id) => {
            const layer = window.__testMap.getLayer(id);
            const source = window.__testMap.getSource(layer.source);
            return [layer.minzoom ?? 0, layer.maxzoom ?? 24, source.tiles[0]];
        })"""
    )
    (national_min, national_max, national_tiles), (detail_min, detail_max, detail_tiles) = bands
    assert (national_min, national_max) == (0, 14)
    assert (detail_min, detail_max) == (14, 24)
    assert "/ch.swisstopo.pixelkarte-grau/" in national_tiles
    assert "/ch.swisstopo.landeskarte-grau-10/" in detail_tiles


def test_basemap_switcher_keeps_its_size_when_the_selection_changes(comp):
    # The active button is bold, which must not change the box's size.
    box = comp.open_popover("basemap")
    buttons = box.locator(".bm-btn")
    sizes = set()
    for i in range(3):
        buttons.nth(i).click()
        expect(buttons.nth(i)).to_have_class("bm-btn active")
        bounds = box.bounding_box()
        sizes.add((round(bounds["width"], 1), round(bounds["height"], 1)))
    assert len(sizes) == 1, sizes


def test_prozessquelle_labels_have_an_accent_background(comp):
    # White numbers on a pill in the app's accent colour (a stretchable image).
    layer = "prozessquelle-label-text"
    page = comp.page
    assert page.evaluate("l => window.__testMap.getLayoutProperty(l, 'icon-image')", layer) == (
        "prozessquelle-label-bg"
    )
    assert page.evaluate("() => window.__testMap.hasImage('prozessquelle-label-bg')")
    assert page.evaluate("l => window.__testMap.getPaintProperty(l, 'text-color')", layer) == (
        "#ffffff"
    )


@pytest.mark.parametrize("name", ["search", "basemap"])
def test_popover_opens_beside_its_trigger_and_closes_on_a_map_click(comp, name):
    page = comp.page
    panel = comp.open_popover(name)
    box = panel.bounding_box()
    trigger = page.locator(f"#{name}-toggle").bounding_box()
    column = page.locator("#map-tools").bounding_box()
    assert box["y"] == pytest.approx(trigger["y"], abs=0.5)
    assert column["x"] - (box["x"] + box["width"]) == pytest.approx(8, abs=0.5)
    assert box["x"] > 0

    page.mouse.click(box["x"] - 100, box["y"] + 200)
    expect(panel).to_be_hidden()
    expect(page.locator(f"#{name}-toggle")).to_have_attribute("aria-expanded", "false")


@pytest.mark.parametrize("name", ["search", "basemap"])
def test_popover_close_button_closes_it_and_focuses_its_trigger(comp, name):
    panel = comp.open_popover(name)
    panel.get_by_role("button", name="Schliessen").click()
    expect(panel).to_be_hidden()
    trigger = comp.page.locator(f"#{name}-toggle")
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(trigger).to_be_focused()


def test_only_one_popover_is_open_at_a_time(comp):
    search = comp.open_popover("search")
    comp.open_popover("basemap")
    expect(search).to_be_hidden()


def test_zoom_buttons_change_zoom(comp):
    page = comp.page
    zoom_before = page.evaluate("window.__testMap.getZoom()")
    page.locator(".maplibregl-ctrl-zoom-in").click()
    page.wait_for_function("z => window.__testMap.getZoom() > z + 0.5", arg=zoom_before)
    zoom_after = page.evaluate("window.__testMap.getZoom()")
    page.locator(".maplibregl-ctrl-zoom-out").click()
    page.wait_for_function("z => window.__testMap.getZoom() < z - 0.5", arg=zoom_after)


def test_coordinate_search_rejects_and_jumps(comp):
    page = comp.page
    comp.open_popover("search")
    expect(page.locator("#search-x")).to_be_focused()
    error = page.locator("#search-error")
    page.fill("#search-x", "1")
    page.fill("#search-y", "2")
    page.get_by_role("button", name="Springen").click()
    expect(error).to_contain_text("ausserhalb der Schweiz")

    page.fill("#search-x", "2600000")
    page.fill("#search-y", "1200000")
    page.press("#search-y", "Enter")
    expect(error).to_have_text("")
    # LV95 2600000/1200000 is the Bern origin, ~46.951 N / 7.439 E.
    page.wait_for_function(
        "() => { const c = window.__testMap.getCenter();"
        " return Math.abs(c.lat - 46.951) < 0.01 && Math.abs(c.lng - 7.439) < 0.01; }",
        timeout=15_000,
    )


def test_zoom_kanton_bern_resets_view(comp):
    page = comp.page
    page.evaluate("window.__testMap.jumpTo({center: [7.9, 46.5], zoom: 14})")
    page.get_by_role("button", name="Zoom Kanton Bern").click()
    page.wait_for_function(
        "() => { const c = window.__testMap.getCenter(), z = window.__testMap.getZoom();"
        " return Math.abs(c.lat - 46.8) < 0.05 && Math.abs(c.lng - 7.5) < 0.05 && Math.abs(z - 8) < 0.5; }",
        timeout=15_000,
    )
