"""The texts the user reads, looked up in app/texts.toml.

Every visible text of the app (captions, labels, help texts, messages) lives
in app/texts.toml, in German and French. `t(key, **values)` returns a text in
the session's language and fills its {placeholders}. The helpers below hold
what the file can't: choosing between two texts, and formatting numbers and
dates before they go into a text. Code keeps its technical names ("bbox");
the user reads "Rechteck".

Numbers go through fmt_ch, the one number format of the app, in the
session's language (the map components mirror it in
frontend/src/shared/number-format.ts, with the locale number_locale() sends).
"""

import math
import os
import re
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TEXTS_PATH = Path(__file__).with_name("texts.toml")
DEFAULT_LANGUAGE = "de"
# Downloaded files are German in every UI language, so scripts that read their
# headers and labels keep working (Q9).
EXPORT_LANGUAGE = DEFAULT_LANGUAGE
# A {name} in a text; any other brace (the LaTeX in a help text) is a literal character.
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _entries(table: dict, prefix: str = "") -> dict[str, dict]:
    """The file's entries by dotted key: a table with `de` is an entry."""
    if "de" in table:
        return {prefix: table}
    found = {}
    for name, value in table.items():
        found |= _entries(value, f"{prefix}.{name}" if prefix else name)
    return found


def load_texts(path: Path) -> dict[str, dict]:
    """Read a texts file: {"section.name": {"de": ..., "fr": ..., "note": ...}}.

    Raises:
        ValueError: the file isn't valid TOML, with the line and how to fix it.
    """
    try:
        with path.open("rb") as file:
            return _entries(tomllib.load(file))
    except tomllib.TOMLDecodeError as error:
        raise ValueError(
            f"{path.name} can't be read: {error}. Look at that line: each text starts and ends "
            'with a quote ("), and a quote inside a text is written \\".'
        ) from error


# Only for the e2e tests, which run the app with a French version of every text.
_TEXTS = load_texts(Path(os.environ.get("PGR_ATLAS_TEXTS_FILE") or TEXTS_PATH))
# The language of a process with no Streamlit session: the upload parser child
# gets the session's language this way (polygon_upload._run_fenced).
PROCESS_LANGUAGE_ENV = "PGR_ATLAS_LANG"
# Where a session keeps its language (set by language.py).
SESSION_KEY = "lang"


def languages() -> tuple[str, ...]:
    """The languages the user can pick: German, and French once any text has one."""
    if any(entry.get("fr") for entry in _TEXTS.values()):
        return (DEFAULT_LANGUAGE, "fr")
    return (DEFAULT_LANGUAGE,)


def language() -> str:
    """The session's language; outside a Streamlit script run, the process's
    (PROCESS_LANGUAGE_ENV), else German.

    Streamlit is looked up in sys.modules, not imported: the upload parser
    child and the derivate sidecar import this module and must stay light.
    """
    streamlit = sys.modules.get("streamlit")
    if (
        streamlit is None
        or streamlit.runtime.scriptrunner.get_script_run_ctx(suppress_warning=True) is None
    ):
        return os.environ.get(PROCESS_LANGUAGE_ENV, DEFAULT_LANGUAGE)
    return streamlit.session_state.get(SESSION_KEY, DEFAULT_LANGUAGE)


def _text(key: str, lang: str | None) -> str:
    if key not in _TEXTS:
        raise KeyError(f"No text {key!r} in {TEXTS_PATH.name}.")
    entry = _TEXTS[key]
    return entry.get(lang or language()) or entry["de"]


def template(key: str, /, lang: str | None = None) -> str:
    """The text `key` in the session's language with its {placeholders} unfilled,
    for a map component that fills them itself (map_labels.py). An empty
    translation falls back to German; lang: as for t().

    Raises:
        KeyError: no text `key`.
    """
    return _text(key, lang)


