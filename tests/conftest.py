import pytest

import ui_text


def pytest_collection_modifyitems(items):
    # Browser tests last: Playwright's sync API keeps an asyncio loop running
    # from its first use until the session ends, and the Tornado test cases
    # (test_pmtiles_server, test_derivate_bbox_server) can't start their own
    # loop after that ("Cannot run the event loop while another loop is running").
    items.sort(
        key=lambda item: (
            item.get_closest_marker("components") is not None
            or item.get_closest_marker("e2e") is not None
        )
    )


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1440, "height": 1000}}


@pytest.fixture
def french_texts(monkeypatch):
    """Every text has a French version, "[FR] " and the German, so the app
    offers both languages and a test sees which one a text is in."""
    french = {key: {**entry, "fr": "[FR] " + entry["de"]} for key, entry in ui_text._TEXTS.items()}
    monkeypatch.setattr(ui_text, "_TEXTS", french)


@pytest.fixture
def german_only_texts(monkeypatch):
    """No text has a French version, so the app offers German only."""
    german = {key: {**entry, "fr": ""} for key, entry in ui_text._TEXTS.items()}
    monkeypatch.setattr(ui_text, "_TEXTS", german)


@pytest.fixture
def french_session(french_texts, monkeypatch):
    """french_texts in a French session: for what must stay German in every UI
    language (Q9)."""
    monkeypatch.setattr(ui_text, "language", lambda: "fr")


@pytest.fixture(autouse=True)
def _work_dir(tmp_path_factory, monkeypatch):
    """Uploads and raster folders (app/work_dirs.py) go to a temp folder, not ~/probe_data."""
    monkeypatch.setenv("PROBE_WORK_DIR", str(tmp_path_factory.mktemp("work")))
