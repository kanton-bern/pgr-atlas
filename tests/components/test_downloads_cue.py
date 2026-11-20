"""The floating downloads cue (app/downloads_cue_component.py).

Its HTML, CSS and JS are inline in the Python module, so the harness mounts
them the way Streamlit mounts an st.components.v2 component: a shadow root as
parentElement, the data as an argument. Next to it, a tall stand-in for a
page with a map and, far below the fold, the keyed downloads container.

No Streamlit, no S3. What is checked here is what only a browser has: the
pill appears while the section is off screen, a click scrolls to it, and it
goes again once the section is on screen.
"""

import json

import downloads_cue_component as cue
import footer
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.components

_SECTION_CLASS = f"st-key-{cue.SECTION_KEY}"
_FOOTER_CLASS = f"st-key-{footer.CONTAINER_KEY}"

_HARNESS = """<!doctype html>
<html><head><meta charset="utf-8"><title>cue</title>
<link rel="stylesheet" href="/styles/tokens.css">
<link rel="stylesheet" href="/styles/app.css">
<style>
  body { margin: 0; }
  #map { height: 1600px; background: #eee; }
  #below { height: 1600px; }
  .%s { position: fixed; bottom: 0; left: 0; right: 0; height: 40px; background: #ddd; }
</style>
</head><body>
<div id="map">map</div>
<div class="stElementContainer st-key-pgr_downloads_cue">
  <!-- The box Streamlit lays the component out in, full size as it makes it. -->
  <div data-testid="stBidiComponentIsolated" id="host" style="width: 100%%; height: 100%%"></div>
</div>
<div id="sections"></div>
<div id="below"></div>
<div class="%s">footer</div>
<script type="module">
  import mount from "/downloads_cue.js";
  const CSS = %s, HTML = %s, DATA = %s;
  const host = document.getElementById("host");
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = "<style>" + CSS + "</style>" + HTML;
  window.teardown = mount({ parentElement: root, data: DATA });
  window.addSection = (text) => {
    const section = document.createElement("div");
    section.className = %s;
    section.textContent = text;
    document.getElementById("sections").append(section);
  };
</script></body></html>
""" % (
    _FOOTER_CLASS,
    _FOOTER_CLASS,
    json.dumps(cue._CSS),
    json.dumps(cue._HTML),
    json.dumps(
        {
            "label": "Zu den Downloads",
            "sectionClass": _SECTION_CLASS,
            "footerClass": _FOOTER_CLASS,
        }
    ),
    json.dumps(_SECTION_CLASS),
)


@pytest.fixture()
def cue_page(page: Page, component_server):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    base = f"http://127.0.0.1:{component_server}"
    page.route(
        f"{base}/downloads_cue.js",
        lambda route: route.fulfill(body=cue._JS, content_type="text/javascript"),
    )
    page.route(
        f"{base}/cue.html", lambda route: route.fulfill(body=_HARNESS, content_type="text/html")
    )
    page.goto(f"{base}/cue.html")
    page.wait_for_function("typeof window.addSection === 'function'")
    page.errors = errors
    return page


def test_no_section_no_pill(cue_page):
    """A view with nothing to download never shows the cue."""
    expect(cue_page.get_by_role("button")).to_be_hidden()
    assert cue_page.errors == []


def test_the_pill_appears_for_a_section_below_the_fold(cue_page):
    cue_page.evaluate("window.addSection('Downloads')")
    button = cue_page.get_by_role("button", name="Zu den Downloads")
    expect(button).to_be_visible()
    assert cue_page.errors == []


def test_a_click_scrolls_to_the_section_and_the_pill_goes(cue_page):
    cue_page.evaluate("window.addSection('Downloads')")
    button = cue_page.get_by_role("button", name="Zu den Downloads")
    expect(button).to_be_visible()
    button.click()
    cue_page.wait_for_function("window.scrollY > 0")
    expect(cue_page.locator(f".{_SECTION_CLASS}")).to_be_in_viewport()
    expect(button).to_be_hidden()
    assert cue_page.errors == []


def test_the_pill_goes_for_a_short_section_at_the_very_end_of_the_page(cue_page):
    """The last 15% of the window can't be scrolled past at the end of a page,
    so a section that sits there but is fully visible must hide the pill."""
    cue_page.evaluate("document.getElementById('below').style.height = '0'")
    cue_page.evaluate("window.addSection('Downloads')")
    cue_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    expect(cue_page.locator(f".{_SECTION_CLASS}")).to_be_in_viewport(ratio=1)
    expect(cue_page.get_by_role("button")).to_be_hidden()
    assert cue_page.errors == []


def test_the_pill_goes_again_when_the_section_does(cue_page):
    """A rerun that drops the result (no selection any more) takes the cue with it."""
    cue_page.evaluate("window.addSection('Downloads')")
    expect(cue_page.get_by_role("button")).to_be_visible()
    cue_page.evaluate("document.getElementById('sections').replaceChildren()")
    expect(cue_page.get_by_role("button")).to_be_hidden()
    assert cue_page.errors == []


def test_the_pill_floats_at_the_bottom_right_above_the_sticky_footer(cue_page):
    """Where it sits is app.css, on the keyed container: Streamlit's own box
    for the element beats a rule in the component's shadow CSS."""
    cue_page.evaluate("window.addSection('Downloads')")
    expect(cue_page.get_by_role("button", name="Zu den Downloads")).to_be_visible()
    box = cue_page.evaluate(
        """(cls) => {
      const footer = document.querySelector("." + cls).getBoundingClientRect();
      const host = document.getElementById("host");
      const pill = host.shadowRoot.querySelector("button").getBoundingClientRect();
      return { fromRight: window.innerWidth - pill.right, intoFooter: pill.bottom - footer.top,
               width: pill.width };
    }""",
        _FOOTER_CLASS,
    )
    assert box["intoFooter"] <= 0, f"the pill reaches {box['intoFooter']} px into the footer"
    assert 0 < box["fromRight"] < 40, box
    assert box["width"] > 0
