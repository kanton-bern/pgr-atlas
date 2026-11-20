"""The page header's markup and a selection's shape name (ui_common)."""

import ast
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui_common import page_header_html, shape_label


@pytest.mark.parametrize(
    ("chips", "expected"),
    [((), ""), (("Pixel 1 / 2",), '<span class="pgr-chip">Pixel 1 / 2</span>')],
)
def test_page_header_html_has_one_h1_and_its_chips(chips, expected):
    markup = page_header_html("IFK-Berechnung", "Klick <hier>", chips)
    assert markup.count("<h1") == 1
    assert '<h1 class="pgr-page-title">IFK-Berechnung</h1>' + expected in markup
    # The hint is text, not markup.
    assert '<p class="pgr-page-hint">Klick &lt;hier&gt;</p>' in markup


@pytest.mark.parametrize(
    ("selection", "expected"),
    [
        ({"type": "bbox", "ring": [[0, 0], [5, 0], [5, 5], [0, 5], [0, 0]]}, "Rechteck"),
        ({"type": "polygon", "ring": [[0, 0], [5, 0], [0, 5], [0, 0]]}, "Polygon (3 Eckpunkte)"),
    ],
)
def test_shape_label_counts_a_polygons_corners_once(selection, expected):
    assert shape_label(selection) == expected


def _download_app():
    import streamlit as st

    from ui_common import download_link_button

    with st.container(horizontal=True):
        download_link_button("Laden", "/canton/x.tif", key="x", help="Hinweis", width="stretch")


def test_download_link_button_keeps_the_link_buttons_props():
    at = AppTest.from_function(_download_app).run()
    (button,) = at.get("link_button")
    assert (button.proto.label, button.proto.url, button.proto.help) == (
        "Laden",
        "/canton/x.tif",
        "Hinweis",
    )


def test_download_link_button_sits_in_a_pgr_download_container():
    at = AppTest.from_function(_download_app).run()
    (keyed,) = at.main.children[0].children.values()
    assert keyed.proto.id.endswith("-pgr_download_x")
    assert [c.type for c in keyed.children.values()] == ["link_button"]


def _link_button_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "link_button"
    ]


def test_no_view_calls_st_link_button_directly():
    """Sidecar downloads go through download_link_button, or the gate misses them."""
    app = Path(__file__).resolve().parents[1] / "app"
    raw = {
        path.name: lines
        for path in app.rglob("*.py")
        if path.name != "ui_common.py" and (lines := _link_button_calls(path))
    }
    assert raw == {}
