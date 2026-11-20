"""The session's language: taken from the link on a session's first run, kept
in the URL, switched with DE | FR at the foot of the sidebar.

The language lives in st.session_state[ui_text.SESSION_KEY], which ui_text.t() reads. The
toggle lists the languages app/texts.toml has (ui_text.languages()) and is
hidden while that is German only. Each language is written in itself and
never translated, so a user who can't read the current one still finds theirs.
"""

from collections.abc import Mapping

import streamlit as st

import ui_text

QUERY_KEY = "lang"
_NAMES = {"de": "Deutsch", "fr": "Français"}

# The keys translated_options() registered this session.
_TRANSLATED_KEYS = "_lang_translated_option_keys"


def language_from_query(params: Mapping[str, str], available: tuple[str, ...]) -> str:
    """The language a link asks for (?lang=fr); German if it asks for none or
    for one the app doesn't have."""
    requested = params.get(QUERY_KEY)
    return requested if requested in available else ui_text.DEFAULT_LANGUAGE


def with_language(params: Mapping[str, str], lang: str) -> dict[str, str]:
    """params plus the language, for a URL that replaces all query params.
    German, the default, isn't written."""
    params = dict(params)
    if lang != ui_text.DEFAULT_LANGUAGE:
        params[QUERY_KEY] = lang
    return params


def set_query_params(params: Mapping[str, str]) -> None:
    """st.query_params.from_dict that keeps the session's language in the URL."""
    st.query_params.from_dict(with_language(params, ui_text.language()))


def init_language() -> None:
    """Before anything shows a text. On a session's first run the language is
    the link's; on every run the URL shows it, so a copied link opens in the
    same language. A page switch drops the query params, and this puts the
    language back on the next run."""
    if ui_text.SESSION_KEY not in st.session_state:
        st.session_state[ui_text.SESSION_KEY] = language_from_query(
            st.query_params, ui_text.languages()
        )
    lang = st.session_state[ui_text.SESSION_KEY]
    if lang == ui_text.DEFAULT_LANGUAGE:
        if QUERY_KEY in st.query_params:
            del st.query_params[QUERY_KEY]
    elif st.query_params.get(QUERY_KEY) != lang:
        st.query_params[QUERY_KEY] = lang


def translated_options(key: str) -> str:
    """The key of a radio or select box whose options show a text or a number
    in the session's language, registered so a language switch keeps its pick.

    Such a widget sends its pick back as the label it shows. After a switch
    that label is in the other language and matches no option: a radio falls
    back to its first option, a select box keeps showing the old label.
    _switch() sets each registered key again, so the widget takes its value
    from the session and shows it in the new language.
    """
    st.session_state.setdefault(_TRANSLATED_KEYS, set()).add(key)
    return key


def _switch(lang: str) -> None:
    """The toggle's callback, so it runs before any widget is drawn."""
    st.session_state[ui_text.SESSION_KEY] = lang
    for key in st.session_state.get(_TRANSLATED_KEYS, set()):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def render_toggle() -> None:
    """DE | FR, as the Kanton Bern guide's language selector (A144): text
    buttons, the current one underlined in red (app.css). The current one is
    disabled: there is nothing to switch to. Nothing while there is only one
    language."""
    available = ui_text.languages()
    if len(available) < 2:
        return
    current = ui_text.language()
    with st.container(key="pgr_lang", horizontal=True):
        for lang in available:
            st.button(
                lang.upper(),
                key=f"lang_{lang}",
                help=_NAMES[lang],
                type="tertiary",
                disabled=lang == current,
                on_click=_switch,
                args=(lang,),
            )
