"""The legal pages: every file exists, the language fallback, the H1 split."""

from pathlib import Path

import pytest
from views import legal


@pytest.mark.parametrize("name", legal.PAGES)
def test_every_page_has_a_german_file_with_a_title(name):
    title, body = legal.load_page(name, "de")

    assert title
    assert body.strip()


@pytest.mark.parametrize("name", legal.PAGES)
def test_body_has_no_h1_left(name):
    _, body = legal.load_page(name, "de")

    assert not any(line.startswith("# ") for line in body.splitlines())


def test_split_title_removes_only_the_first_line():
    title, body = legal.split_title("# Kontakt\n\n## Fragen\n\nText\n")

    assert title == "Kontakt"
    assert body == "## Fragen\n\nText\n"


def test_split_title_rejects_a_file_without_h1():
    with pytest.raises(ValueError, match="must start with a '# Title'"):
        legal.split_title("## Fragen\n\nText\n")


def test_language_file_wins_over_german(tmp_path: Path):
    (tmp_path / "kontakt.de.md").write_text("# Kontakt\n\nDeutsch\n", encoding="utf-8")
    (tmp_path / "kontakt.fr.md").write_text("# Contact\n\nFrançais\n", encoding="utf-8")

    assert legal.load_page("kontakt", "fr", tmp_path) == ("Contact", "Français\n")


def test_missing_language_falls_back_to_german(tmp_path: Path):
    (tmp_path / "kontakt.de.md").write_text("# Kontakt\n\nDeutsch\n", encoding="utf-8")

    assert legal.load_page("kontakt", "fr", tmp_path) == ("Kontakt", "Deutsch\n")


def test_missing_file_names_what_was_looked_for(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match=r"kontakt\.fr\.md.*kontakt\.de\.md"):
        legal.page_path("kontakt", "fr", tmp_path)


def test_page_function_rejects_an_unknown_page():
    with pytest.raises(ValueError, match="Unknown legal page"):
        legal.page_function("datenschutz")


def test_page_function_is_named_after_the_page():
    assert legal.page_function("impressum").__name__ == "impressum"


def test_links_between_legal_pages_keep_a_non_german_language():
    text = "Siehe [Impressum](impressum) und [Daten](rechtliches#simulationsdaten)."

    assert legal.keep_language_in_links(text, "fr") == (
        "Siehe [Impressum](impressum?lang=fr) und [Daten](rechtliches?lang=fr#simulationsdaten)."
    )


def test_links_stay_as_written_in_german():
    text = "Siehe [Impressum](impressum)."

    assert legal.keep_language_in_links(text, "de") == text


def test_other_links_are_left_alone():
    text = "[Kontaktformular](https://example.org/impressum) und [x](impressum-alt)"

    assert legal.keep_language_in_links(text, "fr") == text


def _legal_script() -> None:
    from views import legal

    legal.render("kontakt", on_close=lambda: None)


def _legal_script_without_close() -> None:
    from views import legal

    legal.render("kontakt")


def test_a_legal_page_has_a_close_button_when_given_a_close_action():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_legal_script).run()

    assert not at.exception
    assert [b.key for b in at.button] == ["pgr_legal_close"]


def test_a_legal_page_has_no_close_button_without_a_close_action():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_legal_script_without_close).run()

    assert not at.exception
    assert len(at.button) == 0
