"""The browser loads nothing from third-party servers, apart from the
basemap tiles: every other request must go to the app itself or its sidecars."""

from urllib.parse import urlsplit

import pytest

from tests.lake_data import ANRISS_ID

from .conftest import VIEWS, assert_no_streamlit_exception, map_frame, wait_for_rerun

pytestmark = pytest.mark.e2e

# Hosts besides the app's own that a page may request, each with its reason.
# A host matches itself and its subdomains.
ALLOWED_HOSTS = {
    # swisstopo basemaps (Landeskarte, Relief): public tiles, not ours to host.
    "wmts.geo.admin.ch": "swisstopo basemap tiles",
    # The OSM basemap, loaded only when the user picks it in the switcher.
    "tile.openstreetmap.org": "OpenStreetMap basemap tiles",
}


def _is_allowed(host: str, app_host: str) -> bool:
    if host == app_host:  # the app and its sidecars: same host, any port
        return True
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_HOSTS)


def test_no_view_requests_an_outside_host(app_page, app_url, go_to_view):
    app_host = urlsplit(app_url).hostname
    outside: set[str] = set()

    def record(request):
        url = urlsplit(request.url)
        # data: and blob: URLs never leave the browser.
        if url.scheme in ("http", "https", "ws", "wss") and not _is_allowed(
            url.hostname or "", app_host
        ):
            outside.add(f"{url.scheme}://{url.netloc}")

    # On the context, so the requests of the map iframes count too.
    app_page.context.on("request", record)

    # app_page opened Simulierte Ereignisse before the listener was there: load it again.
    app_page.reload()
    wait_for_rerun(app_page)
    for view in VIEWS:
        go_to_view(view)
        map_frame(app_page, view).locator("#map").wait_for(timeout=60_000)
    app_page.goto(f"{app_url}/anriss?id={ANRISS_ID}")
    app_page.get_by_role("button", name="← Anriss abwählen").wait_for(timeout=180_000)
    wait_for_rerun(app_page)
    # Let the maps finish their first tile and glyph requests.
    app_page.wait_for_load_state("networkidle", timeout=60_000)

    assert_no_streamlit_exception(app_page)
    assert outside == set(), f"Requests to hosts outside the allowlist: {sorted(outside)}"
