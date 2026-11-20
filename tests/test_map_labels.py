"""The texts and locale the map components get (app/map_labels.py)."""

import pytest

import map_labels


def test_render_args_are_german_with_the_de_ch_locale_by_default():
    args = map_labels.render_args(map_labels.chrome())
    assert args["locale"] == "de-CH"
    assert args["labels"]["layers"] == "Layer"
    assert args["labels"]["zoom_level"] == "Zoomstufe = {zoom}"


def test_render_args_send_french_texts_and_the_fr_ch_locale_in_a_french_session(french_session):
    args = map_labels.render_args(map_labels.chrome(), map_labels.selection())
    assert args["locale"] == "fr-CH"
    assert args["labels"]["draw_rect"] == "[FR] 📐 Rechteck zeichnen"
    assert all(text.startswith("[FR] ") for text in args["labels"].values())


def test_a_later_group_replaces_an_earlier_groups_text():
    labels = map_labels.render_args(map_labels.tiles(), {"gold_coverage": "own"})["labels"]
    assert labels["gold_coverage"] == "own"
    assert labels["prozessquellen"] == "Prozessquellen"


@pytest.mark.parametrize(
    "group", [map_labels.chrome, map_labels.tiles, map_labels.selection, map_labels.anriss_popup]
)
def test_every_shared_group_reads_its_texts(group):
    assert all(group().values())
