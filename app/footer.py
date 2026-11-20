"""The footer row at the bottom of every view: the copyright line at the left, the
Arbeitsgruppe Naturgefahren and the three legal pages (Kontakt, Impressum, Rechtliches)
at the right.

The labels come from the caller (app/texts.toml via ui_text.t), so this module holds no
user-facing text. Styling is in app/styles/app.css, under .st-key-pgr_footer.
"""

from collections.abc import Mapping

import streamlit as st

WORKING_GROUP_URL = "https://www.naturgefahren.sites.be.ch/de/start/ueber-uns.html"
PAGE_ORDER = ("contact", "imprint", "legal")
# The row's container key, which Streamlit renders as .st-key-pgr_footer: app.css
# sticks the row to the bottom of the window, and downloads_cue_component.py keeps
# the cue above it.
CONTAINER_KEY = "pgr_footer"


def render(pages: Mapping[str, st.Page], labels: Mapping[str, str]) -> None:
    """Draw the footer row.

    Args:
        pages: The legal pages, keyed "contact", "imprint" and "legal".
        labels: The texts, keyed "copyright" (the line at the left), "working_group" and
            the same three keys as pages (the links at the right).

    Raises:
        KeyError: A page or a label is missing. The message names the key.
    """
    with st.container(key=CONTAINER_KEY, horizontal=True):
        st.caption(labels["copyright"])
        st.page_link(WORKING_GROUP_URL, label=labels["working_group"])
        for name in PAGE_ORDER:
            st.page_link(pages[name], label=labels[name])
