"""Raster-Derivate: the precomputed rasters of the derivate lake, previewed on
the map and downloaded for a drawn area.

The sidebar picks the metric, its variable (or combination) and the band of
the canton mosaic; the map draws that band live from derivate_bbox_server.py
and the precomputed kacheln as its coverage. Once an area is drawn, the
download section below the map offers two ZIPs: the area cropped from the
canton mosaics, and the kachel files it touches.

The data is the derivate lake written by the pipeline's derivate/run_derivate.py
(paths + discovery: probe_core.derivate.derivate_lake). Everything is
discovered from S3 (metrics, variables/combos, bands from the canton mosaic's
stats JSON), never from a config file -- new thresholds, a new combo or a
freshly built mosaic show up by themselves after the cache ttl. Display order
+ labels: _METRICS and texts.toml; a metric without any data on S3 is marked
in the picker and shows a note instead of the map.

The map is not in a fragment: the sidebar shows the area's size, so a new
selection has to rerun the whole page anyway.
"""

import json
import logging
from typing import NamedTuple
from urllib.parse import urlencode

import geopandas as gpd
import streamlit as st
from shapely.geometry import box

import coverage_store
import derivate_download
import language
import raster_jobs
import ui_text
from downloads_cue_component import downloads_cue, downloads_section
from probe_core.data_lake import data_interface as data
from probe_core.derivate import derivate_lake, ifk_and_raster
from raster_bbox_component import raster_bbox_map
from raster_overlay import VARIABLE_UNITS
from raster_utils import RETURN_PERIOD_LOW_YEARS, RETURN_PERIOD_SAFE_YEARS
from ui_common import (
    bbox_server_url,
    checked_selection,
    download_link_button,
    page_header,
    selection_footprint,
    selection_size_label,
    shape_label,
)

VIEW_MODE = "Raster-Derivate"

logger = logging.getLogger(__name__)

# UI-only cap (download size + S3 request count), unrelated to
# ifk_and_raster.max_raster_kacheln()'s RAM-driven cap for on-demand
# compute. Applies to the selection's bounding kacheln.
_MAX_KACHELN = 300
# LV95 metres per Kachel side; id_kachel = floor(x / 1 km) * 10000 + floor(y / 1 km).
_KACHEL_SIZE_M = 1000

# Trefferhäufigkeit uses the reciprocal of the fixed Wiederkehrperiode domain,
# so a rate and the matching return period get the same colour.
_HIT_RATE_LOW, _HIT_RATE_HIGH = 1 / RETURN_PERIOD_SAFE_YEARS, 1 / RETURN_PERIOD_LOW_YEARS
# Intensität opens on this band (the shortest ones hold no values anywhere in
# the canton); the first band if the mosaic has no 300-year band.
_INTENSITY_DEFAULT_RETURN_PERIOD_YEARS = 300
# The P80 legend's lower end (its upper end is 1).
_P80_LOW = 1e-3

# Metrik picker entries that also offer other metrics' datasets: the combined
# hit rate's combos are extra Variable options of Trefferhäufigkeit (UI only,
# the lake keeps two metrics). A metric listed as a partner has no entry itself.
_MERGED = {"hit_rate": ("hit_rate", "combined_hit_rate")}

# The derivate lake's metric names (probe_core.derivate.derivate_lake), in the
# picker's order; each is labelled by derivate.metric.<name> in texts.toml.
_METRICS = (
    "return_period",
    "intensity",
    "hit_rate",
    "combined_hit_rate",
    "start_rate",
    "sim_count",
    "affected_mask",
)
# Metrics with a shorter label in the Metrik picker (derivate.metric_short.<name>).
_SHORT_PICKER_LABELS = ("return_period", "intensity", "hit_rate")
# The pipeline's combo names with a label in texts.toml; another keeps its raw name.
_KNOWN_COMBOS = ("depth01_pressure3",)


class _Picks(NamedTuple):
    """The sidebar's picks. metric and partition are None while the entry has
    no data on S3; band is None while the canton mosaic of (metric,
    partition) isn't built yet."""

    entry: str
    metric: str | None = None
    partition: str | None = None
    band: dict | None = None


