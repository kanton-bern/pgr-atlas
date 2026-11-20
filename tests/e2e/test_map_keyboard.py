"""The map chrome works by keyboard: the control column and its
popovers, the boxes' close buttons, the draw, variable and status
buttons. MapLibre's own controls speak German and the small buttons
are 24 x 24 px targets."""

import re

import pytest
from playwright.sync_api import FrameLocator, Locator, Page, expect

from tests.e2e.conftest import click_map_centre_until, jump_to, map_frame
from tests.lake_data import ANRISS_ID, ANRISS_LV95

pytestmark = pytest.mark.e2e

_OVERVIEW = "Overview (All Events)"
_ANRISS_MAP_TITLE = "anriss_map_component.anriss_result_map"
_MIN_TARGET_PX = 24
_COLLAPSED = re.compile(r"\bmc-collapsed\b")
# The control column, top to bottom.
_COLUMN = [
    "Hineinzoomen",
    "Herauszoomen",
    "Zoom Kanton Bern",
    "Koordinateneingabe (LV95)",
    "Hintergrundkarte",
]


def _tab_until(page: Page, frame: FrameLocator, selector: str, max_presses: int = 40):
    """Presses Tab until the focused element in `frame` matches `selector`."""
    for _ in range(max_presses):
        page.keyboard.press("Tab")
        if frame.locator(f"{selector}:focus").count():
            return
    pytest.fail(f"Tab never reached {selector} in {max_presses} presses")


def _expect_focus_ring(locator: Locator):
    expect(locator).to_be_focused()
    expect(locator).to_have_css("outline-style", "solid")
    expect(locator).to_have_css("outline-width", "2px")
    expect(locator).to_have_css("outline-color", "rgb(0, 0, 0)")


def _visible_basemap(frame: FrameLocator) -> list[str]:
    return frame.locator("body").evaluate(
        """() => ["lk", "relief", "osm"].filter(
            (bm) => window.debugMap.getLayoutProperty(`bg-${bm}`, "visibility") === "visible")"""
    )


def _pressed(buttons: Locator) -> list[str | None]:
    return buttons.evaluate_all("els => els.map(el => el.getAttribute('aria-pressed'))")


def _overview_column(app_page: Page) -> FrameLocator:
    frame = map_frame(app_page, _OVERVIEW)
    expect(frame.get_by_role("button", name="Hineinzoomen")).to_be_visible(timeout=60_000)
    return frame


def test_tab_reaches_every_button_of_the_control_column_in_order(app_page):
    frame = _overview_column(app_page)
    frame.get_by_role("button", name=_COLUMN[0]).focus()
    for name in _COLUMN[1:]:
        app_page.keyboard.press("Tab")
        _expect_focus_ring(frame.get_by_role("button", name=name, exact=True))


def test_basemap_popover_works_by_keyboard(app_page):
    frame = _overview_column(app_page)
    trigger = frame.get_by_role("button", name="Hintergrundkarte")
    trigger.focus()
    app_page.keyboard.press("Enter")
    expect(trigger).to_have_attribute("aria-expanded", "true")
    panel = frame.locator("#basemap-ctrl")
    expect(panel).to_be_visible()
    buttons = panel.locator(".bm-btn")

    # Focus starts on the basemap in use.
    _expect_focus_ring(frame.get_by_role("button", name="SwissTopo LK"))
    assert _pressed(buttons) == ["true", "false", "false"]
    assert _visible_basemap(frame) == ["lk"]

    app_page.keyboard.press("Tab")
    app_page.keyboard.press("Enter")
    expect(buttons.nth(1)).to_have_attribute("aria-pressed", "true")
    assert _pressed(buttons) == ["false", "true", "false"]
    assert _visible_basemap(frame) == ["relief"]

    app_page.keyboard.press("Tab")
    app_page.keyboard.press("Space")
    expect(buttons.nth(2)).to_have_attribute("aria-pressed", "true")
    assert _pressed(buttons) == ["false", "false", "true"]
    assert _visible_basemap(frame) == ["osm"]

    app_page.keyboard.press("Escape")
    expect(panel).to_be_hidden()
    expect(trigger).to_have_attribute("aria-expanded", "false")
    expect(trigger).to_be_focused()


