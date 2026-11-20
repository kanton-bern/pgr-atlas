"""The few elements the app styles through its own classes (app/styles/app.css)
look as intended in the browser: Streamlit's own styles don't override them."""

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import VIEWS, active_nav, nav_link
from tests.lake_data import ANRISS_ID, GEBAEUDESCHATTEN_BUILDING

pytestmark = pytest.mark.e2e


def _style(locator, *props):
    return locator.evaluate(
        "(el, props) => props.map(p => getComputedStyle(el).getPropertyValue(p))", list(props)
    )


def _luminance(rgb: str) -> float:
    channels = [int(c) / 255 for c in re.findall(r"\d+", rgb)[:3]]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg: str, bg: str) -> float:
    light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_sidebar_logos_and_page_header_are_styled(app_page):
    sidebar = app_page.locator("[data-testid='stSidebar']")
    head = sidebar.locator(".pgr-sidebar-head")
    assert _style(head, "display", "flex-direction", "text-align") == ["flex", "column", "center"]
    # The title and the two logos are spaced evenly, not stacked tightly.
    assert float(_style(head, "row-gap")[0].removesuffix("px")) >= 20
    # The logos are served from app/static/ (enableStaticServing).
    for logo in ("img.pgr-logo-be", "img.pgr-logo-wide"):
        assert sidebar.locator(logo).evaluate("img => img.naturalWidth") > 0, logo
    # The app's name: black like the guide's logo caption (A137), but 24 px bold.
    title = sidebar.locator(".pgr-app-title")
    assert _style(title, "font-size", "font-weight", "color") == ["24px", "700", "rgb(0, 0, 0)"]
    assert title.locator(".pgr-app-topic").inner_text() == "Hangmuren"
    # The teal identity band across the top of the whole page.
    band = app_page.locator(".stApp").evaluate(
        """el => {
            const style = getComputedStyle(el, "::before");
            return [style.position, style.height, style.backgroundColor, style.width];
        }"""
    )
    assert band == ["fixed", "4px", "rgb(91, 125, 126)", f"{app_page.viewport_size['width']}px"]

    # The page title: the guide's H4 (24/28 px, 300), black.
    title = app_page.locator("h1.pgr-page-title")
    assert _style(title, "font-size", "line-height", "font-weight", "color") == [
        "24px",
        "28px",
        "300",
        "rgb(0, 0, 0)",
    ]
    hint = app_page.locator(".pgr-page-hint")
    assert _style(hint, "font-size", "color") == ["16px", "rgb(0, 0, 0)"]


# The URL path of each view (st.Page url_path in app.py), and the Anriss view.
_ROUTES = {
    "Overview (All Events)": "",
    "IFK": "ifk",
    "Raster-Karten": "raster-karten",
    "Raster-Derivate": "raster-derivate",
    "Gebäudeschatten": "gebaeudeschatten",
    "Specific Simulation": f"anriss?id={ANRISS_ID}",
}
_TITLES = {
    **{view: label for view, (label, _) in VIEWS.items()},
    "Gebäudeschatten": "Gebäudeschatten",
    "Specific Simulation": f"Anriss {ANRISS_ID}",
}


@pytest.mark.parametrize("view", list(_ROUTES))
def test_each_view_has_one_h1_and_marks_its_nav_link(page, app_url, view):
    """The page title is the page's only h1; the
    navigation is a ruled list and marks the open view with the red bar and
    weight 500."""
    page.goto(f"{app_url}/{_ROUTES[view]}")
    title = _TITLES[view]
    current = active_nav(page, title)
    current.wait_for(timeout=300_000)
    expect(page.locator("h1")).to_have_count(1)
    expect(page.locator("h1")).to_have_text(title)
    assert _style(current, "border-left") == ["4px solid rgb(234, 22, 31)"]
    assert _style(current.locator("p"), "font-weight", "color") == ["500", "rgb(0, 0, 0)"]
    # The other links are plain: no bar, normal weight.
    other = nav_link(
        page, "Simulierte Ereignisse" if view != "Overview (All Events)" else "IFK-Berechnung"
    )
    assert _style(other, "border-left-color")[0] == "rgba(0, 0, 0, 0)"
    # Every row, active or not, sits on a Line Grey rule.
    for link in (current, other):
        assert _style(link, "border-bottom") == ["1px solid rgba(112, 112, 112, 0.5)"]
    assert _style(other.locator("p"), "font-weight") == ["400"]
    # The rows tile: each starts where the one above ends, so the red bar spans
    # exactly its row and the text sits centred between two rules.
    boxes = page.locator(".st-key-pgr_nav [data-testid='stPageLink-NavLink']").evaluate_all(
        "els => els.map(el => el.getBoundingClientRect().toJSON())"
    )
    for upper, lower in zip(boxes, boxes[1:], strict=False):
        assert lower["top"] == pytest.approx(upper["bottom"], abs=0.5)


def test_page_uses_roboto_from_the_app(app_page):
    """Roboto comes from app/static/fonts/ (the theme's fontFaces), not a CDN."""
    loaded = app_page.evaluate(
        "() => document.fonts.ready.then(() => [...document.fonts]"
        ".filter(f => f.family === 'Roboto' && f.status === 'loaded').length)"
    )
    assert loaded > 0
    family = _style(app_page.locator(".stApp"), "font-family")[0]
    assert family.startswith("Roboto")


