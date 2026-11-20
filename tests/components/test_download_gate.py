"""The download gate (frontend/src/download_gate/), built into app/download_gate/dist/.

The page is a small harness that mounts the built script the way Streamlit does
(a shadow root as parentElement, the data and a recording setTriggerValue as
arguments) next to stand-ins for the two kinds of download control, each counting
its clicks, and the legal page's «Simulationsdaten» heading. No Streamlit, no S3.
The decisions are unit-tested in frontend/src/download_gate/gate.test.ts; this
checks them in a real browser: the native dialog, focus, Escape, the replayed click,
the dialog's link.
"""

import json
import re

import pytest
from download_gate_component import _split_statement
from playwright.sync_api import Page, expect

from .conftest import APP_DIR

pytestmark = pytest.mark.components

_DATA = {
    "title": "Hinweis",
    "statementBefore": "Ich habe die ",
    "linkText": "Hinweise zu den Simulationsdaten",
    "statementAfter": " gelesen und akzeptiere sie",
    "linkHref": "rechtliches#simulationsdaten",
    "showSection": "",
    "accept": "Akzeptieren",
    "decline": "Ablehnen",
}

_HARNESS = """<!doctype html>
<html><head><meta charset="utf-8"><title>gate</title>
<style>:root { --pgr-bg: #fff; --pgr-text: #000; --pgr-brand: #4e4e4e; --pgr-focus: #000; }</style>
</head><body>
<div id="host"></div>
<div data-testid="stDownloadButton"><button id="button" type="button">Daten</button></div>
<div class="stElementContainer st-key-pgr_download_raster">
  <a id="link" href="#download">Raster</a>
</div>
<a id="other" href="#other">Other</a>
<div style="height: 3000px"></div>
<h2 id="simulationsdaten">Simulationsdaten</h2>
<script type="module">
  import gate from "/download_gate/dist/download_gate.js";
  window.clicks = { button: 0, link: 0, other: 0 };
  window.triggers = [];
  for (const id of ["button", "link", "other"]) {
    document.getElementById(id).addEventListener("click", () => window.clicks[id]++);
  }
  const setTriggerValue = (name, value) => window.triggers.push([name, value]);
  window.mount = (data) => {
    const root = document.getElementById("host").shadowRoot
      ?? document.getElementById("host").attachShadow({ mode: "open" });
    window.teardown = gate({ parentElement: root, data, setTriggerValue });
  };
  window.mount(%s);
</script></body></html>
""" % json.dumps(_DATA)

_NO_STORAGE_JS = """
Object.defineProperty(window, 'sessionStorage', {
  get() { throw new DOMException('denied', 'SecurityError'); },
});
"""


@pytest.fixture()
def gate_page(page: Page, component_server):
    if not (APP_DIR / "download_gate" / "dist" / "download_gate.js").is_file():
        pytest.fail("app/download_gate/dist is missing: run `npm ci && npm run build` in frontend/")
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    base = f"http://127.0.0.1:{component_server}"
    page.route(
        f"{base}/gate.html", lambda route: route.fulfill(body=_HARNESS, content_type="text/html")
    )
    page.goto(f"{base}/gate.html")
    page.wait_for_function("typeof window.mount === 'function'")
    page.errors = errors
    return page


def clicks(page: Page) -> dict[str, int]:
    return page.evaluate("window.clicks")


