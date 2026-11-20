"""User flows from docs/frontend-app/behavior-inventory.md that need a browser
and the real data: map clicks that reach Python, results drawn back on the map,
and the way back. The places come from tests/lake_data.py."""

import json
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import (
    FRENCH_MARKER,
    VIEWS,
    active_nav,
    assert_no_streamlit_exception,
    click_map_centre_until,
    jump_to,
    map_frame,
    nav_link,
    wait_for_rerun,
)
from tests.lake_data import ANRISS_ID, ANRISS_LV95, IFK_PIXEL, RASTER_SELECTION

pytestmark = pytest.mark.e2e

# The Anriss view's map (anriss_map_component.py's declare_component name).
_ANRISS_MAP_TITLE = "anriss_map_component.anriss_result_map"

# Zoom after a coordinate search, per view (SEARCH_ZOOM in each index.html).
_SEARCH_ZOOM = {"Overview (All Events)": "15.80", "IFK": "17.10", "Raster-Karten": "14.90"}


def _ifk_pixel_query(pixel):
    """A regex for the end of an IFK URL that selects `pixel` (LV95)."""
    return re.escape(f"/ifk?x={pixel[0]:.1f}&y={pixel[1]:.1f}") + "$"


@pytest.mark.parametrize("view", ["Overview (All Events)", "IFK", "Raster-Karten"])
def test_view_loads_vector_tiles_from_the_tile_sidecar(app_page, go_to_view, view):
    if view == "Overview (All Events)":
        go_to_view("IFK")  # the Simulierte Ereignisse map was already loaded by the fixture
    with app_page.expect_response(
        lambda r: ".pmtiles" in r.url and r.status in (200, 206), timeout=60_000
    ):
        go_to_view(view)
    frame = map_frame(app_page, view)
    expect(frame.locator("#legend")).to_be_visible(timeout=30_000)
    app_page.wait_for_timeout(2_000)  # a failed tile would show its error by now
    expect(frame.locator("#map-status.error")).to_have_count(0)


def test_overview_popup_opens_the_anriss_and_back_restores_the_map(app_page, go_to_view):
    view = "Overview (All Events)"
    frame = map_frame(app_page, view)
    jump_to(frame, ANRISS_LV95, _SEARCH_ZOOM[view])
    open_btn = frame.locator(".popup-open-btn", has_text="Anriss öffnen")
    click_map_centre_until(app_page, view, open_btn)
    anriss_id = open_btn.get_attribute("data-id")
    open_btn.click()

    expect(active_nav(app_page, f"Anriss {anriss_id}")).to_be_visible(timeout=60_000)
    expect(app_page).to_have_url(re.compile(rf"/anriss\?id={anriss_id}$"))
    back = app_page.get_by_role("button", name="← Anriss abwählen")
    expect(back).to_be_visible(timeout=180_000)
    # Below the Rohdaten, whose probability join can take a while under load.
    expect(app_page.locator("[data-testid='stMetric']", has_text="Datenpunkte")).to_be_visible(
        timeout=60_000
    )
    anriss_map = app_page.frame_locator(f"iframe[title='{_ANRISS_MAP_TITLE}']")
    expect(anriss_map.locator("#layer-rows")).to_be_visible(timeout=30_000)
    assert_no_streamlit_exception(app_page)

    back.click()
    expect(active_nav(app_page, VIEWS[view][0])).to_be_visible(timeout=60_000)
    wait_for_rerun(app_page)
    expect(map_frame(app_page, view).locator("#zoom-debug")).to_have_text(
        f"Zoomstufe = {_SEARCH_ZOOM[view]}", timeout=30_000
    )
    expect(nav_link(app_page, f"Anriss {anriss_id}")).to_have_count(0)
    # The URL holds that map view too, so a reload or a shared link opens it.
    expect(app_page).to_have_url(re.compile(rf"\?z={_SEARCH_ZOOM[view]}&lat=[\d.]+&lon=[\d.]+$"))