def test_keyboard_focus_is_visible(page, app_url):
    """A link focused by keyboard gets the black 2 px outline."""
    page.goto(app_url)
    first_nav = nav_link(page, "Simulierte Ereignisse")
    first_nav.wait_for(timeout=300_000)
    first_nav.focus()
    page.keyboard.press("Tab")
    focused = page.locator("a:focus-visible")
    expect(focused).to_have_text("IFK-Berechnung")
    assert _style(focused, "outline-style", "outline-width", "outline-color") == [
        "solid",
        "2px",
        "rgb(0, 0, 0)",
    ]


def test_experten_modus_keeps_the_sidebar_width(page, app_url):
    """The sidebar stays 300 px with Experten-Modus on and its editors open; the
    links and buttons fill it and the p_Ablauf buttons show their whole label."""
    page.goto(f"{app_url}/raster-karten")
    sidebar = page.locator("[data-testid='stSidebar']")
    toggle = sidebar.locator(".st-key-_expert_active label")
    toggle.wait_for(timeout=300_000)
    expect(sidebar).to_have_css("width", "300px")
    toggle.click()
    sidebar.locator("[data-testid='stExpander'] summary", has_text="p_Ablauf").click()
    sidebar.get_by_test_id("stDataFrame").wait_for(timeout=60_000)
    expect(sidebar).to_have_css("width", "300px")

    content = sidebar.get_by_test_id("stSidebarUserContent")
    assert content.evaluate("el => el.scrollWidth <= el.clientWidth")
    for key in ("zero", "normalize", "reset"):
        label = sidebar.locator(f".st-key-_expert_ablauf_{key}_btn").get_by_test_id(
            "stMarkdownContainer"
        )
        assert label.evaluate("el => el.scrollWidth <= el.clientWidth"), key
    content_width = content.evaluate(
        "el => { const s = getComputedStyle(el); "
        "return el.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight); }"
    )
    for element in (
        nav_link(page, "IFK-Berechnung"),
        sidebar.locator(".st-key-_raster_submit_btn button"),
    ):
        assert element.evaluate("el => el.getBoundingClientRect().width") == pytest.approx(
            content_width, abs=1
        ), element


_FOOT = ".st-key-pgr_sidebar_foot"

# The bottom of the sidebar's scroll area and of its foot, and of the last
# sidebar element above the foot.
_FOOT_BOXES = """() => {
  const scroller = document.querySelector('[data-testid="stSidebarContent"]');
  const wrapper = document.querySelector('.st-key-pgr_sidebar_foot').parentElement;
  return {
    overflows: scroller.scrollHeight > scroller.clientHeight,
    sidebar: scroller.getBoundingClientRect().bottom,
    foot: wrapper.getBoundingClientRect().toJSON(),
    above: wrapper.previousElementSibling.getBoundingClientRect().bottom,
  };
}"""


def test_sidebar_foot_stays_in_view_on_a_long_sidebar(page, app_url):
    """The version and DE | FR stay at the bottom of the sidebar, in view
    without scrolling it, and cover nothing at the end of the scroll."""
    page.set_viewport_size({"width": 1024, "height": 600})
    page.goto(f"{app_url}/raster-derivate")
    sidebar = page.locator("[data-testid='stSidebar']")
    version = sidebar.locator(f"{_FOOT} .pgr-version")
    version.wait_for(timeout=300_000)
    toggle = sidebar.locator(".st-key-pgr_lang").get_by_role("button", name="FR", exact=True)

    boxes = page.evaluate(_FOOT_BOXES)
    assert boxes["overflows"], "the sidebar must be longer than the viewport for this check"
    expect(version).to_be_in_viewport(ratio=1)
    expect(toggle).to_be_in_viewport(ratio=1)
    version_box = version.bounding_box()
    assert toggle.bounding_box()["y"] >= version_box["y"] + version_box["height"] - 0.5
    assert boxes["foot"]["bottom"] == pytest.approx(boxes["sidebar"], abs=1)

    sidebar.get_by_test_id("stSidebarContent").evaluate("el => el.scrollTo(0, el.scrollHeight)")
    boxes = page.evaluate(_FOOT_BOXES)
    assert boxes["foot"]["bottom"] == pytest.approx(boxes["sidebar"], abs=1)
    assert boxes["above"] <= boxes["foot"]["top"] + 0.5


def test_sidebar_foot_sits_at_the_bottom_of_a_short_sidebar(page, app_url):
    page.set_viewport_size({"width": 1024, "height": 1400})
    page.goto(app_url)
    page.locator(f"{_FOOT} .pgr-version").wait_for(timeout=300_000)
    boxes = page.evaluate(_FOOT_BOXES)
    assert not boxes["overflows"]
    assert boxes["foot"]["bottom"] == pytest.approx(boxes["sidebar"], abs=1)


def test_download_buttons_with_help_are_readable(page, app_url):
    """A button with help= sits in a tooltip wrapper; app.css must still reach it."""
    page.goto(f"{app_url}/gebaeudeschatten")
    sidebar = page.locator("[data-testid='stSidebar']")
    sidebar.get_by_text("800 m (ganze Simulation)").click(timeout=300_000)
    field = sidebar.get_by_label("Gebäude-ID (id_start)")
    field.fill(str(GEBAEUDESCHATTEN_BUILDING))
    # Streamlit's English "Press Enter to submit form" stays hidden.
    expect(sidebar.get_by_test_id("InputInstructions")).to_be_hidden()
    sidebar.get_by_role("button", name="Gebäude anzeigen").click()

    # Streamlit also renders a hidden copy of the button outside the tooltip.
    button = page.locator(".st-key-gs_building_tif button >> visible=true")
    button.wait_for(timeout=120_000)
    color, background = _style(button, "color", "background-color")
    assert _contrast(color, background) >= 4.5