class _ZipContext(NamedTuple):
    """What both ZIP columns share: the link's cache key (selection ring,
    datasets), the selection the Ausschnitt ZIP crops to, and
    derivate_bbox_server.py, which streams the ZIPs."""

    cache_key: tuple
    selection: dict
    bbox_server: dict


# ── Derivate lake (Data-Lake-Derivate/<metric>/...) ─────────────────────────


@st.cache_data(show_spinner=False, ttl=300)
def _available_metrics():
    """{metric: [partition, ...]} for every raster metric with data on S3, in
    display order ([None] for an unpartitioned metric)."""
    available = {}
    for metric in _METRICS:
        partitions = derivate_lake.list_partitions(metric)
        if partitions:
            available[metric] = partitions
    return available


@st.cache_data(show_spinner=False, ttl=300)
def _kacheln(metric, partition):
    """id_kachel set with a file for (metric, partition) -- one S3 listing,
    reused for the map's coverage layer and the download list."""
    return derivate_lake.list_kacheln(metric, partition)


@st.cache_data(show_spinner=False, ttl=300)
def _kachel_sizes(metric, partition):
    """{S3 key: bytes} of (metric, partition)'s kachel files -- sizes the tiles
    bundle before it is built."""
    return derivate_download.list_object_sizes(
        data.S3_BUCKET_GOLD, derivate_lake.dataset_prefix(metric, partition)
    )


@st.cache_data(show_spinner=False, ttl=300)
def _mosaic_size(metric, partition):
    """Bytes of (metric, partition)'s canton mosaic from the S3 listing, or
    None if it isn't built yet."""
    key = derivate_lake.mosaic_key(metric, partition)
    return derivate_download.list_object_sizes(
        data.S3_BUCKET_GOLD, derivate_lake.mosaic_prefix(metric, partition)
    ).get(key)


@st.cache_data(show_spinner=False, ttl=300)
def _mosaic_bands(metric, partition):
    """Canton mosaic's bands [{index, name, vmin, vmax, param}], sorted by
    their parameter (threshold / return period), or None if no mosaic has
    been built yet for (metric, partition) -- preview and cropped download
    need it, the per-kachel download doesn't."""
    bands = derivate_lake.load_mosaic_bands(metric, partition)
    if bands is None:
        return None
    # A band name this probe-core version can't parse (pipeline on a newer naming scheme) is
    # left out of the picker rather than breaking the whole view.
    parsed = []
    for band in bands:
        try:
            band["param"] = derivate_lake.parse_band(metric, band["name"])
        except ValueError:
            continue
        parsed.append(band)
    stat_order = {"rate": 0, "p80": 1}

    def sort_key(band):
        param = band["param"]
        value = param.get("threshold", param.get("return_period", param.get("min_h", 0)))
        return value, stat_order.get(param.get("stat"), 0)

    return sorted(parsed, key=sort_key)