def test_ifk_pixel_click_shows_curves_opens_an_anriss_and_deselects(app_page, go_to_view):
    go_to_view("IFK")
    frame = map_frame(app_page, "IFK")
    jump_to(frame, IFK_PIXEL, _SEARCH_ZOOM["IFK"])
    compute_btn = frame.locator(".popup-open-btn", has_text="IFK berechnen")
    click_map_centre_until(app_page, "IFK", compute_btn)
    expect(frame.locator(".maplibregl-popup")).to_contain_text(
        f"X: {IFK_PIXEL[0]:.1f}, Y: {IFK_PIXEL[1]:.1f}"
    )
    compute_btn.click()

    charts = app_page.locator("[data-testid='stVegaLiteChart']")
    expect(charts).to_have_count(3, timeout=180_000)
    rohdaten = app_page.locator("[data-testid='stDownloadButton']", has_text="Rohdaten (CSV)")
    expect(rohdaten).to_be_visible()
    expect(frame.locator("#anriss-legend")).to_be_visible(timeout=30_000)
    expect(app_page).to_have_url(re.compile(_ifk_pixel_query(IFK_PIXEL)))
    assert_no_streamlit_exception(app_page)

    # The contributing Anrisse are drawn as circles; open one from its popup.
    jump_to(frame, ANRISS_LV95, _SEARCH_ZOOM["IFK"])
    open_btn = frame.locator(".popup-open-btn", has_text="Anriss öffnen")
    click_map_centre_until(app_page, "IFK", open_btn)
    anriss_id = open_btn.get_attribute("data-anriss-id")
    open_btn.click()

    expect(active_nav(app_page, f"Anriss {anriss_id}")).to_be_visible(timeout=60_000)
    expect(app_page).to_have_url(re.compile(rf"/anriss\?id={anriss_id}$"))
    back = app_page.get_by_role("button", name="← Anriss abwählen")
    expect(back).to_be_visible(timeout=180_000)
    back.click()
    expect(active_nav(app_page, VIEWS["IFK"][0])).to_be_visible(timeout=60_000)
    # The pixel is still selected, and the URL holds it.
    expect(charts).to_have_count(3, timeout=180_000)
    expect(app_page).to_have_url(re.compile(_ifk_pixel_query(IFK_PIXEL)))
    assert_no_streamlit_exception(app_page)

    app_page.get_by_role("button", name="← Pixel abwählen").click()
    wait_for_rerun(app_page)
    expect(charts).to_have_count(0)
    expect(app_page).to_have_url(re.compile(r"/ifk$"))
    assert_no_streamlit_exception(app_page)


def test_switching_the_language_keeps_the_map_and_the_selected_pixel(app_page, go_to_view):
    """I18N-1: a language click must not reset the map. The map's iframe keeps
    its window (the marker set below survives), its zoom and the pixel, and
    its texts and numbers change to French."""
    go_to_view("IFK")
    frame = map_frame(app_page, "IFK")
    jump_to(frame, IFK_PIXEL, _SEARCH_ZOOM["IFK"])
    compute_btn = frame.locator(".popup-open-btn", has_text="IFK berechnen")
    click_map_centre_until(app_page, "IFK", compute_btn)
    compute_btn.click()
    charts = app_page.locator("[data-testid='stVegaLiteChart']")
    expect(charts).to_have_count(3, timeout=180_000)
    frame.locator("#map").evaluate("() => { window.__beforeLanguageSwitch = true; }")
    zoom = frame.locator("#zoom-debug").inner_text()

    app_page.locator(".st-key-pgr_lang").get_by_role("button", name="FR", exact=True).click()
    expect(active_nav(app_page, FRENCH_MARKER + VIEWS["IFK"][0])).to_be_visible(timeout=60_000)
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)

    expect(app_page).to_have_url(re.compile(re.escape(f"/ifk?x={IFK_PIXEL[0]:.1f}&y=")))
    expect(app_page).to_have_url(re.compile(r"lang=fr"))
    assert frame.locator("#map").evaluate("() => window.__beforeLanguageSwitch") is True
    # The same zoom, in a French text with a decimal comma: "[FR] Zoomstufe = 18,00".
    expect(frame.locator("#zoom-debug")).to_have_text(FRENCH_MARKER + zoom.replace(".", ","))
    expect(frame.get_by_role("button", name=FRENCH_MARKER + "Hineinzoomen")).to_be_visible()
    expect(charts).to_have_count(3)