def test_first_click_opens_the_dialog_and_downloads_nothing(gate_page):
    gate_page.locator("#button").click()
    dialog = gate_page.locator("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("heading")).to_have_text("Hinweis")
    expect(dialog.locator("p")).to_have_text(
        "Ich habe die Hinweise zu den Simulationsdaten gelesen und akzeptiere sie"
    )
    link = dialog.get_by_role("link")
    expect(link).to_have_text("Hinweise zu den Simulationsdaten")
    expect(link).to_have_attribute("href", "rechtliches#simulationsdaten")
    assert clicks(gate_page)["button"] == 0
    assert gate_page.errors == []


def test_the_link_asks_python_for_the_legal_page_and_downloads_nothing(gate_page):
    """Python switches the page in the same session; the browser does not follow the link."""
    url = gate_page.url
    gate_page.locator("#button").click()
    gate_page.locator("dialog").get_by_role("link").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert gate_page.evaluate("window.triggers") == [["open_legal", True]]
    assert gate_page.url == url
    assert len(gate_page.context.pages) == 1
    assert clicks(gate_page)["button"] == 0


def test_mounted_after_the_link_it_shows_the_section(gate_page):
    gate_page.evaluate(
        "window.mount(%s)" % json.dumps({**_DATA, "showSection": "simulationsdaten"})
    )
    expect(gate_page).to_have_url(re.compile(r"#simulationsdaten$"))
    expect(gate_page.locator("#simulationsdaten")).to_be_in_viewport()


def test_decline_closes_and_the_next_click_asks_again(gate_page):
    gate_page.locator("#button").click()
    gate_page.get_by_role("button", name="Ablehnen").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 0
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_be_visible()


def test_escape_closes_without_downloading_and_returns_focus(gate_page):
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_be_visible()
    gate_page.keyboard.press("Escape")
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 0
    expect(gate_page.locator("#button")).to_be_focused()


def test_accept_downloads_once_and_later_clicks_pass(gate_page):
    gate_page.locator("#button").click()
    gate_page.get_by_role("button", name="Akzeptieren").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 1
    assert gate_page.evaluate("sessionStorage.getItem('pgr-download-accepted')") == "1"
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 2


def test_accepted_tab_passes_after_reload(gate_page):
    gate_page.locator("#button").click()
    gate_page.get_by_role("button", name="Akzeptieren").click()
    gate_page.reload()
    gate_page.wait_for_function("typeof window.mount === 'function'")
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 1


def test_link_in_a_pgr_download_container_is_gated(gate_page):
    gate_page.locator("#link").click()
    expect(gate_page.locator("dialog")).to_be_visible()
    assert clicks(gate_page)["link"] == 0
    gate_page.get_by_role("button", name="Akzeptieren").click()
    assert clicks(gate_page)["link"] == 1


def test_other_links_are_not_gated(gate_page):
    gate_page.locator("#other").click()
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["other"] == 1


def test_dialog_is_keyboard_operable(gate_page):
    gate_page.locator("#button").focus()
    gate_page.keyboard.press("Enter")
    expect(gate_page.locator("dialog")).to_be_visible()
    gate_page.get_by_role("button", name="Akzeptieren").focus()
    gate_page.keyboard.press("Enter")
    expect(gate_page.locator("dialog")).to_be_hidden()
    assert clicks(gate_page)["button"] == 1


def test_mounting_twice_leaves_one_listener(gate_page):
    gate_page.evaluate("window.mount(%s)" % json.dumps(_DATA))
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_have_count(1)
    gate_page.get_by_role("button", name="Akzeptieren").click()
    assert clicks(gate_page)["button"] == 1


def test_teardown_removes_the_gate(gate_page):
    gate_page.evaluate("window.teardown()")
    gate_page.locator("#button").click()
    expect(gate_page.locator("dialog")).to_have_count(0)
    assert clicks(gate_page)["button"] == 1


def test_without_storage_it_asks_every_time_but_still_downloads(page, component_server):
    page.add_init_script(_NO_STORAGE_JS)
    base = f"http://127.0.0.1:{component_server}"
    page.route(
        f"{base}/gate.html", lambda route: route.fulfill(body=_HARNESS, content_type="text/html")
    )
    page.goto(f"{base}/gate.html")
    page.wait_for_function("typeof window.mount === 'function'")
    page.locator("#button").click()
    page.get_by_role("button", name="Akzeptieren").click()
    assert clicks(page)["button"] == 1
    page.locator("#button").click()
    expect(page.locator("dialog")).to_be_visible()
    assert clicks(page)["button"] == 1


def test_statement_is_split_at_the_bracketed_phrase():
    assert _split_statement("Ich habe die [Hinweise] gelesen") == (
        "Ich habe die ",
        "Hinweise",
        " gelesen",
    )


@pytest.mark.parametrize("statement", ["no brackets", "open [only", "empty [] phrase"])
def test_statement_without_a_linked_phrase_is_refused(statement):
    with pytest.raises(ValueError, match="square brackets"):
        _split_statement(statement)
