"""Simulierte Ereignisse: the map view a link holds (?z=&lat=&lon=) and the Datenstand numbers."""

from datetime import UTC, datetime

import pytest

from streamlit.testing.v1 import AppTest

from views.overview import Stats, stat_progress, viewport_from_query, viewport_query

_THUN = {"z": "12", "lat": "46.75", "lon": "7.63"}


def test_a_link_with_a_view_gives_it_to_the_map():
    assert viewport_from_query(_THUN) == {"zoom": 12.0, "lat": 46.75, "lon": 7.63}


@pytest.mark.parametrize("params", [{}, {"other": "1"}])
def test_a_link_without_a_view_gives_none(params):
    assert viewport_from_query(params) is None


@pytest.mark.parametrize(
    "params",
    [
        {"z": "12"},  # lat, lon missing
        {"lat": "46.75", "lon": "7.63"},  # z missing
        {**_THUN, "z": "zwölf"},
        {**_THUN, "lat": ""},
        {**_THUN, "lat": "nan"},
        {**_THUN, "lon": "inf"},
        {**_THUN, "z": "6.99"},  # below the map's zoom range
        {**_THUN, "z": "19.01"},
        {**_THUN, "lat": "45.9"},  # south of Kanton Bern
        {**_THUN, "lon": "8.6"},  # east of it
    ],
)
def test_a_link_with_a_bad_view_is_refused(params):
    with pytest.raises(ValueError):
        viewport_from_query(params)


@pytest.mark.parametrize(
    "params",
    [
        {"z": "7", "lat": "46.30", "lon": "6.85"},
        {"z": "19", "lat": "47.35", "lon": "8.46"},
    ],
)
def test_the_edges_of_the_range_are_allowed(params):
    assert viewport_from_query(params) is not None


def test_a_view_written_to_the_link_reads_back():
    view = {"lat": 46.7512345678, "lon": 7.6298765432, "zoom": 13.456789}
    params = viewport_query(view)
    assert params == {"z": "13.46", "lat": "46.75123", "lon": "7.62988"}
    back = viewport_from_query(params)
    assert back == pytest.approx(
        {"lat": view["lat"], "lon": view["lon"], "zoom": view["zoom"]}, abs=0.005
    )


@pytest.mark.parametrize("available, total", [(7960, 7960), (8000, 7960), (0, 0)])
def test_a_count_that_reached_its_total_is_complete(available, total):
    assert stat_progress(available, total) == ("vollständig", None)


@pytest.mark.parametrize(
    "available, total, text, fraction",
    [
        (2584, 7960, "von 7'960 (32.4 %)", 2584 / 7960),
        (0, 4754, "von 4'754 (0.0 %)", 0.0),
        # Rounds down: one missing out of 61 million is not 100 %.
        (61_313_845, 61_313_846, "von 61'313'846 (99.9 %)", 61_313_845 / 61_313_846),
    ],
)
def test_an_incomplete_count_says_how_far_it_is(available, total, text, fraction):
    assert stat_progress(available, total) == (text, pytest.approx(fraction))


def _stats_script():
    import streamlit as st

    from views.overview import _render_stats

    _render_stats(st.container(), st.session_state["stats"])


def _render(gold_kacheln: int, as_of: datetime | None = None) -> AppTest:
    at = AppTest.from_function(_stats_script)
    at.session_state["stats"] = Stats(
        manifest={"anriss_count": 61_313_846, "area_count": 6, "pq_count": 4754},
        gold={"anriss_count": 61_313_846, "area_count": 6, "pq_count": 4754, "sim_count": 2584},
        sim_count=2584,
        gold_kacheln=gold_kacheln,
        total_kacheln=7960,
        as_of=as_of,
    )
    return at.run()


def _summary(at: AppTest) -> str:
    (popover,) = at.get("popover")
    return popover.proto.popover.label


def test_complete_stats_show_each_count_once():
    at = _render(gold_kacheln=7960)
    assert _summary(at) == "Datenstand · vollständig"
    assert [m.value for m in at.metric] == ["4'754", "61'313'846", "6", "2'584", "7'960"]
    assert [c.value for c in at.caption][1:] == ["vollständig"] * 5
    assert not at.get("progress")


def test_the_counts_follow_the_nesting_of_the_data():
    at = _render(gold_kacheln=7960)
    assert [m.label for m in at.metric] == [
        "Prozessquellen",
        "Anrisse",
        "Grössenklassen",
        "Simulationen",
        "Kacheln (1 km²)",
    ]


def test_an_incomplete_stat_shows_the_computed_count_over_its_total():
    at = _render(gold_kacheln=3980)
    assert _summary(at) == "Datenstand · unvollständig"
    assert at.metric[4].label == "Kacheln (1 km²)"
    assert at.metric[4].value == "3'980"
    (bar,) = at.get("progress")
    assert bar.proto.value == 50
    assert bar.proto.text == "von 7'960 (50.0 %)"
    assert [c.value for c in at.caption][1:] == ["vollständig"] * 4


def test_the_caption_gives_the_swiss_day_of_the_newest_gold_file():
    # 22:30 UTC is already the next day in Switzerland.
    at = _render(gold_kacheln=7960, as_of=datetime(2026, 10, 5, 22, 30, tzinfo=UTC))
    assert at.caption[0].value == (
        "Stand vom 06.10.2026. Vergleich mit dem geplanten Umfang für den ganzen Kanton Bern."
    )


def test_the_caption_has_no_date_without_gold():
    at = _render(gold_kacheln=0)
    assert at.caption[0].value == "Vergleich mit dem geplanten Umfang für den ganzen Kanton Bern."