def test_download_gate_link_opens_rechtliches_in_the_same_session(page, app_url):
    """The dialog's linked phrase opens Rechtliches at «Simulationsdaten» in the
    same tab and session, in the session's language, as the footer link does,
    and downloads nothing. Its close cross goes back to the Anriss, with its URL."""
    downloads = []
    page.on("download", lambda download: downloads.append(download))
    page.goto(f"{app_url}/anriss?id={ANRISS_ID}&lang=fr")
    button = page.locator("[data-testid='stDownloadButton'] button").first
    expect(button).to_be_visible(timeout=300_000)
    wait_for_rerun(page)
    button.click()
    page.locator("dialog").get_by_role("link").click()

    expect(page).to_have_url(f"{app_url}/rechtliches?lang=fr#donnees-de-simulation")
    expect(page.locator("#donnees-de-simulation")).to_be_in_viewport()
    # Only this session knows the Anriss: a new one would not list it.
    expect(nav_link(page, str(ANRISS_ID))).to_be_visible()
    assert len(page.context.pages) == 1
    assert downloads == []

    page.get_by_role("button", name="✕").first.click()
    expect(active_nav(page, str(ANRISS_ID))).to_be_visible(timeout=60_000)
    expect(page).to_have_url(f"{app_url}/anriss?id={ANRISS_ID}&lang=fr")
    assert_no_streamlit_exception(page)


def _go_to(app_page, nav_label: str):
    """Opens a view by its nav label; also those without a map in VIEWS."""
    nav_link(app_page, nav_label).click()
    expect(active_nav(app_page, nav_label)).to_be_visible(timeout=60_000)
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)


def _switch_language(app_page, lang: str, nav_label: str):
    app_page.locator(".st-key-pgr_lang").get_by_role("button", name=lang, exact=True).click()
    marker = FRENCH_MARKER if lang == "FR" else ""
    expect(active_nav(app_page, marker + nav_label)).to_be_visible(timeout=60_000)
    wait_for_rerun(app_page)
    assert_no_streamlit_exception(app_page)


@pytest.mark.parametrize(
    ("nav_label", "pick", "picked"),
    [
        ("Gebäudeschatten", "radio", "Ohne eigenes Gebäude"),
        ("Raster-Karten (ad hoc)", "option", "Druck"),
    ],
)
def test_switching_the_language_keeps_the_sidebar_picks(app_page, nav_label, pick, picked):
    """I18N-1 for the sidebar: a radio or a select box sends its pick as the
    label it shows, which a language switch changes. The pick stays, shown in
    the new language, and back."""
    sidebar = app_page.locator("[data-testid='stSidebar']")
    _go_to(app_page, nav_label)
    if pick == "option":
        sidebar.get_by_role("combobox", name="Variable").click()
    app_page.get_by_role(pick, name=picked, exact=True).click(force=pick == "radio")
    wait_for_rerun(app_page)

    for lang, marker in (("FR", FRENCH_MARKER), ("DE", "")):
        _switch_language(app_page, lang, nav_label)
        if pick == "radio":
            radio = sidebar.get_by_role("radio", name=marker + picked, exact=True)
            expect(radio).to_be_checked()
        else:
            box = sidebar.get_by_role("combobox", name=marker + "Variable")
            expect(box).to_have_value(marker + picked)