def test_coordinate_popover_works_by_keyboard(app_page):
    frame = _overview_column(app_page)
    trigger = frame.get_by_role("button", name="Koordinateneingabe (LV95)")
    trigger.focus()
    app_page.keyboard.press("Space")
    expect(frame.locator("#search-ctrl")).to_be_visible()
    expect(frame.locator("#search-x")).to_be_focused()

    app_page.keyboard.type(str(ANRISS_LV95[0]))
    app_page.keyboard.press("Tab")
    app_page.keyboard.type(str(ANRISS_LV95[1]))
    app_page.keyboard.press("Enter")
    expect(frame.locator("#zoom-debug")).to_have_text("Zoomstufe = 15.80", timeout=15_000)

    app_page.keyboard.press("Escape")
    expect(frame.locator("#search-ctrl")).to_be_hidden()
    expect(trigger).to_be_focused()

    # "Zoom Kanton Bern", the button above, by keyboard.
    app_page.keyboard.press("Shift+Tab")
    expect(frame.get_by_role("button", name="Zoom Kanton Bern")).to_be_focused()
    app_page.keyboard.press("Enter")
    expect(frame.locator("#zoom-debug")).to_have_text("Zoomstufe = 8.00", timeout=15_000)


def test_box_closes_and_reopens_by_keyboard(app_page):
    frame = _overview_column(app_page)
    box = frame.locator("#legend")
    frame.get_by_role("button", name="Hintergrundkarte").focus()

    _tab_until(app_page, frame, "#legend .legend-close")
    expect(frame.locator(":focus")).to_have_accessible_name("Layer ausblenden")
    app_page.keyboard.press("Enter")
    expect(box).to_have_class(_COLLAPSED)
    chip = frame.get_by_role("button", name="Layer einblenden")
    expect(chip).to_be_focused()

    app_page.keyboard.press("Enter")
    expect(box).not_to_have_class(_COLLAPSED)
    expect(frame.locator("#legend .legend-close")).to_be_focused()


def test_draw_buttons_work_by_keyboard(app_page, go_to_view):
    view = "Raster-Derivate"
    go_to_view(view)
    frame = map_frame(app_page, view)
    rect = frame.get_by_role("button", name="📐 Rechteck zeichnen")
    poly = frame.get_by_role("button", name="⬠ Polygon zeichnen")
    expect(rect).to_have_attribute("aria-pressed", "false", timeout=60_000)

    rect.focus()
    app_page.keyboard.press("Enter")
    expect(rect).to_have_attribute("aria-pressed", "true")
    expect(frame.locator("#map")).to_have_class(re.compile(r"\bdrawing\b"))

    app_page.keyboard.press("Tab")
    _expect_focus_ring(poly)
    app_page.keyboard.press("Space")
    expect(poly).to_have_attribute("aria-pressed", "true")
    expect(rect).to_have_attribute("aria-pressed", "false")

    app_page.keyboard.press("Enter")
    expect(poly).to_have_attribute("aria-pressed", "false")
    expect(frame.locator("#map")).not_to_have_class(re.compile(r"\bdrawing\b"))


def test_variable_buttons_work_by_keyboard(page, app_url):
    page.goto(f"{app_url}/anriss?id={ANRISS_ID}")
    frame = page.frame_locator(f"iframe[title='{_ANRISS_MAP_TITLE}']")
    buttons = frame.locator("#var-btns .var-btn")
    expect(buttons.first).to_have_attribute("aria-pressed", "true", timeout=300_000)

    buttons.first.focus()
    page.keyboard.press("Tab")
    _expect_focus_ring(buttons.nth(1))
    page.keyboard.press("Enter")
    expect(buttons.nth(1)).to_have_attribute("aria-pressed", "true")
    assert _pressed(buttons)[0] == "false"
    # Python reruns with the picked variable; the legend follows.
    expect(frame.locator("#vl-title")).to_have_text("Fliessgeschwindigkeit [m/s]", timeout=60_000)