def t(key: str, /, lang: str | None = None, **values) -> str:
    """The text `key` in the session's language, with its placeholders filled.

    An empty translation falls back to German. Values are inserted with str().

    Args:
        key: the entry in texts.toml.
        lang: a language in place of the session's; EXPORT_LANGUAGE for what
            goes into a downloaded file.
        **values: one per {placeholder} of the text.

    Raises:
        KeyError: no text `key`, or the text has a placeholder with no value.
        TypeError: a value has no placeholder in the text.
    """
    text = _text(key, lang)
    names = set(PLACEHOLDER.findall(text))
    if missing := names - values.keys():
        raise KeyError(f"Text {key!r} needs a value for {sorted(missing)}; got {sorted(values)}.")
    if extra := values.keys() - names:
        raise TypeError(f"Text {key!r} has no placeholder for {sorted(extra)}: {text!r}.")
    return PLACEHOLDER.sub(lambda match: str(values[match.group(1)]), text)


_SUPERSCRIPT = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")
# Below this a plain decimal is mostly zeros: 0.00000008 reads as 8.0 × 10⁻⁸.
_SCI_BELOW = 1e-3
_SWISS_TIME = ZoneInfo("Europe/Zurich")
# The map components' locale per language (frontend/src/shared/texts.ts).
NUMBER_LOCALES = {"de": "de-CH", "fr": "fr-CH"}
# Thousands group and decimal mark per language, as number-format.ts writes
# them: German Switzerland 2'584.5, French Switzerland 2 584,5 (narrow no-break space).
NUMBER_SEPARATORS = {"de": ("'", "."), "fr": ("\u202f", ",")}


def number_locale(lang: str | None = None) -> str:
    """The map components' `locale` for the session's language: "de-CH" or "fr-CH"."""
    return NUMBER_LOCALES[lang or language()]


def in_locale(number: str, lang: str | None = None) -> str:
    """A number written the Python way ("2'584.5", "0.1") in the session's language.

    For numbers fmt_ch can't write, e.g. f"{threshold:g}". lang: as for t().
    """
    group, decimal = NUMBER_SEPARATORS[lang or language()]
    return number.translate(str.maketrans({"'": group, ".": decimal}))


def fmt_ch(n, digits: int = 0, sci_from: float = math.inf, lang: str | None = None) -> str:
    """A number in the app's Swiss format, in the session's language.

    German: ' groups thousands ("2'584"), "." is the decimal point. French: a
    narrow no-break space groups ("2 584"), "," is the decimal comma. A value
    below 0.001 (other than 0), or from `sci_from` on, is written as a power
    of ten with one decimal: "8.4 × 10⁻⁸".

    Args:
        n: the number; None, NaN and ±inf read "-".
        digits: decimals of a plain number.
        sci_from: the magnitude from which a large number is a power of ten
            too (return periods past 10⁶ years); by default never.
        lang: as for t(); EXPORT_LANGUAGE for a number in a downloaded file.
    """
    if n is None or not math.isfinite(n):
        return "-"
    magnitude = abs(n)
    if (0 < magnitude < _SCI_BELOW) or magnitude >= sci_from:
        mantissa, exponent = f"{n:.1e}".split("e")
        power = f"{mantissa} × 10{str(int(exponent)).translate(_SUPERSCRIPT)}"
        return in_locale(power, lang)
    text = f"{n:,.{digits}f}".replace(",", "'")
    # -0.004 rounds to "-0.00": a zero has no sign.
    unsigned = text.lstrip("-") if float(text.replace("'", "")) == 0 else text
    return in_locale(unsigned, lang)


def file_size(size_bytes: int) -> str:
    """A download's size: "1.2 GB", "365 MB", "4.5 MB", or "41 kB" below 1 MB
    (rounded up, so a small file never reads 0 kB)."""
    if size_bytes >= 1e9:
        return t("unit.gb", value=fmt_ch(size_bytes / 1e9, digits=1))
    if size_bytes > 999_000:
        return t("unit.mb", value=fmt_ch(size_bytes / 1e6, digits=1 if size_bytes < 1e7 else 0))
    return t("unit.kb", value=fmt_ch(math.ceil(size_bytes / 1e3)))


# Not translated: the app's name, and where feedback on the app goes. One
# place, so both notes that name the contact change together. support@ takes
# everything client-facing; alerts go to alert@ (docs/monitoring.md).
APP_NAME = "PGR-Atlas"
FEEDBACK_CONTACT = "support@skerlak.ch"


def chip_pixel(e: float, n: float) -> str:
    """The header chip of a selected pixel, in LV95: "Pixel 2'598'502.5 / 1'137'502.5"."""
    return t("header.chip_pixel", e=fmt_ch(e, digits=1), n=fmt_ch(n, digits=1))


