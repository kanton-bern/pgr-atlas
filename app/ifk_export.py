"""Downloads of the IFK view (a pixel or an area): file names and CSV columns. Kept out of app.py
so they can be tested without Streamlit or S3 (tests/test_ifk_export.py).

compute_ifk_default's intensities are in the display units (m, m/s, kN/m²,
raster_overlay.VARIABLE_UNITS), so the headers say so -- the Anriss view's
Rohdaten convert gold's cm and cm/s to these units too (anriss_export)."""

import pandas as pd

import ui_text
from raster_overlay import VARIABLE_UNITS


def intensity_label(variable: str) -> str:
    """'depth' -> 'Fliesstiefe', in every UI language (Q9)."""
    return ui_text.t(f"variable.{variable}", lang=ui_text.EXPORT_LANGUAGE)


def intensity_header(variable: str) -> str:
    """'depth' -> 'Fliesstiefe [m]'."""
    return f"{intensity_label(variable)} [{VARIABLE_UNITS[variable]}]"


RETURN_PERIOD_HEADER = "Wiederkehrperiode [Jahre]"
# p_exceedance is an annual rate (the summed lambda_Ereignis of every event at
# least this intense), not a probability -- hence lambda_, like lambda_Ereignis.
EXCEEDANCE_HEADER = "lambda_Überschreitung"
# The production values next to an Experten-Modus curve.
EXCEEDANCE_ORIGINAL_HEADER = "lambda_Überschreitung_original"
RETURN_PERIOD_ORIGINAL_HEADER = "Wiederkehrperiode_original [Jahre]"

_VARIABLES = ("depth", "velocity", "pressure")


def _rohdaten_rename() -> dict[str, str]:
    return {
        **{v: intensity_header(v) for v in _VARIABLES},
        "p_ablauf": "p_Ablauf",
        "lambda_ereignis": "lambda_Ereignis",
    }


def pixel_slug(x, y) -> str:
    """Pixel centers sit at k*5 + 2.5; file names cut them down to whole
    metres (2600002.5 -> 2600002), like probe-core's Raster-Karten names."""
    return f"{int(x)}_{int(y)}"


def _expert_suffix(expert: bool) -> str:
    return ui_text.FILE_EXPERT_SUFFIX if expert else ""


def curve_file_stem(variable: str, x, y, expert: bool) -> str:
    return f"ifk_{ui_text.FILE_VARIABLES[variable]}_{pixel_slug(x, y)}{_expert_suffix(expert)}"


def rohdaten_file_name(x, y, expert: bool) -> str:
    return f"ifk_rohdaten_{pixel_slug(x, y)}{_expert_suffix(expert)}.csv"


def wahrscheinlichkeiten_file_name(x, y) -> str:
    """The Experten-Modus probabilities (JSON) behind a pixel's curves."""
    return f"ifk_wahrscheinlichkeiten_{pixel_slug(x, y)}{_expert_suffix(True)}.json"


def curve_csv_bytes(
    curve: pd.DataFrame, variable: str, original: pd.DataFrame | None = None
) -> bytes:
    """One variable's curve (intensity, p_exceedance, return_period) with the
    columns named in German, with their units.

    Args:
        original: the production curve of the same pixel, for an
            Experten-Modus curve. Its rate and return period are added per
            intensity as '..._original' columns.
    """
    if original is not None:
        curve = curve.merge(
            original, on="intensity", how="outer", suffixes=("", "_original")
        ).sort_values("intensity")
    out = curve.rename(
        columns={
            "intensity": intensity_header(variable),
            "p_exceedance": EXCEEDANCE_HEADER,
            "return_period": RETURN_PERIOD_HEADER,
            "p_exceedance_original": EXCEEDANCE_ORIGINAL_HEADER,
            "return_period_original": RETURN_PERIOD_ORIGINAL_HEADER,
        }
    )
    return out.to_csv(index=False).encode("utf-8-sig")


def area_rohdaten_column_names() -> dict[str, str]:
    """The Rohdaten columns of an area: probe-core's AREA_EREIGNISSE_COLUMNS,
    where the intensities are the simulation's maxima over the area."""
    return {
        **{v: f"{intensity_label(v)} max [{VARIABLE_UNITS[v]}]" for v in _VARIABLES},
        "pixel_count": "Anzahl Pixel",
        "p_ablauf": "p_Ablauf",
        "lambda_ereignis": "lambda_Ereignis",
    }


# Above this many events the Rohdaten of an area are Parquet: Excel opens at
# most 1'048'576 rows.
AREA_ROHDATEN_CSV_MAX_ROWS = 1_000_000


def area_slug(selection: dict) -> str:
    """The area's bounding rectangle in whole metres, like probe-core's
    Raster-Karten names: 2598450_1137450_2598555_1137555."""
    eastings = [point[0] for point in selection["ring"]]
    northings = [point[1] for point in selection["ring"]]
    return f"{int(min(eastings))}_{int(min(northings))}_{int(max(eastings))}_{int(max(northings))}"


def area_curve_file_stem(variable: str, selection: dict, expert: bool) -> str:
    return (
        f"ifk_gebiet_{ui_text.FILE_VARIABLES[variable]}_{area_slug(selection)}"
        f"{_expert_suffix(expert)}"
    )


def area_rohdaten_file_name(selection: dict, expert: bool, extension: str) -> str:
    """extension: 'csv' or 'parquet'."""
    return f"ifk_gebiet_rohdaten_{area_slug(selection)}{_expert_suffix(expert)}.{extension}"


def area_wahrscheinlichkeiten_file_name(selection: dict) -> str:
    """The Experten-Modus probabilities (JSON) behind an area's curves."""
    return f"ifk_gebiet_wahrscheinlichkeiten_{area_slug(selection)}{_expert_suffix(True)}.json"


def rohdaten_csv_bytes(ereignisse: pd.DataFrame) -> bytes:
    """compute_ifk_default's 'ereignisse': one row per event reaching the
    pixel, intensities renamed with their units and p_Ablauf/lambda_Ereignis
    spelled like the rest of the app."""
    return ereignisse.rename(columns=_rohdaten_rename()).to_csv(index=False).encode("utf-8-sig")
