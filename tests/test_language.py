"""The session's language from a link and back into the URL (app/language.py)."""

import pytest

import language


@pytest.mark.parametrize(
    ("params", "lang"),
    [
        ({"lang": "fr"}, "fr"),
        ({"lang": "de", "x": "2598502.5"}, "de"),
        ({}, "de"),
        # A language the app doesn't have, or one that isn't one at all.
        ({"lang": "it"}, "de"),
        ({"lang": "FR"}, "de"),
        ({"lang": ""}, "de"),
    ],
)
def test_a_link_picks_a_language_the_app_has(params, lang):
    assert language.language_from_query(params, ("de", "fr")) == lang


def test_a_link_asking_for_french_opens_german_until_there_is_french():
    assert language.language_from_query({"lang": "fr"}, ("de",)) == "de"


def test_a_url_that_replaces_the_params_keeps_french():
    params = {"x": "2598502.5", "y": "1137502.5"}
    assert language.with_language(params, "fr") == {**params, "lang": "fr"}
    assert language.with_language({}, "fr") == {"lang": "fr"}


def test_german_is_not_written_into_the_url():
    assert language.with_language({"id": "7"}, "de") == {"id": "7"}