def chip_building(id_start: int) -> str:
    return t("header.chip_building", id=int(id_start))


def overview_stats_caption(as_of: datetime | None) -> str:
    """The line under "Datenstand", e.g. "Stand vom 06.10.2026. Vergleich ...".

    Args:
        as_of: when the newest gold file was written, with its time zone; the
            day is the Swiss one. None (no gold yet) leaves the date out.
    """
    if as_of is None:
        return t("overview.stats_caption_undated")
    day = as_of.astimezone(_SWISS_TIME).strftime("%d.%m.%Y")
    return t("overview.stats_caption", date=day)


def nav_anriss(id_anriss: int) -> str:
    """The open Anriss in the navigation and as its page title, e.g. "Anriss 977441"."""
    return t("nav.anriss_id", page=t("nav.anriss"), id=int(id_anriss))


def lookup_unknown(id_anriss: int) -> str:
    """The Anriss-ID lookup's error for an ID that isn't in the manifest."""
    return t("lookup.unknown", id=int(id_anriss))


def ifk_summary_pixel(e: float, n: float) -> str:
    """'**Pixel (LV95)** 2'598'502.5 / 1'137'502.5'."""
    return t("ifk.summary_pixel", e=fmt_ch(e, digits=1), n=fmt_ch(n, digits=1))


def ifk_summary_anrisse(count: int) -> str:
    """'**124** beitragende Anrisse', '**1** beitragender Anriss'."""
    if count == 1:
        return t("ifk.summary_anrisse_one")
    return t("ifk.summary_anrisse", count=fmt_ch(count))


def ifk_summary_return_period(years: float) -> str:
    """'Höchste Wiederkehrperiode **6.5 × 10⁹ Jahre**'; from 10⁶ years a power
    of ten, as in the raster legends."""
    return t("ifk.summary_return_period", years=fmt_ch(years, sci_from=1e6))


def ifk_area_rohdaten(file_format: str, n_ereignisse: int) -> str:
    """The Rohdaten link of an area: 'CSV' or 'Parquet' and the row count."""
    return t("ifk_area.rohdaten", file_format=file_format, n_ereignisse=fmt_ch(n_ereignisse))


def expert_p_h_caption(default: float) -> str:
    """The p_h expander's caption: the production split."""
    return t(
        "expert.p_h_caption", mean=fmt_ch(default, digits=2), max=fmt_ch(1 - default, digits=2)
    )


def expert_ablauf_sum_ok(total: float) -> str:
    return t("expert.ablauf_sum_ok", total=in_locale(f"{total:.6f}"))


def expert_ablauf_sum_invalid(total: float) -> str:
    return t("expert.ablauf_sum_invalid", total=in_locale(f"{total:.6f}"))


def ifk_no_process(x: float, y: float) -> str:
    """A finished kachel's pixel that no simulated process reaches."""
    return t("ifk.no_process", x=in_locale(f"{x:.1f}"), y=in_locale(f"{y:.1f}"))


def ifk_no_kachel(x: float, y: float) -> str:
    """A pixel outside every finished SIM_SPATIAL kachel."""
    return t("ifk.no_kachel", x=in_locale(f"{x:.1f}"), y=in_locale(f"{y:.1f}"))


def anriss_gold_not_ready(pending_kacheln) -> str:
    return t("anriss.gold_not_ready", n=len(pending_kacheln), kacheln=pending_kacheln)


def anriss_rate(lambda_ereignis: float) -> tuple[str, str]:
    """The scenario's rate and its return period in years, as the Statistik shows them."""
    return fmt_ch(lambda_ereignis, digits=3), fmt_ch(1.0 / lambda_ereignis)


def version_footer(version: str, source: str, bucket: str) -> str:
    """Version, S3 source and bucket: which app reads which data."""
    return (
        f"<div class='pgr-version'>{t('app.version', version=version)}<br>"
        f"{t('app.data_source', source=source, bucket=bucket)}</div>"
    )


def raster_too_many_kacheln(area_km2: float, n_kacheln: int, max_kacheln: int) -> str:
    return t(
        "raster.too_many_kacheln",
        area_km2=fmt_ch(area_km2, digits=2),
        n_kacheln=n_kacheln,
        max_kacheln=max_kacheln,
    )