def test_ifk_summary_copies_the_pixel_link_by_keyboard(page, app_url):
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=app_url)
    e, n = IFK_PIXEL
    page.goto(f"{app_url}/ifk?x={e}&y={n}")
    expect(page.locator("[data-testid='stVegaLiteChart']")).to_have_count(3, timeout=300_000)
    summary = page.locator(".st-key-ifk_summary")
    expect(summary).to_contain_text("Pixel (LV95) 2'598'502.5 / 1'137'502.5")
    expect(summary).to_contain_text("beitragende Anrisse")
    expect(summary).to_contain_text("Höchste Wiederkehrperiode")

    # Tab from the row's first button (the return period's help icon); Enter copies.
    summary.locator("button").first.focus()
    page.keyboard.press("Tab")
    copy = summary.get_by_role("button", name="Link kopieren")
    expect(copy).to_be_focused()
    page.keyboard.press("Enter")
    expect(summary.get_by_role("status")).to_have_text("Link kopiert")
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied == f"{app_url}/ifk?x={e}&y={n}"
    assert_no_streamlit_exception(page)


def test_ifk_summary_says_where_the_link_is_when_the_clipboard_is_missing(page, app_url):
    # Plain HTTP on a non-localhost host has no navigator.clipboard.
    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    e, n = IFK_PIXEL
    page.goto(f"{app_url}/ifk?x={e}&y={n}")
    summary = page.locator(".st-key-ifk_summary")
    copy = summary.get_by_role("button", name="Link kopieren")
    expect(copy).to_be_visible(timeout=300_000)
    copy.click()
    status = summary.get_by_role("status")
    expect(status).to_contain_text("Kopieren nicht möglich")
    page.wait_for_timeout(4_500)  # longer than "Link kopiert" stays
    expect(status).to_contain_text("Kopieren nicht möglich")
    assert_no_streamlit_exception(page)


@pytest.fixture()
def lv95_geojson_without_crs(tmp_path):
    """The raster test area as GeoJSON in LV95 metres, with no `crs` member."""
    path = tmp_path / "gebiet.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [RASTER_SELECTION["ring"]]},
                    }
                ],
            }
        )
    )
    return path