@pytest.mark.parametrize("view", [_OVERVIEW, "IFK", "Raster-Karten"])
def test_maplibre_controls_are_german(app_page, go_to_view, view):
    if view != _OVERVIEW:
        go_to_view(view)
    frame = map_frame(app_page, view)
    expect(frame.get_by_role("button", name="Hineinzoomen")).to_be_visible(timeout=60_000)
    expect(frame.get_by_role("button", name="Herauszoomen")).to_be_visible()
    expect(frame.locator("canvas.maplibregl-canvas")).to_have_attribute("aria-label", "Karte")
    expect(frame.get_by_role("button", name="Zoom in")).to_have_count(0)


def _size(locator) -> tuple[float, float]:
    box = locator.bounding_box()
    assert box is not None
    return box["width"], box["height"]


def _assert_target_size(locator: Locator, label: object = None):
    width, height = _size(locator)
    assert width >= _MIN_TARGET_PX and height >= _MIN_TARGET_PX, (label, width, height)


def test_column_buttons_are_at_least_24px(app_page):
    frame = _overview_column(app_page)
    for name in _COLUMN:
        _assert_target_size(frame.get_by_role("button", name=name, exact=True), name)


def test_close_and_reopen_targets_are_at_least_24px(app_page):
    """Every box's "x" and its reopen chip: 24 x 24 px, and a plain glyph
    without a button background, also in boxes that style their own buttons."""
    frame = _overview_column(app_page)
    closers = frame.locator(".legend-close:visible")
    count = closers.count()
    assert count >= 1  # the layer box
    for i in range(count):
        closer = closers.nth(i)
        _assert_target_size(closer, i)
        expect(closer).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        expect(closer).to_have_css("border-top-width", "0px")

    for _ in range(count):
        closers.first.click()
    chips = frame.locator(".legend-open:visible")
    expect(chips).to_have_count(count)
    for i in range(count):
        chip = chips.nth(i)
        _assert_target_size(chip, i)
        expect(chip).to_have_css("background-color", "rgba(0, 0, 0, 0)")


def test_close_and_reopen_hover_looks_the_same_in_every_box(app_page):
    """The "x" and the chip have the same hover look in every box; the
    collapsed box is exactly as high as its chip."""
    frame = _overview_column(app_page)
    closers = frame.locator(".legend-close:visible")
    count = closers.count()
    for i in range(count):
        closers.nth(i).hover()
        expect(closers.nth(i)).to_have_css("background-color", "rgba(0, 0, 0, 0.08)")

    for _ in range(count):
        closers.first.click()
    chips = frame.locator(".legend-open:visible")
    for i in range(count):
        chip = chips.nth(i)
        chip.hover()
        expect(chip).to_have_css("background-color", "rgba(0, 0, 0, 0)")
        box_height = chip.evaluate("el => el.parentElement.getBoundingClientRect().height")
        assert box_height == pytest.approx(_size(chip)[1], abs=0.5), (i, box_height)


def test_popup_buttons_are_german_at_least_24px_and_reachable(app_page):
    frame = map_frame(app_page, _OVERVIEW)
    jump_to(frame, ANRISS_LV95, "15.80")
    open_btn = frame.locator(".popup-open-btn")
    click_map_centre_until(app_page, _OVERVIEW, open_btn)
    _assert_target_size(open_btn, "Anriss öffnen")
    expect(open_btn).to_have_attribute("type", "button")
    close = frame.locator(".maplibregl-popup", has=open_btn).get_by_role(
        "button", name="Popup schliessen"
    )
    _assert_target_size(close, "Popup schliessen")
    # MapLibre puts its close button after the content.
    open_btn.focus()
    app_page.keyboard.press("Tab")
    _expect_focus_ring(close)
    app_page.keyboard.press("Shift+Tab")
    _expect_focus_ring(open_btn)

    close.focus()
    app_page.keyboard.press("Enter")
    expect(open_btn).to_have_count(0)