@st.cache_data(show_spinner=False, ttl=300)
def _coverage_version(metric, partition):
    """The (metric, partition)'s precomputed kacheln as 1 km LV95 squares in
    WGS84, published to coverage_store; returns the version the map fetches
    from pmtiles_server.py's /coverage.geojson?v=<version>. Same box-from-id
    math as data_interface.load_kachel_coverage() for the gold layer, for
    _kacheln's id set. Cached for 5 minutes like _kacheln: building it takes
    seconds for the whole canton."""
    kacheln = sorted(_kacheln(metric, partition))
    squares = []
    for id_kachel in kacheln:
        west = (id_kachel // 10000) * _KACHEL_SIZE_M
        south = (id_kachel % 10000) * _KACHEL_SIZE_M
        squares.append(box(west, south, west + _KACHEL_SIZE_M, south + _KACHEL_SIZE_M))
    coverage = gpd.GeoDataFrame(
        {"region": [f"Kachel {id_kachel}" for id_kachel in kacheln]},
        geometry=squares,
        crs="EPSG:2056",
    )
    return coverage_store.publish(
        f"derivate/{metric}/{partition}", coverage.to_crs("EPSG:4326").to_json()
    )


# ── Picker entries, labels and styles ───────────────────────────────────────


def _picker_metrics() -> list[str]:
    """The Metrik picker's entries, in display order."""
    partners = {metric for group in _MERGED.values() for metric in group if metric not in _MERGED}
    return [metric for metric in _METRICS if metric not in partners]


def _datasets(entry: str, available: dict) -> list[tuple]:
    """[(metric, partition), ...] with data on S3 behind a Metrik picker entry;
    variables in Raster-Karten's order (Fliesstiefe, -geschwindigkeit, Druck)."""
    variable_order = list(VARIABLE_UNITS)

    def position(partition):
        if partition in variable_order:
            return variable_order.index(partition)
        return len(variable_order)

    return [
        (metric, partition)
        for metric in _MERGED.get(entry, (entry,))
        for partition in sorted(available.get(metric, []), key=position)
    ]


def _entry(metric: str) -> str:
    """The Metrik picker entry a metric is offered under."""
    return next((entry for entry, group in _MERGED.items() if metric in group), metric)


def _metric_label(metric: str) -> str:
    return ui_text.t(f"derivate.metric.{metric}")


def _picker_label(metric: str) -> str:
    """The Metrik picker's label: a shorter one where the full one gets cut off."""
    if metric in _SHORT_PICKER_LABELS:
        return ui_text.t(f"derivate.metric_short.{metric}")
    return _metric_label(metric)


def _gold_variable_label(variable: str) -> str:
    """'Fliesstiefe'; a variable this view doesn't know keeps its raw name."""
    if variable in VARIABLE_UNITS:
        return ui_text.t(f"variable.{variable}")
    return variable


def _partition_label(metric, partition):
    """The partition as a condition: 'Fliesstiefe', 'Fliesstiefe ≥ 0.1 m und Druck ≥ 3 kN/m²'."""
    if derivate_lake.PARTITION_KEYS[metric] == "variable":
        return _gold_variable_label(partition)
    if partition in _KNOWN_COMBOS:
        return ui_text.t(f"derivate.combo_label.{partition}")
    return partition


def _variable_label(dataset: tuple) -> str:
    """Variable picker label of a (metric, partition): 'Fliesstiefe', 'Fliesstiefe und Druck'."""
    metric, partition = dataset
    if derivate_lake.PARTITION_KEYS[metric] == "variable":
        return _gold_variable_label(partition)
    if partition in _KNOWN_COMBOS:
        return ui_text.t(f"derivate.combo_variable.{partition}")
    return partition


def _band_is_empty(band):
    """True if no pixel of the mosaic holds a value in this band (canton_bands.json has no
    vmin/vmax). Real case: intensity at a 10-year return period -- nowhere in the canton do
    events come that often (the shortest return period is ~12 years), so the band is all nodata."""
    return band["vmin"] is None and band["vmax"] is None


def _band_option_label(metric, partition, band):
    """Picker label for one band: the threshold / return period / statistic it stands for."""
    label = _band_param_label(metric, partition, band)
    if _band_is_empty(band):
        return ui_text.t("derivate.band_empty_option", label=label)
    return label


def _band_param_label(metric, partition, band):
    param = band["param"]
    if "threshold" in param:
        return ui_text.derivate_band_threshold(param["threshold"], VARIABLE_UNITS[partition])
    if "return_period" in param:
        return ui_text.derivate_band_return_period(param["return_period"])
    if param.get("stat") == "rate":
        return ui_text.t("derivate.band_rate")
    if "min_h" in param:
        return ui_text.derivate_band_min_h(param["min_h"])
    if param.get("stat") == "p80":
        return ui_text.t("derivate.band_p80")
    return band["name"] or "-"


def _legend_condition(metric, partition, band_label):
    """The condition a legend title is about: variable + threshold, the
    combination, or None for a metric whose title names no condition."""
    if metric in ("return_period", "hit_rate"):
        return f"{ui_text.t(f'variable.{partition}')} {band_label}"
    if metric == "combined_hit_rate":
        return _partition_label(metric, partition)
    return None


def _style(metric, partition, band):
    """Legend label/unit + colour style for one band. The same dict feeds
    the legend AND derivate_bbox_server.py's colorization (forwarded as
    query args by the map component), so they can't disagree.

    Wiederkehrperiode: fixed 100..100'000 yr log domain for every threshold
    (per-band domains would make the same colour mean a different return
    period per threshold), reversed viridis (yellow = frequent).
    Trefferhäufigkeit: the reciprocal domain, plain viridis (yellow = many
    events/year), so a pixel gets the same colour under both metrics.
    Intensität keeps a per-band real vmin/vmax: a 100-year and a 1'000'000-
    year intensity live on genuinely different physical scales."""
    param = band["param"]
    band_label = _band_param_label(metric, partition, band)
    condition = _legend_condition(metric, partition, band_label)
    if metric == "return_period":
        return dict(
            label=ui_text.t(
                "legend.title", what=condition, measure=ui_text.t("legend.return_period")
            ),
            unit=ui_text.t("unit.years"),
            scale="log",
            ramp="viridis_r",
            vmin=RETURN_PERIOD_LOW_YEARS,
            vmax=RETURN_PERIOD_SAFE_YEARS,
            note=ui_text.t("legend.return_period_note"),
        )
    if metric == "hit_rate" or (metric == "combined_hit_rate" and param.get("stat") == "rate"):
        return dict(
            label=ui_text.t("legend.title", what=condition, measure=ui_text.t("legend.hit_rate")),
            unit=ui_text.t("unit.per_year"),
            scale="log",
            ramp="viridis",
            vmin=_HIT_RATE_LOW,
            vmax=_HIT_RATE_HIGH,
            note=ui_text.t("legend.hit_rate_note"),
        )
    if metric == "combined_hit_rate":
        return dict(
            label=ui_text.t("legend.title", what=condition, measure=ui_text.t("legend.p80")),
            unit="",
            scale="log",
            ramp="viridis",
            vmin=_P80_LOW,
            vmax=1.0,
            note=ui_text.t("legend.p80_note"),
        )
    if metric == "intensity":
        vmin = band["vmin"] if band["vmin"] is not None else 0.0
        vmax = band["vmax"] if band["vmax"] is not None else 1.0
        return dict(
            label=ui_text.t(
                "legend.intensity",
                variable=ui_text.t(f"variable.{partition}"),
                return_period=band_label,
            ),
            unit=VARIABLE_UNITS[partition],
            scale="linear",
            ramp="viridis",
            vmin=vmin,
            vmax=vmax,
            note="",
        )
    if metric == "start_rate":
        # No fixed physical domain to anchor on (and no data yet when this was written):
        # four decades below the mosaic's real maximum.
        vmax = band["vmax"] if band["vmax"] else 1e-3
        return dict(
            label=ui_text.t(
                "legend.title", what=ui_text.t("legend.start_rate"), measure=band_label
            ),
            unit=ui_text.t("unit.per_year"),
            scale="log",
            ramp="viridis",
            vmin=vmax * 1e-4,
            vmax=vmax,
            note=ui_text.t("legend.start_rate_note"),
        )
    if metric == "sim_count":
        return dict(
            label=_metric_label(metric),
            unit="",
            scale="log",
            ramp="viridis",
            vmin=1.0,
            vmax=max(band["vmax"] or 10.0, 10.0),
            note=ui_text.t("legend.sim_count_note"),
        )
    return dict(
        label=_metric_label(metric),
        unit="",
        scale="mask",
        ramp="viridis",
        vmin=0.0,
        vmax=1.0,
        note="",
    )


# ── Sidebar ─────────────────────────────────────────────────────────────────
# Plain reactive widgets, not st.form -- each pick gates the options of the
# next. Explicit key= on every one, and per-metric/partition keys, so a pick
# survives switching away and back and a conditional widget can't inherit
# another one's state (a past incident with unkeyed selectboxes).


def _download_key(entry: str) -> str:
    return f"_derivate_dl__{entry}"


def _tick_shown_metric():
    """The metric picked for the map is ticked for download, too."""
    st.session_state[_download_key(st.session_state["_derivate_metric"])] = True


def _sidebar(available: dict) -> _Picks:
    """The pickers and the area section."""
    st.sidebar.markdown("---")
    # Every known metric is listed, also one whose producer hasn't written
    # anything yet -- marked, so it's visible what's coming (selectbox options
    # can't be disabled). Picking one shows a note instead of map/downloads.
    entry = st.sidebar.selectbox(
        ui_text.t("derivate.metric_select"),
        _picker_metrics(),
        key=language.translated_options("_derivate_metric"),
        help=ui_text.t("derivate.metric_select_help"),
        on_change=_tick_shown_metric,
        format_func=lambda metric: ui_text.derivate_metric_option(
            _picker_label(metric), bool(_datasets(metric, available))
        ),
    )
    st.sidebar.caption(ui_text.t(f"derivate.metric_help.{entry}"))
    datasets = _datasets(entry, available)
    # Not available yet: the main area says so, the sidebar only marks the option.
    if not datasets:
        return _Picks(entry)
    metric, partition = _variable_picker(entry, datasets)
    band = _band_picker(metric, partition)
    if metric == "combined_hit_rate":
        # Only for the combined option: what rate and P80 mean.
        st.sidebar.caption(ui_text.t("derivate.metric_help.combined_hit_rate"))
    _area_section()
    return _Picks(entry, metric, partition, band)


def _variable_picker(entry: str, datasets: list[tuple]) -> tuple:
    """One Variable picker over the entry's datasets -- for Trefferhäufigkeit
    the variables and the combos of the combined hit rate (_MERGED). An
    unpartitioned metric has one dataset and no picker."""
    metric, partition = datasets[0]
    if partition is None:
        return metric, partition
    return st.sidebar.selectbox(
        ui_text.t("derivate.variable_select"),
        datasets,
        format_func=_variable_label,
        help=ui_text.t("derivate.variable_select_help"),
        key=language.translated_options(f"_derivate_variable__{entry}"),
    )


def _band_title(metric: str, partition: str | None) -> str:
    if metric in ("return_period", "hit_rate"):
        return ui_text.t("area.threshold_label", unit=VARIABLE_UNITS.get(partition, ""))
    if metric == "intensity":
        return ui_text.t("area.return_period_label")
    if metric == "start_rate":
        return ui_text.t("derivate.band_select_min_h")
    return ui_text.t("derivate.band_select")


def _band_help(metric: str) -> str | None:
    """The band picker's help; sim_count and affected_mask have none."""
    if metric in ("return_period", "hit_rate", "intensity"):
        raster_karten = ui_text.t("nav.raster_karten")
        return ui_text.t(f"derivate.band_help.{metric}", raster_karten=raster_karten)
    if metric in ("start_rate", "combined_hit_rate"):
        return ui_text.t(f"derivate.band_help.{metric}")
    return None


def _band_picker(metric: str, partition: str | None) -> dict | None:
    """The mosaic band to preview; None while the canton mosaic isn't built."""
    bands = _mosaic_bands(metric, partition)
    if bands is None:
        st.sidebar.caption(ui_text.t("derivate.preview_pending_sidebar"))
        return None
    if len(bands) == 1:
        return bands[0]
    if metric == "combined_hit_rate":
        # A combo's thresholds are fixed: one option, shown so the picker
        # order matches the single variables'. Its bands (rate, P80) go
        # to the Darstellung picker below.
        st.sidebar.selectbox(
            ui_text.t("derivate.threshold"),
            [partition],
            format_func=lambda combo: _partition_label(metric, combo),
            help=ui_text.t("derivate.combo_threshold_help"),
            key=language.translated_options(f"_derivate_combo_threshold__{partition}"),
        )
    # Only the actually precomputed bands exist to pick -- read from the
    # mosaic, not a free number input like Raster-Karten's.
    by_index = {band["index"]: band for band in bands}
    default_position = next(
        (
            position
            for position, band in enumerate(bands)
            if band["param"].get("return_period") == _INTENSITY_DEFAULT_RETURN_PERIOD_YEARS
        ),
        0,
    )
    index = st.sidebar.selectbox(
        _band_title(metric, partition),
        list(by_index),
        index=default_position,
        format_func=lambda band_index: _band_option_label(metric, partition, by_index[band_index]),
        help=_band_help(metric),
        key=language.translated_options(f"_derivate_band__{metric}__{partition}"),
    )
    return by_index[index]


def _area_section():
    """The drawn area's size, and "Zurücksetzen" to drop it."""
    st.sidebar.markdown(
        f"<div class='pgr-field-label'>{ui_text.t('area.heading')}</div>", unsafe_allow_html=True
    )
    selection = st.session_state.get("_derivate_selection")
    if selection is None:
        st.sidebar.caption(ui_text.t("derivate.area_hint"))
        return
    xmin, ymin, xmax, ymax = ifk_and_raster.selection_bounds(selection)
    n_kacheln = len(ifk_and_raster.kacheln_for_bbox(xmin, ymin, xmax, ymax))
    st.sidebar.caption(
        ui_text.t(
            "area.selection_size",
            shape=shape_label(selection),
            size=selection_size_label(*selection_footprint(selection)),
            n_kacheln=n_kacheln,
        )
    )
    if st.sidebar.button(ui_text.t("area.reset"), key="derivate_reset_btn", width="stretch"):
        for key in ("_derivate_selection", "_derivate_selection_component_nonce"):
            st.session_state.pop(key, None)
        st.rerun()


# ── Map ─────────────────────────────────────────────────────────────────────


def _band_notes(picks: _Picks):
    """Why the map may show no values: an empty band, or no mosaic yet."""
    if picks.band is None:
        st.info(ui_text.t("derivate.preview_pending"))
    elif _band_is_empty(picks.band):
        if picks.metric == "intensity":
            st.info(
                ui_text.t(
                    "derivate.intensity_band_empty",
                    return_period=_band_param_label(picks.metric, picks.partition, picks.band),
                )
            )
        else:
            st.info(ui_text.t("derivate.band_empty"))


def _map(picks: _Picks, servers: dict, bbox_server: dict, default_center: tuple[float, float]):
    """Canton-wide live preview: derivate_bbox_server.py crops+colorizes the
    current viewport straight from the (metric, partition)'s canton mosaic
    COG on every pan/zoom, in native LV95 -- see that module's docstring for
    the approaches tried before. Without a band (no mosaic yet) the map shows
    only the coverage. Returns the component's value."""
    band = picks.band
    style = _style(picks.metric, picks.partition, band) if band is not None else {}
    return raster_bbox_map(
        center_lat=default_center[0],
        center_lon=default_center[1],
        coverage_version=_coverage_version(picks.metric, picks.partition),
        selected_selection=st.session_state.get("_derivate_selection"),
        derivate_bbox_metric=picks.metric if band is not None else None,
        derivate_bbox_partition=picks.partition,
        derivate_bbox_band=band["index"] if band is not None else None,
        derivate_bbox_label=style.get("label"),
        derivate_bbox_unit=style.get("unit"),
        derivate_bbox_scale=style.get("scale"),
        derivate_bbox_ramp=style.get("ramp"),
        derivate_bbox_vmin=style.get("vmin"),
        derivate_bbox_vmax=style.get("vmax"),
        derivate_bbox_note=style.get("note"),
        derivate_bbox_server_port=bbox_server["port"],
        derivate_bbox_path_prefix=bbox_server["path_prefix"],
        pmtiles_port=servers["pmtiles_port"],
        pmtiles_path_prefix=servers["pmtiles_path_prefix"],
    )


def _handle_selection(map_value: dict | None):
    """A new map selection ({'selection': ...|None, 'nonce'}), as in
    Raster-Karten: the nonce tells a new interaction apart, since a component
    that was never clicked also returns None, like "Löschen"."""
    if map_value is None or map_value["nonce"] == st.session_state.get(
        "_derivate_selection_component_nonce"
    ):
        return
    st.session_state["_derivate_selection_component_nonce"] = map_value["nonce"]
    try:
        new_selection = checked_selection(map_value["selection"])
    except ValueError as error:
        logger.warning("Map selection refused: %s", error)
        return
    if new_selection != st.session_state.get("_derivate_selection"):
        st.session_state["_derivate_selection"] = new_selection
        st.rerun()


# ── Download ────────────────────────────────────────────────────────────────


def _zip_column(kind: str, items: list, estimate: int, context: _ZipContext):
    """One ZIP: its title and size, then "ZIP erstellen", which registers it
    with the derivate sidecar, or the link it is streamed from. The
    link stays per (selection, datasets) until its id expires."""
    # Kacheln: exact (uncompressed ZIP of the S3 files); Ausschnitt: an upper
    # bound from the same kacheln (estimate_zip_bytes).
    size = ui_text.derivate_zip_size(kind, estimate)
    st.markdown(f"**{ui_text.t(f'derivate.zip_title.{kind}')}**")
    help_text = ui_text.t(f"derivate.zip_help.{kind}")
    st.caption(ui_text.t("derivate.zip_files", help_text=help_text, n_files=len(items), size=size))
    links = st.session_state.setdefault("_derivate_download_links", {})
    link = links.get(kind)
    if link is not None and (
        link["key"] != context.cache_key or raster_jobs.get_download(link["id"]) is None
    ):
        del links[kind]
        link = None
    if not items:
        st.caption(ui_text.t("derivate.zip_no_mosaic"))
        return
    build_label = ui_text.t("derivate.zip_build")
    if link is None and st.button(build_label, key=f"derivate_build_{kind}_btn"):
        link = links[kind] = {
            "key": context.cache_key,
            "id": raster_jobs.register_download(
                kind, items, context.selection if kind == "crop" else None
            ),
        }
    if link is not None:
        download_link_button(
            ui_text.t("derivate.zip_download", size=size),
            bbox_server_url(context.bbox_server, f"/download/{link['id']}.zip"),
            key=f"derivate_zip_{kind}",
        )


def _selection_files(selection_kacheln: list, datasets: list) -> tuple[list, list]:
    """(kachel files for the Kacheln ZIP as (name in the ZIP, S3 key), the
    datasets the Ausschnitt ZIP can crop from a canton mosaic)."""
    kachel_files = [
        (
            f"{ui_text.derivate_file_stem(metric, partition)}/kachel_{id_kachel}.tif",
            derivate_lake.kachel_key(metric, id_kachel, partition),
        )
        for metric, partition in datasets
        for id_kachel in sorted(set(selection_kacheln) & _kacheln(metric, partition))
    ]
    crop_datasets = [
        (metric, partition)
        for metric, partition in datasets
        if _mosaic_bands(metric, partition) is not None
    ]
    return kachel_files, crop_datasets


def _dataset_label(metric: str, partition: str | None) -> str:
    return _metric_label(_entry(metric)) + (
        f" - {_partition_label(metric, partition)}" if partition else ""
    )


def _kanton_links(datasets: list, bbox_server: dict):
    """The whole canton: one link per dataset's canton mosaic, passed through
    from S3 by derivate_bbox_server.py's /canton route (the browser can't reach
    every stage's object storage). A mosaic is up to ~9 GB (48 GB for all of
    them): too big for a ZIP, which could not resume; a single file
    resumes with Range requests."""
    st.markdown(f"**{ui_text.t('derivate.kanton_title')}**")
    st.caption(ui_text.t("derivate.kanton_help"))
    mosaics = [
        (metric, partition, size)
        for metric, partition in datasets
        if (size := _mosaic_size(metric, partition)) is not None
    ]
    if not mosaics:
        st.caption(ui_text.t("derivate.zip_no_mosaic"))
    for metric, partition, size in mosaics:
        query = f"?{urlencode({'partition': partition})}" if partition else ""
        download_link_button(
            ui_text.derivate_kanton_download(_dataset_label(metric, partition), size),
            bbox_server_url(bbox_server, f"/canton/{metric}.tif{query}"),
            key=f"derivate_kanton_{metric}_{partition}",
            width="stretch",
        )
        # Which band holds which threshold / return period: the file's own
        # band names are the lake's column names.
        bands = _mosaic_bands(metric, partition) or []
        if len(bands) > 1:
            st.caption(
                ui_text.derivate_kanton_bands(
                    [(band["index"], _band_param_label(metric, partition, band)) for band in bands]
                )
            )


# A fragment: the metric checkboxes and "ZIP erstellen" rerun only this
# section, not the whole page with its map.
@st.fragment
def _download_section(selection: dict | None, available: dict, entry: str, bbox_server: dict):
    """The download section below the map; `entry`, the metric on the map,
    starts ticked and is ticked again whenever it is picked
    (_tick_shown_metric). The whole canton is offered with or without an area."""
    st.markdown(ui_text.t("derivate.download_heading"))
    columns = st.columns(3)
    entries = [each for each in _picker_metrics() if _datasets(each, available)]
    st.session_state.setdefault(_download_key(entry), True)
    picked = [
        each
        for position, each in enumerate(entries)
        if columns[position % 3].checkbox(_metric_label(each), key=_download_key(each))
    ]
    datasets = [dataset for each in picked for dataset in _datasets(each, available)]
    if not datasets:
        st.caption(ui_text.t("derivate.no_metric"))
        return
    # Keyed for app.css: the thin line between the two columns.
    with st.container(key="derivate_downloads"):
        left, right = st.columns(2)
    with left:
        if selection is None:
            _area_title()
            st.info(ui_text.t("derivate.select_area"))
        else:
            _area_zips(selection, datasets, bbox_server)
    with right:
        _kanton_links(datasets, bbox_server)


def _area_title():
    """The left column's title where it has no ZIP to offer, so the column
    reads as the Ausschnitt side next to "Ganzer Kanton" all the same."""
    st.markdown(f"**{ui_text.t('derivate.zip_title.crop')}**")


def _area_zips(selection: dict, datasets: list, bbox_server: dict):
    """The Ausschnitt and Kacheln ZIPs of the drawn area, one above the other."""
    selection_kacheln = ifk_and_raster.kacheln_for_bbox(*ifk_and_raster.selection_bounds(selection))
    if len(selection_kacheln) > _MAX_KACHELN:
        _area_title()
        st.warning(
            ui_text.t(
                "derivate.too_many_kacheln",
                n_kacheln=len(selection_kacheln),
                max_kacheln=_MAX_KACHELN,
            )
        )
        return
    kachel_files, crop_datasets = _selection_files(selection_kacheln, datasets)
    if not kachel_files:
        _area_title()
        st.info(ui_text.t("derivate.no_kacheln"))
        return
    # Sized from the S3 listing of the kachel files each ZIP covers, so the
    # user sees the size before requesting it.
    sizes = {
        key: size
        for metric, partition in datasets
        for key, size in _kachel_sizes(metric, partition).items()
    }
    crop_estimate = derivate_download.estimate_zip_bytes(
        [
            derivate_lake.kachel_key(metric, id_kachel, partition)
            for metric, partition in crop_datasets
            for id_kachel in sorted(set(selection_kacheln) & _kacheln(metric, partition))
        ],
        sizes,
    )
    kachel_estimate = derivate_download.estimate_zip_bytes([key for _, key in kachel_files], sizes)
    cache_key = (json.dumps(selection["ring"]), tuple(datasets))
    context = _ZipContext(cache_key, selection, bbox_server)
    _zip_column("crop", crop_datasets, crop_estimate, context)
    _zip_column("kacheln", kachel_files, kachel_estimate, context)
    missing_mosaic = [dataset for dataset in datasets if dataset not in crop_datasets]
    if missing_mosaic and crop_datasets:
        st.caption(
            ui_text.derivate_missing_mosaic(
                [_dataset_label(metric, partition) for metric, partition in missing_mosaic]
            )
        )


def render(servers: dict, bbox_server: dict, default_center: tuple[float, float]):
    """The view: its sidebar, the map and the download section.

    Args:
        servers: pmtiles_port and pmtiles_path_prefix of the tile sidecar.
        bbox_server: port and path_prefix of derivate_bbox_server.py, which
            draws the preview and streams the ZIPs.
        default_center: (lat, lon) the map starts at.
    """
    available = _available_metrics()
    picks = _sidebar(available)
    page_header(ui_text.t("nav.raster_derivate"), ui_text.t("header.derivate_hint"))
    if picks.metric is None:
        st.info(ui_text.t("derivate.metric_no_data", metric=_metric_label(picks.entry)))
        return
    selection = st.session_state.get("_derivate_selection")
    _band_notes(picks)
    _handle_selection(_map(picks, servers, bbox_server, default_center))
    with downloads_section():
        _download_section(selection, available, picks.entry, bbox_server)
    downloads_cue()
