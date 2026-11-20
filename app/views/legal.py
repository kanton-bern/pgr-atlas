"""Kontakt, Impressum and Rechtliches: Markdown files from app/legal/.

Each page is app/legal/<name>.<lang>.md, falling back to <name>.de.md while a
language has no file. The file's first line is its "# H1"; it becomes the
page header, and the rest is rendered as Markdown (Streamlit adds the heading
anchors, e.g. rechtliches#simulationsdaten).
"""

import re
from collections.abc import Callable
from pathlib import Path

import streamlit as st

import ui_text
from ui_common import page_header

PAGES = ("kontakt", "impressum", "rechtliches")

LEGAL_DIR = Path(__file__).resolve().parent.parent / "legal"
_FALLBACK_LANGUAGE = "de"


def page_path(name: str, lang: str, legal_dir: Path = LEGAL_DIR) -> Path:
    """The file for a page in a language, else its German file.

    Raises:
        FileNotFoundError: neither file exists; the message names both.
    """
    wanted = legal_dir / f"{name}.{lang}.md"
    if wanted.is_file():
        return wanted
    fallback = legal_dir / f"{name}.{_FALLBACK_LANGUAGE}.md"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        f"Legal page '{name}' has no file: looked for {wanted} and {fallback}. "
        f"Add app/legal/{name}.{_FALLBACK_LANGUAGE}.md."
    )


def split_title(markdown: str) -> tuple[str, str]:
    """The text of the leading "# H1" line, and the Markdown after it.

    Raises:
        ValueError: the first line is not a "# " heading.
    """
    first, _, body = markdown.partition("\n")
    if not first.startswith("# "):
        raise ValueError(f"A legal page must start with a '# Title' line, not {first!r}.")
    return first[2:].strip(), body.lstrip("\n")


def keep_language_in_links(markdown: str, lang: str) -> str:
    """Adds `?lang=<lang>` to the links between legal pages, unless `lang` is German.

    A Markdown link is a full page load that starts a new session, which would
    open the linked page in German; the language travels in the URL instead.
    """
    if lang == ui_text.DEFAULT_LANGUAGE:
        return markdown
    pages = "|".join(PAGES)
    return re.sub(rf"\]\(({pages})(#[\w-]+)?\)", rf"](\1?lang={lang}\2)", markdown)


def load_page(name: str, lang: str, legal_dir: Path = LEGAL_DIR) -> tuple[str, str]:
    """A page's title and its Markdown body, without the H1 line."""
    path = page_path(name, lang, legal_dir)
    return split_title(path.read_text(encoding="utf-8"))


def render(name: str, lang: str | None = None, on_close: Callable[[], None] | None = None) -> None:
    """Draws one legal page: the header with the file's title, then its body.

    Args:
        name: one of PAGES.
        lang: a language in place of the session's.
        on_close: called when the cross at the header's right end is clicked; no cross
            when None.
    """
    lang = lang or ui_text.language()
    title, body = load_page(name, lang)
    header = page_header(title, hint="")
    if on_close is not None:
        with header:
            st.button(
                "✕",
                key="pgr_legal_close",
                help=ui_text.t("footer.close"),
                on_click=on_close,
                type="tertiary",
            )
    st.markdown(keep_language_in_links(body, lang))


def page_function(name: str, on_close: Callable[[], None] | None = None) -> Callable[[], None]:
    """The no-argument function for st.Page(..., url_path=name).

    `on_close` is passed on to `render`.
    """
    if name not in PAGES:
        raise ValueError(f"Unknown legal page {name!r}; expected one of {PAGES}.")

    def _page() -> None:
        render(name, on_close=on_close)

    _page.__name__ = name
    return _page
