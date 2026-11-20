"""Fixtures for the full-app tests.

By default this starts the app itself via app/run_app.py (the container
entrypoint: loads app/../.env, starts pmtiles/derivate-bbox servers, then
Streamlit) on free ports. Set PGR_ATLAS_URL to test an already-running
instance instead (a local dev server, or a Bedag stage).

The app reads the data lake at startup, so it needs working S3 credentials
(PROBE_S3_ACCESS_KEY_ID / PROBE_S3_SECRET_ACCESS_KEY) for the
`adelboden-test` bucket, the default here; PROBE_S3_BUCKET
overrides it. The flows in test_flows.py rely on the fixed places in
tests/lake_data.py, which exist in that bucket.

The app this suite starts has a French text for every entry (french_texts_file),
so the language toggle shows; German stays the default.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import FrameLocator, Locator, Page, expect

import ui_text
from tests.lake_data import TEST_BUCKET

APP_DIR = Path(__file__).resolve().parents[2] / "app"
_app_log: Path | None = None  # set when this suite started the app itself

# (nav link label, component iframe title) per view -- see app.py's
# _PAGES and each *_component.py's declare_component() name.
VIEWS = {
    "Overview (All Events)": ("Simulierte Ereignisse", "overview_component.maplibre_overview"),
    "IFK": ("IFK-Berechnung", "ifk_map_component.ifk_pixel_map"),
    "Raster-Karten": ("Raster-Karten (ad hoc)", "raster_bbox_component.raster_bbox_map"),
    "Raster-Derivate": ("Raster-Derivate", "raster_bbox_component.raster_bbox_map"),
}


# Every French text of the app this suite starts: the German one after this
# marker, so a test sees which language a text is in.
FRENCH_MARKER = "[FR] "


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def french_texts_file(folder: Path) -> Path:
    """A copy of app/texts.toml with a French text for every entry, so the app
    offers both languages (ui_text.languages). The placeholders stay."""
    texts = ui_text.load_texts(ui_text.TEXTS_PATH)
    lines = []
    for key, entry in texts.items():
        german = entry["de"]
        lines += [
            f"[{key}]",
            f"de = {json.dumps(german, ensure_ascii=False)}",
            f"fr = {json.dumps(FRENCH_MARKER + german, ensure_ascii=False)}",
            "",
        ]
    path = folder / "texts.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def app_url(tmp_path_factory):
    if url := os.environ.get("PGR_ATLAS_URL"):
        yield url.rstrip("/")
        return

    port = _free_port()
    env = {
        # The test bucket unless the caller picks another, never the default "maxi".
        "PROBE_S3_BUCKET": TEST_BUCKET,
        **os.environ,
        # The map components fetch tiles from the sidecars' own ports.
        "SIDECAR_ALLOWED_ORIGINS": f"http://127.0.0.1:{port}",
        "STREAMLIT_SERVER_PORT": str(port),
        "STREAMLIT_SERVER_HEADLESS": "true",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "PMTILES_PORT": str(_free_port()),
        "DERIVATE_BBOX_PORT": str(_free_port()),
        "PGR_ATLAS_TEXTS_FILE": str(french_texts_file(tmp_path_factory.mktemp("texts"))),
    }
    global _app_log
    log_path = _app_log = tmp_path_factory.mktemp("app") / "streamlit.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [sys.executable, "run_app.py"],
            cwd=APP_DIR,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 60
    while True:
        try:
            urllib.request.urlopen(f"{url}/_stcore/health", timeout=2)
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                pytest.fail(f"App did not start; log:\n{log_path.read_text()[-3000:]}")
            time.sleep(0.5)
    yield url
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def nav_link(page: Page, label: str) -> Locator:
    """A link of the sidebar navigation."""
    return page.locator("[data-testid='stSidebar'] .st-key-pgr_nav a", has_text=label)


def active_nav(page: Page, label: str) -> Locator:
    """The navigation link marked as the current page, if it is `label`."""
    return page.locator("[data-testid='stSidebar'] .st-key-nav_current a", has_text=label)


def assert_no_streamlit_exception(page: Page):
    exc = page.locator("[data-testid='stException']")
    if exc.count():
        pytest.fail(f"Streamlit exception on page:\n{exc.first.inner_text()[:2000]}")


def wait_for_rerun(page: Page):
    """Wait until Streamlit has finished running the script."""
    page.wait_for_timeout(300)
    expect(page.locator("[data-testid='stStatusWidget']")).to_have_count(0, timeout=60_000)


@pytest.fixture()
def app_page(page: Page, app_url) -> Page:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(app_url)
    first_nav = nav_link(page, VIEWS["Overview (All Events)"][0])
    exc = page.locator("[data-testid='stException']")
    try:
        # The first session reads the event catalog and gold manifest from S3.
        expect(first_nav.or_(exc).first).to_be_visible(timeout=300_000)
    except AssertionError as error:
        log = _app_log.read_text()[-3000:] if _app_log else "(external app, no log)"
        pytest.fail(
            f"App never rendered its sidebar nav (S3 credentials?).\n{error}\n\nApp log tail:\n{log}"
        )
    wait_for_rerun(page)
    assert_no_streamlit_exception(page)
    page.js_errors = errors
    return page


def map_frame(page: Page, view: str) -> FrameLocator:
    return page.frame_locator(f"iframe[title='{VIEWS[view][1]}']")


def jump_to(frame: FrameLocator, lv95: tuple[float, float], zoom: str):
    """Uses the map's coordinate search, then waits until the fly-to ends at
    `zoom` (the view's search zoom, as the readout prints it)."""
    trigger = frame.get_by_role("button", name="Koordinateneingabe (LV95)")
    if trigger.get_attribute("aria-expanded") != "true":
        trigger.click()
    frame.locator("#search-x").fill(str(lv95[0]))
    frame.locator("#search-y").fill(str(lv95[1]))
    frame.locator("#search-y").press("Enter")
    expect(frame.locator("#zoom-debug")).to_have_text(f"Zoomstufe = {zoom}", timeout=15_000)


def click_map_centre_until(page: Page, view: str, target: Locator):
    """Clicks the middle of the view's map until `target` shows up.

    A click lands on whatever the map has drawn there, and vector tiles may
    still be loading after a jump, so a single click can miss.
    """
    map_el = map_frame(page, view).locator("#map")
    map_el.scroll_into_view_if_needed()
    # Relative to the page's viewport, iframe offset included.
    box = map_el.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    for _ in range(10):
        page.mouse.click(x, y)
        try:
            expect(target).to_be_visible(timeout=2_000)
            return
        except AssertionError:
            pass
    expect(target).to_be_visible()


@pytest.fixture()
def go_to_view(app_page):
    def _go_to(view: str):
        label, _ = VIEWS[view]
        nav_link(app_page, label).click()
        expect(active_nav(app_page, label)).to_be_visible(timeout=60_000)
        wait_for_rerun(app_page)
        assert_no_streamlit_exception(app_page)

    return _go_to
