import re
import tomllib
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
STYLES = APP / "styles"
CONFIG = tomllib.loads((APP / ".streamlit" / "config.toml").read_text(encoding="utf-8"))


def _tokens() -> dict[str, str]:
    css = (STYLES / "tokens.css").read_text(encoding="utf-8")
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", css))


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    light, dark = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("name", ["tokens.css", "app.css"])
def test_stylesheet_has_no_less_than_sign(name):
    """st.html's sanitizer drops a style element whose text contains "<", even in a comment."""
    assert "<" not in (STYLES / name).read_text(encoding="utf-8")


def test_app_css_defines_no_tokens_of_its_own():
    """The tokens live in tokens.css, which the map components bundle too."""
    assert ":root" not in (STYLES / "app.css").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "fg, bg, minimum",
    [
        # Text: WCAG AA 4.5:1.
        ("--pgr-text", "--pgr-bg", 4.5),
        ("--pgr-text", "--pgr-surface", 4.5),
        ("--pgr-text", "--pgr-info-bg", 4.5),
        ("--pgr-text-muted", "--pgr-bg", 4.5),
        ("--pgr-text-muted", "--pgr-surface", 4.5),
        ("--pgr-bg", "--pgr-brand", 4.5),
        ("--pgr-bg", "--pgr-brand-dark", 4.5),
        ("--pgr-error", "--pgr-bg", 4.5),
        ("--pgr-error", "--pgr-error-bg", 4.5),
        # Focus outline, borders and the identity band: 3:1 for UI parts.
        ("--pgr-focus", "--pgr-bg", 3.0),
        ("--pgr-focus", "--pgr-surface", 3.0),
        ("--pgr-brand", "--pgr-surface", 3.0),
        ("--pgr-project", "--pgr-surface", 3.0),
    ],
)
def test_token_pairs_meet_wcag_aa(fg, bg, minimum):
    tokens = _tokens()
    assert _contrast(tokens[fg], tokens[bg]) >= minimum


@pytest.mark.parametrize(
    "section, option, token",
    [
        ("theme", "backgroundColor", "--pgr-bg"),
        ("theme", "secondaryBackgroundColor", "--pgr-surface"),
        ("theme", "textColor", "--pgr-text"),
        ("theme", "primaryColor", "--pgr-brand"),
        ("theme", "borderColor", "--pgr-text-muted"),
        ("theme", "linkColor", "--pgr-text"),
        ("theme", "redColor", "--pgr-error"),
        ("theme", "redBackgroundColor", "--pgr-error-bg"),
        ("theme", "blueColor", "--pgr-info"),
        ("theme", "blueBackgroundColor", "--pgr-info-bg"),
        ("theme", "greenColor", "--pgr-success"),
        ("theme", "orangeColor", "--pgr-warning"),
        ("sidebar", "backgroundColor", "--pgr-surface"),
    ],
)
def test_streamlit_theme_matches_the_tokens(section, option, token):
    """The theme styles Streamlit's widgets, the tokens everything else: they must agree."""
    theme = CONFIG["theme"]
    values = theme["sidebar"] if section == "sidebar" else theme
    assert values[option].upper() == _tokens()[token].upper()


def test_app_config_serves_static_files():
    """The logos and Roboto need static serving, which only this file turns on: the image
    copies all of app/, and Streamlit reads .streamlit/config.toml from where it starts."""
    assert CONFIG["server"]["enableStaticServing"] is True


def test_theme_font_files_exist():
    """The theme's fonts are served from app/static/; a wrong path silently falls back to Arial."""
    for face in CONFIG["theme"]["fontFaces"]:
        assert (APP / face["url"].removeprefix("app/")).is_file(), face["url"]
