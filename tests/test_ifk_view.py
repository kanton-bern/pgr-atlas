"""IFK: the pixel a link selects (?x=&y=), the summary above the curves, and the
curves' number format."""

import re

import altair as alt
import pandas as pd
import pytest
import vl_convert

from tests.lake_data import IFK_PIXEL, IFK_PIXEL_OUTSIDE
from ifk_charts import style_light_chart
from ui_common import snap_to_pixel
from views.ifk import pixel_from_query, pixel_query, result_summary

_LINK = {"x": "2598502.5", "y": "1137502.5"}


@pytest.mark.parametrize(
    ("value", "centre"),
    [
        (2598502.5, 2598502.5),  # already a pixel centre
        (2598500.1, 2598502.5),
        (2598504.9, 2598502.5),
        (2598505.0, 2598507.5),  # halfway between two centres: up, like Math.round in the map
        (2598500.0, 2598502.5),
        (1137499.9, 1137497.5),
    ],
)
def test_a_coordinate_snaps_to_the_nearest_pixel_centre(value, centre):
    assert snap_to_pixel(value) == centre


def test_a_link_with_a_pixel_selects_it():
    assert pixel_from_query(_LINK) == IFK_PIXEL


def test_a_link_off_the_pixel_centre_selects_the_pixel_it_is_in():
    assert pixel_from_query({"x": "2598501", "y": "1137504.99"}) == IFK_PIXEL


@pytest.mark.parametrize("params", [{}, {"other": "1"}, {"z": "12"}])
def test_a_link_without_a_pixel_gives_none(params):
    assert pixel_from_query(params) is None


@pytest.mark.parametrize(
    "params",
    [
        {"x": "2598502.5"},  # y missing
        {"y": "1137502.5"},  # x missing
        {**_LINK, "x": "zwei"},
        {**_LINK, "y": ""},
        {**_LINK, "x": "nan"},
        {**_LINK, "y": "inf"},
        # Far outside LV95, where the projection wraps around into Kanton Bern.
        {**_LINK, "y": "22267500"},
        {"x": "7.63", "y": "46.75"},  # WGS84 instead of LV95
        {"x": str(IFK_PIXEL_OUTSIDE[0]), "y": str(IFK_PIXEL_OUTSIDE[1])},  # Zürich
        {"x": "2500000", "y": "1117500"},  # Lac Léman, in LV95 but west of Kanton Bern
    ],
)
def test_a_bad_pixel_link_raises(params):
    with pytest.raises(ValueError):
        pixel_from_query(params)


def test_a_pixel_written_to_a_link_reads_back():
    params = pixel_query(IFK_PIXEL)
    assert params == _LINK
    assert pixel_from_query(params) == IFK_PIXEL


def test_a_pixel_outside_kanton_bern_gives_no_link():
    assert pixel_query(IFK_PIXEL_OUTSIDE) is None


def test_curve_axes_group_thousands_the_swiss_way():
    df = pd.DataFrame({"return_period": [10, 100_000, 3_000_000], "intensity": [0.1, 1.0, 2.0]})
    chart = (
        alt.Chart(df)
        .mark_line()
        .encode(x=alt.X("return_period:Q", scale=alt.Scale(type="log")), y="intensity:Q")
    )
    labels = re.findall(
        r">([\d',.]+)</text>", vl_convert.vegalite_to_svg(style_light_chart(chart).to_dict())
    )
    assert "1'000'000" in labels
    assert not any("," in label for label in labels)


def _curve(return_periods):
    return pd.DataFrame(
        {
            "intensity": range(len(return_periods)),
            "p_exceedance": [1 / t for t in return_periods],
            "return_period": return_periods,
        }
    )


def _result(anriss_rates, curves):
    anrisse = pd.DataFrame(
        {
            "id_anriss": range(len(anriss_rates)),
            "lambda_ereignis_sum": anriss_rates,
        }
    )
    return {
        "anriss_events": anrisse,
        "curves": dict(zip(["depth", "velocity", "pressure"], curves)),
    }


def test_summary_counts_the_anrisse_and_takes_the_highest_return_period_of_all_curves():
    result = _result(
        [1e-6, 2e-9, 3e-11],
        [_curve([60_000.0, 4e6]), _curve([60_000.0, 6.4e9]), _curve([60_000.0, 6.4e9])],
    )
    assert result_summary(result) == (3, 6.4e9)


def test_summary_leaves_out_anrisse_set_to_zero_and_infinite_return_periods():
    """Experten-Modus can set an Anriss's rate to zero: an intensity only its
    events reach has p_exceedance 0, so an infinite return period."""
    result = _result(
        [1e-6, 0.0],
        [_curve([60_000.0, float("inf")]), _curve([60_000.0, 2e5]), _curve([])],
    )
    assert result_summary(result) == (1, 2e5)


def test_summary_of_empty_curves_has_no_return_period():
    result = _result([], [_curve([]), _curve([]), _curve([])])
    assert result_summary(result) == (0, None)
