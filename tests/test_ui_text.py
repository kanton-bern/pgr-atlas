import ast
from pathlib import Path

import numpy as np
import pytest

import ui_text

REPO = Path(__file__).resolve().parents[1]
# The pipeline's names for the data, which the user doesn't need to know.
PIPELINE_TERMS = ("Data-Lake", "Data Lake", "Gold")


def _user_strings() -> list[str]:
    """Every string literal in ui_text.py except docstrings."""
    tree = ast.parse((REPO / "app" / "ui_text.py").read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _texts_file_strings() -> list[str]:
    """The German and French of every entry in app/texts.toml."""
    texts = ui_text.load_texts(REPO / "app" / "texts.toml")
    return [entry[lang] for entry in texts.values() for lang in ("de", "fr")]


def test_ui_text_names_no_pipeline_terms():
    strings = _user_strings() + _texts_file_strings()
    found = [s for s in strings if any(term in s for term in PIPELINE_TERMS)]
    assert found == []


@pytest.mark.parametrize("key", ["map.tiles.gold_coverage", "map.ifk.gold_coverage"])
def test_map_layer_lists_use_the_same_kacheln_term(key):
    assert ui_text.t(key, lang="de").startswith("Berechnete Kacheln")


@pytest.mark.parametrize("id_anriss", [977441, np.int64(977441), 977441.0])
def test_nav_anriss_shows_the_id_as_an_integer(id_anriss):
    assert ui_text.nav_anriss(id_anriss) == "Anriss 977441"


def _keys_under(prefix: str) -> set[str]:
    texts = ui_text.load_texts(REPO / "app" / "texts.toml")
    return {key.removeprefix(prefix) for key in texts if key.startswith(prefix)}


def test_nav_labels_carry_no_emoji():
    labels = [ui_text.t(f"nav.{key}") for key in _keys_under("nav.") if key != "anriss_id"]
    assert labels
    assert all(char.isalpha() or char in " -()" for label in labels for char in label)


def test_every_gebaeudeschatten_variant_has_a_help():
    from probe_core import gebaeudeschatten as gs

    for variant in gs.VARIANTS:
        assert ui_text.gs_variant_help(variant, 10)


def test_every_derivate_metric_has_a_label_and_help():
    from probe_core.derivate import derivate_lake

    assert _keys_under("derivate.metric_help.") == _keys_under("derivate.metric.")
    assert _keys_under("derivate.metric.") <= set(derivate_lake.PARTITION_KEYS)


@pytest.mark.parametrize("n", [None, float("nan"), float("inf"), -float("inf"), np.nan])
def test_fmt_ch_shows_a_dash_for_no_number(n):
    assert ui_text.fmt_ch(n) == "-"


@pytest.mark.parametrize(
    "n, kwargs, expected",
    [
        (0, {}, "0"),
        (999, {}, "999"),
        (1000, {}, "1'000"),
        (2584, {}, "2'584"),
        (257_579_577, {}, "257'579'577"),
        (np.int64(4754), {}, "4'754"),
        (7.5e6, {}, "7'500'000"),
        (-1_234_567.891, {"digits": 2}, "-1'234'567.89"),
        (999.5, {}, "1'000"),
        (0.004, {"digits": 2}, "0.00"),
        (-0.004, {"digits": 2}, "0.00"),
        (-0.4, {}, "0"),
        (0.001, {"digits": 3}, "0.001"),
        (32.46, {"digits": 1}, "32.5"),
    ],
)
def test_fmt_ch_groups_thousands_with_an_apostrophe(n, kwargs, expected):
    assert ui_text.fmt_ch(n, **kwargs) == expected


@pytest.mark.parametrize(
    "n, kwargs, expected",
    [
        (8.4e-8, {}, "8.4 × 10⁻⁸"),
        (3.88e-9, {"digits": 3}, "3.9 × 10⁻⁹"),
        (-2e-7, {}, "-2.0 × 10⁻⁷"),
        (0.000999, {}, "1.0 × 10⁻³"),
        (1.5e-12, {}, "1.5 × 10⁻¹²"),
        (999_999, {"sci_from": 1e6}, "999'999"),
        (1e6, {"sci_from": 1e6}, "1.0 × 10⁶"),
        (2.2e10, {"sci_from": 1e6}, "2.2 × 10¹⁰"),
        (-3e7, {"sci_from": 1e6}, "-3.0 × 10⁷"),
    ],
)
def test_fmt_ch_writes_tiny_and_huge_numbers_as_a_power_of_ten(n, kwargs, expected):
    assert ui_text.fmt_ch(n, **kwargs) == expected


@pytest.mark.parametrize("n", [0, 1, 12, 123, 1234, 99_999, 1_000_000, 10**15, -54_321])
def test_fmt_ch_without_its_apostrophes_is_the_plain_number(n):
    text = ui_text.fmt_ch(n)
    assert text.replace("'", "") == str(n)
    assert all(len(group) == 3 for group in text.lstrip("-").split("'")[1:])


@pytest.mark.parametrize(
    "size_bytes, expected",
    [
        (0, "0 kB"),
        (400, "1 kB"),
        (41_200, "42 kB"),
        (999_000, "999 kB"),
        (999_001, "1.0 MB"),
        (1_000_000, "1.0 MB"),
        (9_960_000, "10.0 MB"),
        (10_000_000, "10 MB"),
        (365_000_000, "365 MB"),
        (1_000_000_000, "1.0 GB"),
        (8_960_000_000, "9.0 GB"),
    ],
)
def test_file_size(size_bytes, expected):
    assert ui_text.file_size(size_bytes) == expected


def test_anriss_rate_writes_the_rate_as_a_power_of_ten():
    assert ui_text.anriss_rate(6.9e-8) == ("6.9 × 10⁻⁸", "14'492'754")


def test_chip_pixel_writes_lv95_in_the_swiss_format():
    assert ui_text.chip_pixel(2598502.5, 1137502.5) == "Pixel 2'598'502.5 / 1'137'502.5"


def test_ifk_summary_pixel_writes_lv95_in_the_swiss_format():
    text = ui_text.ifk_summary_pixel(2598502.5, 1137502.5)
    assert text == "**Pixel (LV95)** 2'598'502.5 / 1'137'502.5"


@pytest.mark.parametrize(
    ("count", "text"),
    [
        (1, "**1** beitragender Anriss"),
        (124, "**124** beitragende Anrisse"),
        (1_250, "**1'250** beitragende Anrisse"),
    ],
)
def test_ifk_summary_anrisse_counts_in_the_swiss_format(count, text):
    assert ui_text.ifk_summary_anrisse(count) == text


@pytest.mark.parametrize(
    ("years", "shown"),
    [
        (60_766.6, "60'767 Jahre"),
        (999_999.4, "999'999 Jahre"),
        (6_463_221_829.3, "6.5 × 10⁹ Jahre"),
    ],
)
def test_ifk_summary_return_period_is_a_power_of_ten_from_a_million_years(years, shown):
    assert ui_text.ifk_summary_return_period(years) == f"Höchste Wiederkehrperiode **{shown}**"


def test_download_label_names_format_and_size():
    assert ui_text.download_label("Rohdaten", "CSV", 41_000) == "📥 Rohdaten (CSV, 41 kB)"


# ── Numbers in French ────────────────────────────────────────────────────────

NNBSP = "\u202f"  # French Switzerland's thousands group: a narrow no-break space


@pytest.mark.parametrize(
    "n, kwargs, expected",
    [
        (2584, {}, f"2{NNBSP}584"),
        (-1_234_567.891, {"digits": 2}, f"-1{NNBSP}234{NNBSP}567,89"),
        (-0.004, {"digits": 2}, "0,00"),
        (8.4e-8, {}, "8,4 × 10⁻⁸"),
        (2.2e10, {"sci_from": 1e6}, "2,2 × 10¹⁰"),
    ],
)
def test_fmt_ch_writes_french_numbers_in_a_french_session(french_session, n, kwargs, expected):
    assert ui_text.fmt_ch(n, **kwargs) == expected


def test_fmt_ch_writes_the_language_given_in_place_of_the_session(french_session):
    # A number in a downloaded file stays German (Q9).
    assert ui_text.fmt_ch(1234.5, digits=1, lang=ui_text.EXPORT_LANGUAGE) == "1'234.5"
    assert ui_text.depth_m(10, lang=ui_text.EXPORT_LANGUAGE) == "0.10 m"


def test_in_locale_changes_only_the_separators(french_session):
    assert ui_text.in_locale("0.1") == "0,1"
    assert ui_text.in_locale("2'598'502.5") == f"2{NNBSP}598{NNBSP}502,5"
    assert ui_text.in_locale("0.1", lang="de") == "0.1"


@pytest.mark.parametrize(("lang", "locale"), [("de", "de-CH"), ("fr", "fr-CH")])
def test_number_locale_is_the_maps_locale_for_the_language(monkeypatch, lang, locale):
    monkeypatch.setattr(ui_text, "language", lambda: lang)
    assert ui_text.number_locale() == locale


def test_template_keeps_the_placeholders_for_the_map_to_fill():
    assert ui_text.template("map.chrome.zoom_level") == "Zoomstufe = {zoom}"
    with pytest.raises(KeyError, match="map.chrome.nothing"):
        ui_text.template("map.chrome.nothing")
