"""Fixtures for the map-component tests.

Each MapLibre component waits for Streamlit's `streamlit:render` message.
These tests load its page as a top-level page from a tiny local HTTP server,
post that message with hand-made args, and drive the map chrome directly -- no
Streamlit, no S3, so they run anywhere (CI included).

Every component is built from frontend/ into app/<component>/dist/ (`npm run
build` in frontend/ first).
"""

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import anriss_map_component
import gebaeudeschatten_map_component
import ifk_map_component
import overview_component
import raster_bbox_component

APP_DIR = Path(__file__).resolve().parents[2] / "app"
# The Python wrapper of each component, whose texts() every render sends, as
# the app does: a key Python and the component's args.ts disagree on stops the map.
_WRAPPERS = {
    "overview": overview_component,
    "overview_ifk": ifk_map_component,
    "raster_bbox_map": raster_bbox_component,
    "anriss_map": anriss_map_component,
    "gebaeudeschatten_map": gebaeudeschatten_map_component,
}

# Basemap tiles and the (non-existent here) PMTiles archives: blocked so the
# tests neither depend on nor hammer swisstopo/OSM. The map still fires 'load'
# with failed tiles.
_BLOCKED_HOSTS = ("geo.admin.ch", "tile.openstreetmap.org")

# Every component sets window.debugMap right after creating its map. This
# catches that assignment, so tests can reach the map and wait for its 'load'
# event -- which is when each view wires its legend toggles.
_CAPTURE_MAP_JS = """
(() => {
  Object.defineProperty(window, 'debugMap', {
    configurable: true,
    get() { return window.__testMap; },
    set(map) {
      window.__testMap = map;
      map.on('load', () => { window.__testMapLoaded = true; });
    },
  });
  window.__componentValues = [];
  window.addEventListener('message', e => {
    const m = e.data || {};
    if (m.isStreamlitMessage && m.type === 'streamlit:setComponentValue') window.__componentValues.push(m.value);
  });
})();
"""


class _Handler(SimpleHTTPRequestHandler):
    """Serves app/ like Streamlit's component handler."""

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def component_server():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(APP_DIR))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()


class MapComponent:
    def __init__(self, page: Page, texts: dict):
        self.page = page
        self.texts = texts  # `labels` and `locale`, sent with every render unless a test overrides
        self.errors: list[str] = []
        self.coverage_requests: list[str] = []  # URLs the map fetched the coverage from
        self.cdn_requests: list[str] = []  # the components bundle their scripts: none expected
        page.on("pageerror", lambda exc: self.errors.append(str(exc)))
        page.on("request", self._record_cdn_request)

    def _record_cdn_request(self, request):
        if "unpkg.com" in request.url:
            self.cdn_requests.append(request.url)

    def values(self) -> list:
        """Everything the component sent back via setComponentValue."""
        return self.page.evaluate("window.__componentValues")

    def layer_visibility(self, layer_id: str) -> str:
        return self.page.evaluate(
            "id => window.__testMap.getLayoutProperty(id, 'visibility') || 'visible'", layer_id
        )

    def open_popover(self, name: str) -> Locator:
        """Opens the control column's "search" or "basemap" popover; returns its panel."""
        trigger = self.page.locator(f"#{name}-toggle")
        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "true")
        panel = self.page.locator(f"#{trigger.get_attribute('aria-controls')}")
        expect(panel).to_be_visible()
        return panel

    def render(self, **args):
        """Send another streamlit:render, like a Streamlit rerun would."""
        self.page.evaluate(
            "args => window.postMessage({type: 'streamlit:render', args}, '*')",
            json.loads(json.dumps({**self.texts, **args})),
        )


def _page_path(component_dir: str) -> str:
    built = f"{component_dir}/dist/index.html"
    if not (APP_DIR / built).is_file():
        pytest.fail(f"app/{built} is missing: run `npm ci && npm run build` in frontend/")
    return built


@pytest.fixture()
def open_component(page: Page, component_server):
    def _open(component_dir: str, **args) -> MapComponent:
        comp = MapComponent(page, _WRAPPERS[component_dir].texts())
        for host in _BLOCKED_HOSTS:
            page.route(f"**://*{host}/**", lambda route: route.abort())
        page.route("**/*.pmtiles", lambda route: route.fulfill(status=404))

        def serve_coverage(route):
            comp.coverage_requests.append(route.request.url)
            route.fulfill(json=COVERAGE_GEOJSON)

        page.route("**/coverage.geojson?*", serve_coverage)
        page.add_init_script(_CAPTURE_MAP_JS)
        page.goto(f"http://127.0.0.1:{component_server}/{_page_path(component_dir)}")
        args.setdefault("center_lat", 46.8)
        args.setdefault("center_lon", 7.5)
        # Like the Python wrappers, which always send the sidecar ports.
        args.setdefault("pmtiles_port", component_server)
        args.setdefault("derivate_bbox_server_port", component_server)
        comp.render(**args)
        try:
            page.wait_for_function("window.__testMapLoaded === true", timeout=30_000)
        except PlaywrightTimeoutError:
            # A wrong render arg (a label key Python and args.ts disagree on) throws in the page.
            pytest.fail(f"{component_dir}'s map did not load; page errors: {comp.errors}")
        return comp

    return _open


# A small square of "gold coverage" near Bern, WGS84. Served as the tile
# sidecar's /coverage.geojson?v=COVERAGE_VERSION.
COVERAGE_VERSION = "0123456789abcdef"
COVERAGE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [7.44, 46.94],
                        [7.46, 46.94],
                        [7.46, 46.96],
                        [7.44, 46.96],
                        [7.44, 46.94],
                    ]
                ],
            },
        }
    ],
}
