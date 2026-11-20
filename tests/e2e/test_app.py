"""Full-app smoke tests: the app boots, the sidebar collapses/expands, every
view is reachable from the sidebar nav and mounts its map, URLs open their
view, and the map's legend chrome works inside the real Streamlit iframe."""

import pytest
from playwright.sync_api import expect

from tests.lake_data import ANRISS_ID, IFK_PIXEL

from .conftest import (
    VIEWS,
    active_nav,
    assert_no_streamlit_exception,
    nav_link,
    wait_for_rerun,
)

pytestmark = pytest.mark.e2e


def test_app_boots_on_overview(app_page):
    expect(app_page).to_have_title("PGR-Atlas Hangmuren")
    for label, _ in VIEWS.values():
        expect(nav_link(app_page, label)).to_be_visible()
    expect(app_page.locator(f"iframe[title='{VIEWS['Overview (All Events)'][1]}']")).to_be_visible()
    assert app_page.js_errors == []


def test_sidebar_collapses_and_expands(app_page):
    sidebar = app_page.locator("[data-testid='stSidebar']")
    expect(sidebar).to_have_attribute("data-collapsed", "false")

    sidebar.hover()
    app_page.locator("[data-testid='stSidebarCollapseButton'] button").click()
    expect(sidebar).to_have_attribute("data-collapsed", "true")
    expect(sidebar).not_to_be_in_viewport()

    app_page.locator("[data-testid='stExpandSidebarButton']").click()
    expect(sidebar).to_have_attribute("data-collapsed", "false")
    expect(sidebar).to_be_in_viewport()


def _expect_map_mounted(page, view):
    iframe = page.locator(f"iframe[title='{VIEWS[view][1]}']")
    if view == "Raster-Derivate":
        # Only has a map once precomputed rasters exist in the bucket.
        no_data = page.locator(
            "[data-testid='stAlertContainer']", has_text="liegen noch keine Daten vor"
        )
        expect(iframe.or_(no_data).first).to_be_visible(timeout=60_000)
        if not iframe.count():
            return
    expect(iframe).to_be_visible(timeout=60_000)
    frame = page.frame_locator(f"iframe[title='{VIEWS[view][1]}']")
    expect(frame.locator("#legend")).to_be_visible(timeout=30_000)
    expect(frame.locator("#map-tools")).to_be_visible(timeout=30_000)


def test_nav_round_trip_through_all_views(app_page, go_to_view):
    for view in [*VIEWS, "Overview (All Events)"]:
        go_to_view(view)
        _expect_map_mounted(app_page, view)
    assert app_page.js_errors == []


# The URL path of each view's page (st.Page url_path in app.py; Simulierte Ereignisse is the default).
_URL_PATHS = {
    "Overview (All Events)": "",
    "IFK": "ifk",
    "Raster-Karten": "raster-karten",
    "Raster-Derivate": "raster-derivate",
}


def _expect_on_view(page, app_url, view, timeout=60_000, query=""):
    label, _ = VIEWS[view]
    expect(active_nav(page, label)).to_be_visible(timeout=timeout)
    expect(page).to_have_url(f"{app_url}/{_URL_PATHS[view]}{query}")


# A new session: the first one after the app starts reads the catalog from S3.
_NEW_SESSION_TIMEOUT_MS = 300_000


# /ifk is opened by test_ifk_url_with_a_pixel_selects_it, /anriss by the test after it.
@pytest.mark.parametrize("view", ["Raster-Karten", "Raster-Derivate"])
def test_view_url_opens_the_view(page, app_url, view):
    page.goto(f"{app_url}/{_URL_PATHS[view]}")
    _expect_on_view(page, app_url, view, _NEW_SESSION_TIMEOUT_MS)
    wait_for_rerun(page)
    assert_no_streamlit_exception(page)


def test_overview_url_with_a_map_view_starts_the_map_there(page, app_url):
    page.goto(f"{app_url}/?z=12.5&lat=46.75&lon=7.63")
    _expect_on_view(
        page,
        app_url,
        "Overview (All Events)",
        _NEW_SESSION_TIMEOUT_MS,
        query="?z=12.5&lat=46.75&lon=7.63",
    )
    frame = page.frame_locator(f"iframe[title='{VIEWS['Overview (All Events)'][1]}']")
    expect(frame.locator("#zoom-debug")).to_have_text("Zoomstufe = 12.50", timeout=30_000)
    assert_no_streamlit_exception(page)


