"""The download disclaimer gate.

An st.components.v2 component with inline JS, mounted once on every page. It holds
back the first download of a browser tab behind a dialog and lets later ones
through (frontend/src/download_gate/). Python hands it the texts, and opens the
legal page when the dialog's link is clicked.

The link opens the legal page in the same session, as the footer's link does:
the component sets the trigger value "open_legal" and its callback calls
st.switch_page. A plain link would load the page anew and start a new session.

The script is built from frontend/ by `npm run build` into
app/download_gate/dist/download_gate.js and read from there.
"""

from pathlib import Path
from urllib.parse import urlencode

import streamlit as st
from streamlit.navigation.page import StreamlitPage

import language
import ui_text

_SCRIPT = Path(__file__).parent / "download_gate" / "dist" / "download_gate.js"

# The key of the component's element. It must not start with "pgr_download_":
# the gate treats links inside such a container as downloads, its own dialog link
# included.
_KEY = "pgr_gate"

# The id of the "Simulationsdaten" heading on Rechtliches, per language of the
# page's file: Streamlit makes it from the heading's text, so it changes with the
# translation. tests/test_download_gate_component.py checks it against the files.
LEGAL_SECTIONS = {"de": "simulationsdaten", "fr": "donnees-de-simulation"}

# Set by the link's callback, read once by the run that draws the legal page.
_SHOW_SECTION = "_download_gate_show_section"


def _legal_section(lang: str) -> str:
    """The heading's id on Rechtliches in `lang`, or in German while it has no page."""
    return LEGAL_SECTIONS.get(lang, LEGAL_SECTIONS[ui_text.DEFAULT_LANGUAGE])


def _legal_href(legal_page: StreamlitPage) -> str:
    """The link's href, in the session's language: what a Ctrl- or middle-click opens."""
    lang = ui_text.language()
    query = urlencode(language.with_language({}, lang))
    return f"{legal_page.url_path}{'?' + query if query else ''}#{_legal_section(lang)}"


def _split_statement(statement: str) -> tuple[str, str, str]:
    """Splits 'text [linked phrase] text' into the three parts."""
    before, opening, rest = statement.partition("[")
    link, closing, after = rest.partition("]")
    if not opening or not closing or not link:
        raise ValueError(
            f"download_gate.statement needs one linked phrase in [square brackets]: {statement!r}"
        )
    return before, link, after


def mount_download_gate(
    title: str, statement: str, accept: str, decline: str, legal_page: StreamlitPage
) -> None:
    """Mounts the gate. Call it once per script run, on every page.

    Registers the component on every call, not once at import: the registry
    belongs to the Streamlit runtime, and a module imported under one runtime
    (AppTest starts one per test) would be unknown to the next.

    Args:
        title: the dialog's heading.
        statement: the sentence the user accepts, with the phrase that links to the
            legal page in square brackets, e.g. 'Ich habe die [Hinweise] gelesen'.
        accept: the label of the accepting button.
        decline: the label of the declining button.
        legal_page: the page the linked phrase opens, at its "Simulationsdaten" heading.

    Raises:
        FileNotFoundError: the script is not built.
        ValueError: `statement` has no [linked phrase].
    """
    if not _SCRIPT.is_file():
        raise FileNotFoundError(f"{_SCRIPT} is missing: run `npm ci && npm run build` in frontend/")
    before, link_text, after = _split_statement(statement)

    def _open_legal() -> None:
        st.session_state[_SHOW_SECTION] = True
        st.switch_page(legal_page)

    show_section = st.session_state.pop(_SHOW_SECTION, False)
    # The leading newline makes Streamlit treat the string as code, not as a file path.
    mount = st.components.v2.component("download_gate", js="\n" + _SCRIPT.read_text("utf-8"))
    mount(
        key=_KEY,
        data={
            "title": title,
            "statementBefore": before,
            "linkText": link_text,
            "statementAfter": after,
            "linkHref": _legal_href(legal_page),
            "showSection": _legal_section(ui_text.language()) if show_section else "",
            "accept": accept,
            "decline": decline,
        },
        on_open_legal_change=_open_legal,
        width="content",
        height="content",
    )
