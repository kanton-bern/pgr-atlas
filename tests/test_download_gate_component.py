"""The Python side of the download gate."""

import re
import unicodedata
from types import SimpleNamespace

import pytest

import download_gate_component as gate
import ui_text
from views import legal


@pytest.mark.parametrize(
    ("lang", "href"),
    [
        ("de", "rechtliches#simulationsdaten"),
        ("fr", "rechtliches?lang=fr#donnees-de-simulation"),
    ],
)
def test_the_link_keeps_the_language(monkeypatch, lang, href):
    """A Ctrl- or middle-click follows the href in a new session, which takes its language."""
    monkeypatch.setattr(ui_text, "language", lambda: lang)
    assert gate._legal_href(SimpleNamespace(url_path="rechtliches")) == href


def _heading_id(heading: str) -> str:
    """The id Streamlit gives a Markdown heading: accents dropped, lower case, the
    words joined by "-" (what its slugify does for these headings)."""
    plain = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode()
    return "-".join(re.findall(r"[a-z0-9]+", plain.lower()))


@pytest.mark.parametrize(
    "path", sorted(legal.LEGAL_DIR.glob("rechtliches.*.md")), ids=lambda path: path.name
)
def test_every_rechtliches_page_has_the_heading_the_link_leads_to(path):
    """The link and the scroll after it find the section only by this id."""
    lang = path.name.split(".")[1]
    headings = re.findall(r"^## (.+)$", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    assert gate.LEGAL_SECTIONS[lang] in {_heading_id(heading) for heading in headings}


def test_the_gates_own_key_is_not_a_download_container():
    """The gate gates links inside st-key-pgr_download_*: its dialog link must stay free."""
    assert not gate._KEY.startswith("pgr_download_")


def test_the_statement_is_split_around_the_linked_phrase():
    assert gate._split_statement("Ich habe die [Hinweise] gelesen") == (
        "Ich habe die ",
        "Hinweise",
        " gelesen",
    )


@pytest.mark.parametrize("statement", ["no brackets", "empty []", "open [only"])
def test_a_statement_without_a_linked_phrase_is_refused(statement):
    with pytest.raises(ValueError, match="square brackets"):
        gate._split_statement(statement)