def test_ifk_url_with_a_pixel_selects_it(page, app_url):
    query = f"?x={IFK_PIXEL[0]}&y={IFK_PIXEL[1]}"
    page.goto(f"{app_url}/ifk{query}")
    _expect_on_view(page, app_url, "IFK", _NEW_SESSION_TIMEOUT_MS, query=query)
    expect(page.locator("[data-testid='stVegaLiteChart']")).to_have_count(3, timeout=180_000)
    assert_no_streamlit_exception(page)


def test_clicking_the_active_nav_link_keeps_the_selection_in_the_url(page, app_url):
    """The open view's own link reruns it with its URL as it was: the pixel the
    view still shows stays in the URL, so reload and shared links keep it."""
    query = f"?x={IFK_PIXEL[0]}&y={IFK_PIXEL[1]}"
    page.goto(f"{app_url}/ifk{query}")
    charts = page.locator("[data-testid='stVegaLiteChart']")
    expect(charts).to_have_count(3, timeout=_NEW_SESSION_TIMEOUT_MS)
    url = page.url
    active_nav(page, VIEWS["IFK"][0]).click()
    # The URL already matches, so expect() alone would pass before the rerun.
    page.wait_for_timeout(2_000)
    wait_for_rerun(page)
    expect(page).to_have_url(url)
    expect(charts).to_have_count(3)
    assert_no_streamlit_exception(page)


def test_anriss_url_with_an_id_opens_that_anriss(page, app_url):
    page.goto(f"{app_url}/anriss?id={ANRISS_ID}")
    expect(active_nav(page, f"Anriss {ANRISS_ID}")).to_be_visible(timeout=_NEW_SESSION_TIMEOUT_MS)
    expect(page.get_by_role("button", name="← Anriss abwählen")).to_be_visible(timeout=180_000)
    # Below the Rohdaten, whose probability join can take a while under load.
    expect(page.locator("[data-testid='stMetric']", has_text="Datenpunkte")).to_be_visible(
        timeout=60_000
    )
    expect(page).to_have_url(f"{app_url}/anriss?id={ANRISS_ID}")
    assert_no_streamlit_exception(page)


def test_browser_back_and_forward_move_between_views(app_page, app_url, go_to_view):
    # Two steps each way: before Streamlit 1.64, every st.switch_page added two
    # history entries, so every other Back stayed on the same view.
    go_to_view("IFK")
    _expect_on_view(app_page, app_url, "IFK")
    go_to_view("Raster-Karten")
    _expect_on_view(app_page, app_url, "Raster-Karten")
    app_page.go_back()
    _expect_on_view(app_page, app_url, "IFK")
    app_page.go_back()
    _expect_on_view(app_page, app_url, "Overview (All Events)")
    app_page.go_forward()
    _expect_on_view(app_page, app_url, "IFK")
    app_page.go_forward()
    _expect_on_view(app_page, app_url, "Raster-Karten")
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)


def test_map_legend_and_toggles_inside_app(app_page):
    view = "Overview (All Events)"  # app_page opens on Simulierte Ereignisse (test_app_boots_on_overview)
    frame = app_page.frame_locator(f"iframe[title='{VIEWS[view][1]}']")
    frame.get_by_role("button", name="Hintergrundkarte").click(timeout=30_000)
    expect(frame.locator("#basemap-ctrl")).to_be_visible()

    for basemap in ("relief", "osm", "lk"):
        button = frame.locator(f"#basemap-ctrl .bm-btn[data-bm='{basemap}']")
        button.click()
        expect(button).to_contain_class("active")

    gold = frame.locator("#gold-toggle")
    gold.uncheck()
    expect(gold).not_to_be_checked()
    gold.check()

    legend = frame.locator("#legend")
    legend.locator(".legend-close").click()
    expect(legend.locator(".legend-row").first).to_be_hidden()
    expect(legend.locator(".legend-open")).to_be_visible()
    assert_no_streamlit_exception(app_page)


def test_experten_modus_toggle_and_expanders(app_page, go_to_view):
    go_to_view("IFK")
    sidebar = app_page.locator("[data-testid='stSidebar']")
    toggle = sidebar.locator("[data-testid='stCheckbox']", has_text="Experten-Modus")
    toggle.click()
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)

    expanders = sidebar.locator("[data-testid='stExpander'] summary")
    expect(expanders.first).to_be_visible()
    for i in range(expanders.count()):
        expanders.nth(i).click()
        expect(sidebar.locator("[data-testid='stExpanderDetails']").nth(i)).to_be_visible()
    assert_no_streamlit_exception(app_page)

    toggle.click()
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)
