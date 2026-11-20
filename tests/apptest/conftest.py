"""Fixtures for the AppTest suite: app.py run in-process by
streamlit.testing.v1.AppTest, against the `adelboden-test` bucket.

Run it on its own, with its path, so no other test module imports probe-core
before the _test_lake fixture sets its environment (probe-core reads it at import):

    pytest -m apptest tests/apptest

It needs S3 credentials for the test bucket, from the environment or the
repo's .env.
"""

import json
import os
import time
from pathlib import Path

import pytest
from dotenv import dotenv_values
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from tests.lake_data import TEST_BUCKET

REPO_DIR = Path(__file__).resolve().parents[2]
APP_FILE = REPO_DIR / "app" / "app.py"

# The first run of a session reads the event catalog and gold manifest from S3.
_RUN_TIMEOUT_S = 600


@pytest.fixture(scope="session", autouse=True)
def _test_lake():
    """Points probe-core at the test bucket before app.py first imports it."""
    with pytest.MonkeyPatch.context() as monkeypatch:
        for key, value in dotenv_values(REPO_DIR / ".env").items():
            if key not in os.environ and value is not None:
                monkeypatch.setenv(key, value)
        if "PROBE_S3_BUCKET" not in os.environ:
            monkeypatch.setenv("PROBE_S3_BUCKET", TEST_BUCKET)
        if not os.environ.get("PROBE_S3_ACCESS_KEY_ID"):
            pytest.fail(
                "No S3 credentials: set PROBE_S3_ACCESS_KEY_ID and "
                "PROBE_S3_SECRET_ACCESS_KEY, or put them in .env."
            )

        from probe_core.data_lake import data_interface

        if data_interface.S3_BUCKET_GOLD != os.environ["PROBE_S3_BUCKET"]:
            pytest.fail(
                "probe-core was imported before this fixture set its bucket: run the "
                "suite on its own (pytest -m apptest tests/apptest)."
            )
        yield


# The url_path of each view's st.Page in app.py.
PAGE_URL_PATHS = {
    "Overview (All Events)": "simulierte-ereignisse",
    "IFK": "ifk",
    "Raster-Karten": "raster-karten",
    "Raster-Derivate": "raster-derivate",
    "Specific Simulation": "anriss",
    "Gebäudeschatten": "gebaeudeschatten",
    "Kontakt": "kontakt",
    "Impressum": "impressum",
    "Rechtliches": "rechtliches",
}
# A page link names its page by that page's hash (see open_page).
_VIEW_OF_PAGE_HASH = {calc_hash(path): view for view, path in PAGE_URL_PATHS.items()}


def open_page(at: AppTest, view: str) -> AppTest:
    """Makes the next runs open `view`'s page.

    AppTest.switch_page only takes page script files, and app.py's pages are
    functions. Streamlit names those by the hash of their url_path (calc_hash),
    which AppTest sends as the page on each run.
    """
    assert hasattr(at, "_page_hash"), "AppTest no longer has _page_hash; update open_page"
    at._page_hash = calc_hash(PAGE_URL_PATHS[view])
    return at


def new_app(view: str) -> AppTest:
    """The app, not run yet, set to open `view`."""
    return open_page(AppTest.from_file(str(APP_FILE), default_timeout=_RUN_TIMEOUT_S), view)


def run_view(view: str, **state) -> AppTest:
    """Runs the app once on `view`, with `state` preset in session_state."""
    at = new_app(view)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_no_exception(at)
    assert current_view(at) == view
    return at


def nav_links(at: AppTest) -> dict[str, str]:
    """The sidebar navigation's links: {label: the view each opens}."""
    return {
        link.proto.label: _VIEW_OF_PAGE_HASH[link.proto.page_script_hash]
        for link in at.sidebar.get("page_link")
    }


def _current_links(node) -> list:
    """The page links inside the sidebar's "nav_current" container."""
    if getattr(node, "type", None) == "flex_container" and node.proto.id.endswith("-nav_current"):
        return list(node.get("page_link"))
    return [
        link for child in getattr(node, "children", {}).values() for link in _current_links(child)
    ]


def current_view(at: AppTest) -> str | None:
    """The view whose sidebar nav link is marked active, as the user sees it.
    None on the Anriss page without a selected Anriss, which has no link."""
    links = _current_links(at.sidebar)
    assert len(links) <= 1, links
    if not links:
        return None
    return _VIEW_OF_PAGE_HASH[links[0].proto.page_script_hash]


def page_title(at: AppTest) -> str:
    """The text of the page header's h1 (ui_common.page_header)."""
    (header,) = [h for h in at.main.get("html") if 'class="pgr-page-title"' in h.proto.body]
    return header.proto.body.split('class="pgr-page-title">', 1)[1].split("</h1>", 1)[0]


def assert_no_exception(at: AppTest):
    assert not at.exception, [e.message for e in at.exception]


def run_until(at: AppTest, done, timeout_s: float = 300):
    """Reruns the app until done(at) is true: a raster job runs on a thread,
    and only a rerun picks up its result."""
    deadline = time.monotonic() + timeout_s
    while not done(at):
        if time.monotonic() > deadline:
            pytest.fail(f"Not done after {timeout_s} s")
        time.sleep(1)
        at.run()
        assert_no_exception(at)


def map_args(at: AppTest) -> dict:
    """The args the view's map component got on the last run."""
    (component,) = at.get("component_instance")
    return json.loads(component.proto.json_args)


def texts(elements) -> list[str]:
    return [e.value for e in elements]


def labels(elements) -> list[str]:
    return [e.proto.label for e in elements]
