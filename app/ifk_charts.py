"""The IFK charts: one curve per variable (a pixel's or an area's), in
Experten-Modus with the production curve in grey behind it, and its CSV and
PNG downloads."""

import json

import altair as alt
import streamlit as st
import vl_convert

import ifk_export
import ui_text
from raster_overlay import VARIABLE_UNITS

# The curve's colour (Vega-Lite's default mark colour) and, in Experten-Modus,
# the grey dashed production curve behind it.
_CURVE_COLOR = "#4c78a8"
_ORIGINAL_COLOR = "#9E9E9E"
_ORIGINAL_DASH = [5, 4]


def _number_locale() -> dict:
    """Vega's number format for the session's language, as ui_text.fmt_ch writes
    numbers: 1'000'000 or 1 000 000, not Vega's default 1,000,000."""
    group, decimal = ui_text.NUMBER_SEPARATORS[ui_text.language()]
    return {"decimal": decimal, "thousands": group, "grouping": [3], "currency": ["", ""]}


def style_light_chart(chart):
    """The app's chart styling (Roboto, black text on white, Swiss numbers in the
    session's language); paired with theme=None on st.altair_chart so Streamlit
    doesn't apply its own."""
    return (
        chart.properties(background="white")
        .configure(font="Roboto", locale={"number": _number_locale()})
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelColor="#000000", titleColor="#000000", gridColor="#E0E0E0", domainColor="#999"
        )
        .configure_title(color="#000000")
    )


def _chart_png_bytes(chart):
    """Server-side PNG (vl-convert) for the PNG download: Streamlit's
    vega-lite chart has no image export of its own."""
    return vl_convert.vegalite_to_png(chart.to_dict(), scale=2)


def _curve_line(df, var, series: str | None):
    """One curve as an Altair line. `series` ("original" or "expert") names it
    in the legend and the tooltip; None draws a single curve, without a legend."""
    label = ui_text.t(f"variable.{var}")
    tooltip = [
        alt.Tooltip("return_period:Q", title=ui_text.t("ifk.tooltip_return_period"), format=",.0f"),
        alt.Tooltip("intensity:Q", title=label, format=".2f"),
    ]
    line = alt.Chart(df).mark_line(
        point=True,
        strokeWidth=2,
        strokeDash=_ORIGINAL_DASH if series == "original" else [],
    )
    encoding = {}
    if series is not None:
        if series == "original":
            name = ui_text.t("ifk.series_original")
        else:
            name = ui_text.t("ifk.series_expert")
        line = line.transform_calculate(series=json.dumps(name))
        tooltip.insert(0, alt.Tooltip("series:N", title=ui_text.t("ifk.tooltip_series")))
        encoding["color"] = alt.Color(
            "series:N",
            scale=alt.Scale(
                domain=[ui_text.t("ifk.series_expert"), ui_text.t("ifk.series_original")],
                range=[_CURVE_COLOR, _ORIGINAL_COLOR],
            ),
            legend=alt.Legend(title=None, orient="bottom"),
        )
    return line.encode(
        x=alt.X(
            "return_period:Q",
            title=ui_text.t("ifk.axis_return_period"),
            scale=alt.Scale(type="log"),
            # An area's curve can span seven decades in a third of the page:
            # labels that would run into each other are left out.
            axis=alt.Axis(labelOverlap=True),
        ),
        y=alt.Y("intensity:Q", title=f"{label} [{VARIABLE_UNITS[var]}]"),
        tooltip=tooltip,
        **encoding,
    )


def curve(df, var, file_stem: str, original=None):
    """One variable's curve and its downloads.

    Args:
        df: the curve (intensity, p_exceedance, return_period).
        var: 'depth', 'velocity' or 'pressure'.
        file_stem: the downloads' file name without extension.
        original: the production curve of the same pixel or area, drawn in
            grey behind an Experten-Modus curve and added to its CSV; None
            without Experten-Modus.
    """
    # One bordered card per variable (app.css styles .st-key-ifk_curve_card_*),
    # so the two download buttons belong visibly to the chart above them.
    with st.container(border=True, key=f"ifk_curve_card_{var}"):
        st.markdown(f"**{ui_text.t(f'variable.{var}')}** [{VARIABLE_UNITS[var]}]")
        if df.empty:
            st.caption(ui_text.t("ifk.no_data"))
            return
        if original is None or original.empty:
            original = None
            chart = _curve_line(df, var, None)
        else:
            # The original is the first layer, so the Experten-Modus curve is
            # drawn over it where the two overlap.
            chart = alt.layer(
                _curve_line(original, var, "original"),
                _curve_line(df, var, "expert"),
            )
        chart = chart.properties(height=280)
        st.altair_chart(style_light_chart(chart), width="stretch", theme=None)
        dl_cols = st.columns(2)
        dl_cols[0].download_button(
            ui_text.t("ifk.curve_csv"),
            ifk_export.curve_csv_bytes(df, var, original),
            file_name=f"{file_stem}.csv",
            mime="text/csv",
            key=f"ifk_csv_{var}",
            on_click="ignore",
        )
        dl_cols[1].download_button(
            ui_text.t("ifk.curve_png"),
            _chart_png_bytes(chart),
            file_name=f"{file_stem}.png",
            mime="image/png",
            key=f"ifk_png_{var}",
            on_click="ignore",
        )