def download_label(label: str, file_format: str, size_bytes: int) -> str:
    """A download button's label: what, format and size, e.g. "📥 Fliesstiefe [m]
    (GeoTIFF, 41 kB)"."""
    return t(
        "app.download_button", label=label, file_format=file_format, size=file_size(size_bytes)
    )


def raster_download(label: str, size_bytes: int) -> str:
    """A result's download button, e.g. "📥 Fliesstiefe ≥ 0.1 m, Wiederkehrperiode
    (GeoTIFF, 1.2 MB)"."""
    return download_label(label, "GeoTIFF", size_bytes)


def derivate_metric_option(label: str, available: bool) -> str:
    return label if available else t("derivate.metric_no_data_option", label=label)


def derivate_band_threshold(threshold: float, unit: str) -> str:
    return t("derivate.band_threshold", threshold=in_locale(f"{threshold:g}"), unit=unit)


def derivate_band_return_period(return_period: int) -> str:
    return t("derivate.band_return_period", return_period=fmt_ch(return_period))


def derivate_band_min_h(min_h: float) -> str:
    return t("derivate.band_min_h", min_h=in_locale(f"{min_h:g}"))


def derivate_missing_mosaic(datasets: list[str]) -> str:
    return t("derivate.missing_mosaic", datasets=", ".join(datasets))


def derivate_zip_size(kind: str, size_bytes: int) -> str:
    """The Kacheln ZIP's size is exact; the Ausschnitt's an upper bound."""
    size = t("unit.mb", value=in_locale(f"{size_bytes / 1e6:.1f}"))
    if kind == "kacheln":
        return size
    return t("derivate.zip_size_estimate", size=size)


def derivate_kanton_download(dataset: str, size_bytes: int) -> str:
    return t("derivate.kanton_download", dataset=dataset, size=file_size(size_bytes))


def derivate_kanton_bands(bands: list[tuple[int, str]]) -> str:
    """The bands of one canton file, e.g. "Band 1: ≥ 0.1 m · Band 2: ≥ 0.5 m"."""
    return " · ".join(t("derivate.kanton_band", index=index, label=label) for index, label in bands)


def depth_m(cm: int, lang: str | None = None) -> str:
    """A depth gold stores in whole cm, shown in m: 10 -> "0.10 m". cm is only
    gold's integer encoding; the client sees m and m/s. lang: as for t()."""
    return t("unit.m", lang=lang, value=fmt_ch(cm / 100, digits=2, lang=lang))


def gs_variant_help(variant: str, min_depth: int) -> str:
    return t(f"gs.variant_help.{variant}", min_depth=depth_m(min_depth))


def gs_min_depth_option(cm: int) -> str:
    return depth_m(cm)


def gs_cell_tooltip(kind: str, depth: int, n_sims: int, status: str) -> str:
    """kind is GS_OWN_PIXEL / GS_RING_PIXEL or '' for a pixel outside both masks."""
    prefix = f"{kind}\n" if kind else ""
    return prefix + t("gs.cell_tooltip", depth=depth_m(depth), n_sims=n_sims, status=status)


def gs_shadowing_tooltip(id_start: int, kind: str, counts: bool) -> str:
    if counts:
        return t("gs.shadowing_tooltip_counts", id_start=id_start, kind=kind)
    return t("gs.shadowing_tooltip_not_counts", id_start=id_start, kind=kind)


def gs_mask_label(variant_label: str, reach_label: str, min_depth: int) -> str:
    return t(
        "gs.mask_label",
        variant_label=variant_label,
        reach_label=reach_label,
        min_depth=depth_m(min_depth),
    )


def gs_pixel_heading(e: float, n: float) -> str:
    return t("gs.pixel_heading", e=in_locale(f"{e:.1f}"), n=in_locale(f"{n:.1f}"))


def gs_excluded_summary(counts: dict) -> str:
    """counts: {reason label: number of pixels}."""
    items = (
        t("gs.excluded_summary_item", reason=reason, count=count)
        for reason, count in counts.items()
    )
    return t("gs.excluded_summary", reasons=" · ".join(items))


def gs_pixel_summary(n_counting: int, n_reaching: int, variant_label: str, min_depth: int) -> str:
    return t(
        "gs.pixel_summary",
        n_counting=n_counting,
        n_reaching=n_reaching,
        variant_label=variant_label,
        min_depth=depth_m(min_depth),
    )