def test_raster_karten_mode_a_on_an_uploaded_area(app_page, go_to_view, lv95_geojson_without_crs):
    go_to_view("Raster-Karten")
    sidebar = app_page.locator("[data-testid='stSidebar']")
    sidebar.locator("[data-testid='stExpander'] summary", has_text="Gebiet hochladen").click()
    uploader = sidebar.locator("[data-testid='stFileUploaderDropzoneInput']")
    uploader.set_input_files(lv95_geojson_without_crs)

    # GeoJSON without a crs member reads as WGS84, which lands far outside
    # Switzerland: the app asks for the right system.
    expect(sidebar.get_by_text("ausserhalb der Schweiz")).to_be_visible(timeout=60_000)
    wait_for_rerun(app_page)
    # Streamlit 1.64's selectbox is a combobox, opened by its arrow button.
    # Right after the upload a click on it is sometimes lost, or the list closes
    # again before its options appear, so open it until the option shows.
    crs = sidebar.locator("[data-testid='stSelectbox']", has_text="Koordinatensystem der Datei")
    lv95 = app_page.get_by_role("option", name="LV95 (EPSG:2056)")
    for _ in range(3):
        crs.get_by_role("button", name="Open").click()
        try:
            expect(lv95).to_be_visible(timeout=5_000)
            break
        except AssertionError:
            continue
    else:
        pytest.fail("The CRS list did not show its options after 3 clicks on its arrow button")
    lv95.click()
    sidebar.get_by_role("button", name="Übernehmen").click()
    expect(sidebar.get_by_text("Erfolgreich hochgeladen")).to_be_visible(timeout=60_000)
    expect(sidebar.get_by_text("Polygon (4 Eckpunkte)")).to_be_visible()

    threshold = sidebar.get_by_label("Schwellenwert [m]")
    threshold.fill("0.1")
    threshold.press("Enter")
    wait_for_rerun(app_page)
    # The job's progress shows in a card above the map and its downloads below
    # it. The card pushes the map down while the job runs and is gone once the
    # result is there, so the map ends up where it started.
    map_iframe = app_page.locator(f"iframe[title='{VIEWS['Raster-Karten'][1]}']")
    map_box_before = map_iframe.bounding_box()
    main = app_page.locator("[data-testid='stMain']")
    # The map loads the overlay image from the job route, not from its render args.
    with app_page.expect_response(
        lambda r: "/job/" in r.url and r.url.endswith("/depth.png"), timeout=300_000
    ) as overlay:
        sidebar.get_by_role("button", name="Raster erzeugen").click()
    assert overlay.value.ok

    expect(main.get_by_text("1 Raster erzeugt")).to_be_visible(timeout=300_000)
    assert map_iframe.bounding_box() == map_box_before
    # The GeoTIFF is a link to derivate_bbox_server.py's /job/<id>/<var>.tif.
    link = main.locator(
        "[data-testid='stLinkButton'] a", has_text="Fliesstiefe ≥ 0.1 m, Wiederkehrperiode (GeoTIFF"
    )
    expect(link).to_be_visible()
    expect(main.get_by_text("Datei: adhoc_wiederkehrperiode_")).to_be_visible()
    download = app_page.request.get(link.get_attribute("href"))
    assert download.ok
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="adhoc_wiederkehrperiode_'
    )
    frame = map_frame(app_page, "Raster-Karten")
    expect(frame.locator("#raster-legend")).to_be_visible(timeout=30_000)
    assert_no_streamlit_exception(app_page)

    sidebar.get_by_role("button", name="Zurücksetzen").click()
    wait_for_rerun(app_page)
    expect(app_page.get_by_text("1 Raster erzeugt")).to_have_count(0)
    expect(frame.locator("#raster-legend")).to_be_hidden()
    expect(sidebar.get_by_text("Gebiet auf der Karte zeichnen")).to_be_visible()


def test_ifk_of_a_linked_rectangle_shows_curves_the_outline_and_the_rohdaten(page, app_url):
    e, n = IFK_PIXEL
    page.goto(f"{app_url}/ifk?xmin={e - 50}&ymin={n - 50}&xmax={e + 50}&ymax={n + 50}")
    sidebar = page.locator("[data-testid='stSidebar']")
    submit = sidebar.get_by_role("button", name="IFK des Gebiets berechnen")
    # The link only selects the rectangle: its size shows, nothing is computed.
    expect(sidebar.get_by_text("Rechteck: 105 m × 105 m")).to_be_visible(timeout=120_000)
    expect(page.locator("[data-testid='stVegaLiteChart']")).to_have_count(0)

    submit.click()
    expect(page.locator("[data-testid='stVegaLiteChart']")).to_have_count(3, timeout=300_000)
    expect(page.get_by_text("jede Simulation zählt einmal")).to_be_visible()
    frame = map_frame(page, "IFK")
    expect(frame.locator("#anriss-outline-row")).to_be_visible(timeout=30_000)
    expect(frame.locator("#bbox-readout")).to_have_text("105 m × 105 m · 11'025 m²")
    # The Rohdaten are a link to derivate_bbox_server.py's /file/<id>.
    link = page.locator("[data-testid='stLinkButton'] a", has_text="Rohdaten (CSV)")
    download = page.request.get(link.get_attribute("href"))
    assert download.ok
    assert download.headers["content-disposition"].startswith(
        'attachment; filename="ifk_gebiet_rohdaten_'
    )
    assert download.body().startswith(b"\xef\xbb\xbfid_prozessquelle,id_anriss,")
    assert_no_streamlit_exception(page)

    sidebar.get_by_role("button", name="Zurücksetzen").click()
    expect(page.locator("[data-testid='stVegaLiteChart']")).to_have_count(0, timeout=60_000)
    expect(page).to_have_url(f"{app_url}/ifk")