def overlay_label_return_period(variable: str | None, threshold, unit: str) -> str:
    """Mode A legend: 'Fliesstiefe ≥ 0.5 m, Wiederkehrperiode' (no threshold: the measure alone)."""
    if threshold is None:
        return t("legend.return_period")
    threshold = in_locale(f"{threshold:g}")
    return t("overlay.return_period", variable=variable, threshold=threshold, unit=unit)


def overlay_label_intensity(variable: str, return_period) -> str:
    """Mode B legend: 'Fliesstiefe bei Wiederkehrperiode 300 Jahre'."""
    if return_period is None:
        return variable
    return t("overlay.intensity", variable=variable, return_period=fmt_ch(return_period))


def upload_zip_ratio(name: str, ratio: float, max_ratio: int) -> str:
    return t("upload.zip_ratio", name=name, ratio=fmt_ch(ratio), max_ratio=max_ratio)


# The friction parameters, as the user reads them; the code and the CSV
# columns keep mu, xsi, tau0. Symbols, so not translated.
PARAM_LABELS = {"mu": "μ", "xsi": "ξ", "tau0": "τ₀"}


# ── Download file names ──────────────────────────────────────────────────────
# One style for every file the user downloads: lower case, German without
# umlauts, parts joined by "_", in the order product, metric, variable,
# parameter, area. Decimal points become "_" (0.7 m -> "0_7m"), as in the
# derivate lake's band names. Keys are gold's and the derivate lake's names.
# Not translated, so scripts that read the files keep working (Q9).

FILE_VARIABLES = {"depth": "fliesstiefe", "velocity": "fliessgeschwindigkeit", "pressure": "druck"}
FILE_METRICS = {
    "return_period": "wiederkehrperiode",
    "intensity": "intensitaet",
    "hit_rate": "trefferhaeufigkeit",
    "combined_hit_rate": "trefferhaeufigkeit",
    "start_rate": "anrisshaeufigkeit",
    "sim_count": "anzahl_simulationen",
    "affected_mask": "betroffen",
}
# The pipeline's combo names; an unknown one keeps its raw name.
FILE_COMBOS = {"depth01_pressure3": "fliesstiefe_und_druck"}
# Gebäudeschatten variants (probe_core.gebaeudeschatten.VARIANTS).
FILE_GS_VARIANTS = {
    "raw": "roh",
    "shadowing_building": "ohne_eigenes_gebaeude",
    "shadowing_building_surrounding": "ohne_eigenes_gebaeude_und_umgebung",
}
FILE_EXPERT_SUFFIX = "_expertenmodus"


def file_number(value) -> str:
    """A number as a file-name part: 0.7 -> "0_7", 1.0 -> "1", 10000 -> "10000"."""
    number = float(value)
    text = str(int(number)) if number == int(number) else f"{number:g}"
    return text.replace(".", "_").replace("-", "neg")


def derivate_file_stem(metric: str, partition: str | None) -> str:
    """'derivat_wiederkehrperiode_fliesstiefe' / 'derivat_anzahl_simulationen':
    the start of a Derivate download's name. partition is the variable or the
    combo, None for an unpartitioned metric."""
    parts = ["derivat", FILE_METRICS.get(metric, metric)]
    if partition is not None:
        parts.append(FILE_VARIABLES.get(partition) or FILE_COMBOS.get(partition, partition))
    return "_".join(parts)


# ── Fixed export texts (not translated, Q9) ──────────────────────────────────
# Used only inside downloaded files: the Gebäudeschatten CSV columns and
# values, and the band descriptions of its GeoTIFF.

GS_CSV_MASK = "Maske"
GS_CSV_MASK_MEANING = "Maske (Bedeutung)"
GS_CSV_MASK_NONE = "übriger Pixel (Maske 0)"
GS_TIF_BAND_MASK = "Maske (1 = Gebäudepixel, 2 = Nachbarpixel, 0 = übrige)"
GS_TIF_BAND_COUNTS = "abgeschattet (1 = zählt, 0 = ausgeschlossen)"
GS_TIF_BAND_DEPTH = "Fliesstiefe max [m]"
GS_TIF_BAND_SIMS = "Anzahl Simulationen"
