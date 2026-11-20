"""Gebäudeschatten view: which buildings' flows reach where, and why a pixel
counts as affected or not.

Two ways in, both on one map, one at a time (the last click wins, the other
selection is dropped):
  - a building (map click or ID): its own pixels (own_building_mask = 1), its
    neighbour ring (= 2), its footprint, and every pixel its simulations reach,
    coloured by Fliesstiefe where the pixel counts under the chosen variant and
    grey where the variant excludes it (the reason is in the hover text);
  - a pixel (click next to a building, or Shift-click): every building whose
    simulations reach it, whether each counts there, and those buildings' own
    pixels, rings and footprints as outlines.

Data and rules come from probe_core.gebaeudeschatten, the same module the
pipeline builds the affected-mask rasters with, so the explanation here and
the mask on the map can't disagree. Everything is read from the gold bucket
(published there by the pipeline's data_lake/publish_gebaeudeschatten_to_app_bucket.py);
the view is only offered when that data is present (is_available). Downloads:
the canton mask of the current settings (derivate_bbox_server's /canton), and the selected
building's or pixel's data as CSV (gebaeudeschatten_export).
"""

import logging
import time

import numpy as np
import pandas as pd
import shapely
import streamlit as st
from pyproj import Transformer
from shapely.geometry import mapping
from shapely.ops import transform as shapely_transform

import gebaeudeschatten_export
import language
from derivate_bbox_server import GEBAEUDESCHATTEN_METRIC
from gebaeudeschatten_map_component import gebaeudeschatten_map
import ui_text
from probe_core import gebaeudeschatten as gs
from downloads_cue_component import downloads_cue, downloads_section
from ui_common import bbox_server_url, download_link_button, page_header

VIEW_MODE = "Gebäudeschatten"

logger = logging.getLogger(__name__)

# 1 cm filters numerical traces at the flow's edge; 10 cm is where low intensity typically starts.
DEFAULT_MIN_DEPTH = 1
# Tightest reach first; 50 m is the default.
REACH_OPTIONS = sorted(gs.REACHES_M)
DEFAULT_REACH = 50
# Which reason explains a pixel when several of its rows are excluded:
# the structural ones (same for every simulation) before the depth one.
_REASON_ORDER = [
    gs.REASON_OWN_BUILDING,
    gs.REASON_OWN_NEIGHBOR,
    gs.REASON_FALLBACK_NEIGHBOR,
    gs.REASON_BELOW_MIN_DEPTH,
]
_SIMULATION_COLUMNS = ["A", "h", "mu", "xsi", "tau0"]

_TO_WGS84 = Transformer.from_crs("EPSG:2056", "EPSG:4326", always_xy=True)
_CANTON_BOUNDS = [[46.30, 6.85], [47.35, 8.46]]
# Pixel colours: own building red, neighbour ring light blue, shadow dark blue,
# excluded shadow grey. The canton mask under them is lilac (derivate_bbox_server's
# mask_color "purple"), so the selection's shadow takes another hue, not a darker lilac.
OWN_COLOR = "#e5261f"
RING_COLOR = "#5bc4ef"
SHADOW_COLOR = "#08519c"
EXCLUDED_COLOR = "#bdbdbd"
_HALF_PIXEL_M = gs.RESOLUTION_M / 2


def _cells_legend() -> list[dict]:
    return [
        {"color": OWN_COLOR, "label": ui_text.t("gs.own_pixel")},
        {"color": RING_COLOR, "label": ui_text.t("gs.ring_pixel")},
        {"color": SHADOW_COLOR, "label": ui_text.t("gs.legend_shadow")},
        {"color": EXCLUDED_COLOR, "label": ui_text.t("gs.legend_excluded")},
    ]


def _variant_label(variant: str) -> str:
    return ui_text.t(f"gs.variant.{variant}")


def _reach_label(reach_m: int) -> str:
    return ui_text.t(f"gs.reach.{reach_m}")


def _mask_kinds() -> dict[int, str]:
    """own_building_mask value -> the pixel's kind, as the hover texts name it."""
    return {1: ui_text.t("gs.own_pixel"), 2: ui_text.t("gs.ring_pixel")}


# ── data (immutable once published, so cached without TTL) ─────────────────


@st.cache_data(ttl=600, show_spinner=False)
def is_available() -> bool:
    try:
        return gs.is_available()
    except Exception:  # a failed S3 check must not break the app's navigation
        logger.warning(
            "Gebäudeschatten availability check failed; the view is hidden", exc_info=True
        )
        return False


@st.cache_data(max_entries=16, show_spinner=False)
def _building_rows(id_start: int, reach_m: int) -> pd.DataFrame:
    return gs.building_rows(id_start, reach_m)


@st.cache_data(max_entries=32, show_spinner=False)
def _pixel_rows(e: float, n: float, reach_m: int) -> pd.DataFrame:
    return gs.pixel_rows(e, n, reach_m)


@st.cache_data(max_entries=32, show_spinner=False)
def _footprints(id_starts: tuple, reach_m: int, near: tuple) -> pd.DataFrame:
    return gs.building_footprint_pixels(list(id_starts), reach_m, near)


@st.cache_data(max_entries=64, show_spinner=False)
def _geometries(id_starts: tuple) -> pd.DataFrame:
    return gs.building_geometries(list(id_starts))


# ── geometry helpers ─────────────────────────────────────────────────────────


def _to_wgs(geometry):
    return shapely_transform(_TO_WGS84.transform, geometry)


def _pixel_union(xs, ys):
    """Outline of a set of 5 m pixels (their squares merged), in WGS84."""
    if len(xs) == 0:
        return None
    boxes = shapely.box(
        np.asarray(xs) - _HALF_PIXEL_M,
        np.asarray(ys) - _HALF_PIXEL_M,
        np.asarray(xs) + _HALF_PIXEL_M,
        np.asarray(ys) + _HALF_PIXEL_M,
    )
    return _to_wgs(shapely.union_all(boxes))


def _feature_collection(geometries):
    features = [
        {"type": "Feature", "geometry": mapping(geometry), "properties": {}}
        for geometry in geometries
        if geometry is not None and not geometry.is_empty
    ]
    return {"type": "FeatureCollection", "features": features} if features else None


def _footprint_geojson(id_starts):
    footprints = _geometries(tuple(sorted(int(id_start) for id_start in id_starts)))
    return _feature_collection(
        [_to_wgs(shapely.from_wkb(bytes(wkb))) for wkb in footprints["geometry_wkb"]]
    )


def _wgs_bounds(xmin, ymin, xmax, ymax):
    lon0, lat0 = _TO_WGS84.transform(xmin, ymin)
    lon1, lat1 = _TO_WGS84.transform(xmax, ymax)
    return [[lat0, lon0], [lat1, lon1]]


def _rows_wgs_bounds(rows):
    """The WGS84 bounds of a frame's x/y pixel centres, for the map to focus on."""
    return _wgs_bounds(rows.x.min(), rows.y.min(), rows.x.max(), rows.y.max())


def _sim_label(row, lang: str | None = None) -> str:
    """lang: as for ui_text.t; EXPORT_LANGUAGE for the GeoTIFF tag."""
    thickness = ui_text.depth_m(row.h, lang=lang)
    mu = ui_text.in_locale(f"{float(row.mu):g}", lang=lang)
    return f"A={int(row.A)} m², h={thickness}, μ={mu}, ξ={int(row.xsi)}, τ₀={int(row.tau0)}"


# ── aggregation: rows (one per simulation and pixel) -> one per pixel ────────


def _reason_label(reason: str, min_depth: int, lang: str | None = None) -> str:
    """lang: as for ui_text.t; EXPORT_LANGUAGE in a downloaded file."""
    if reason == gs.REASON_BELOW_MIN_DEPTH:
        depth = ui_text.depth_m(min_depth, lang=lang)
        return ui_text.t("gs.reason.below_min_depth", lang=lang, min_depth=depth)
    return ui_text.t(f"gs.reason.{reason}", lang=lang)


def _pixel_status(rows: pd.DataFrame, variant: str, min_depth: int) -> pd.DataFrame:
    """Per pixel: max Fliesstiefe, number of simulations, own_building_mask,
    whether any row counts under `variant` at `min_depth` cm, and the reason if none does."""
    reason = rows[gs.reason_column(variant, min_depth)]
    rank = reason.map({ordered: position for position, ordered in enumerate(_REASON_ORDER)})
    ranked_rows = rows.assign(_counts=reason.isna(), _rank=rank)
    per_pixel = (
        ranked_rows.groupby(["x", "y"], sort=False)
        .agg(
            depth=("Fliesstiefe", "max"),
            n_sims=("Fliesstiefe", "size"),
            mask=("own_building_mask", "max"),
            counts=("_counts", "any"),
            rank=("_rank", "min"),
        )
        .reset_index()
    )
    per_pixel["reason"] = per_pixel["rank"].map(
        lambda rank: None if pd.isna(rank) else _REASON_ORDER[int(rank)]
    )
    per_pixel.loc[per_pixel["counts"], "reason"] = None
    return per_pixel


def _building_cells(pixel_status: pd.DataFrame, min_depth: int) -> pd.DataFrame:
    """The selected building's pixels as cells: colour by mask, else by
    whether the pixel counts; the hover text says why."""
    mask = pixel_status["mask"]
    shadow_color = np.where(pixel_status["counts"], SHADOW_COLOR, EXCLUDED_COLOR)
    color = np.where(mask == 1, OWN_COLOR, np.where(mask == 2, RING_COLOR, shadow_color))
    counts_text = ui_text.t("gs.counts")
    status = [
        counts_text if counts else ui_text.t("gs.excluded", reason=_reason_label(reason, min_depth))
        for counts, reason in zip(pixel_status["counts"], pixel_status["reason"])
    ]
    kind = mask.map(_mask_kinds()).fillna("")
    tooltip = [
        ui_text.gs_cell_tooltip(pixel_kind, int(depth), int(n_sims), status_text)
        for pixel_kind, depth, n_sims, status_text in zip(
            kind, pixel_status["depth"], pixel_status["n_sims"], status
        )
    ]
    return pd.DataFrame(
        {"x": pixel_status["x"], "y": pixel_status["y"], "color": color, "tooltip": tooltip}
    )


def _shadowing_cells(pixel_buildings, pixel_footprints, selected_building) -> pd.DataFrame:
    """Own and ring pixels of the buildings reaching the selected pixel (the
    selected building's own cells already come from _building_cells)."""
    footprints = pixel_footprints[pixel_footprints.id_start != selected_building]
    counts_by_building = dict(zip(pixel_buildings.id_start, pixel_buildings.counts))
    kinds = _mask_kinds()
    return pd.DataFrame(
        {
            "x": footprints["x"],
            "y": footprints["y"],
            "color": np.where(footprints["own_building_mask"] == 1, OWN_COLOR, RING_COLOR),
            "tooltip": [
                ui_text.gs_shadowing_tooltip(
                    id_start, kinds[1] if mask == 1 else kinds[2], counts_by_building[id_start]
                )
                for id_start, mask in zip(footprints["id_start"], footprints["own_building_mask"])
            ],
        }
    )


def _cells_geojson(cells: pd.DataFrame):
    """Square 5 m cells with fillColor and tooltip, for the map's cells layer."""
    if cells.empty:
        return None
    xs, ys = cells["x"].to_numpy(dtype=float), cells["y"].to_numpy(dtype=float)
    # All corners in one transform call: SW, SE, NE, NW, SW per pixel.
    west, east = xs - _HALF_PIXEL_M, xs + _HALF_PIXEL_M
    south, north = ys - _HALF_PIXEL_M, ys + _HALF_PIXEL_M
    corner_xs = np.stack([west, east, east, west, west], axis=1)
    corner_ys = np.stack([south, south, north, north, south], axis=1)
    lon, lat = _TO_WGS84.transform(corner_xs.ravel(), corner_ys.ravel())
    rings = np.stack(
        [np.asarray(lon).reshape(corner_xs.shape), np.asarray(lat).reshape(corner_ys.shape)], axis=2
    ).tolist()
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {
                "fillColor": color,
                "fillOpacity": 0.5 if color == EXCLUDED_COLOR else 0.85,
                "tooltip": tooltip,
            },
        }
        for ring, color, tooltip in zip(rings, cells["color"], cells["tooltip"])
    ]
    return {"type": "FeatureCollection", "features": features}


# ── state ────────────────────────────────────────────────────────────────────


def _init_state():
    defaults = {
        "gs_reach": DEFAULT_REACH,
        "gs_variant": "shadowing_building_surrounding",
        "gs_min_depth": DEFAULT_MIN_DEPTH,
        "gs_building": None,
        "gs_pixel": None,
        "gs_click_nonce": None,
        "gs_focus": None,
        "gs_table_pick": None,
    }
    for key, default in defaults.items():
        st.session_state.setdefault(key, default)


def _select_building(id_start, focus_bounds=None):
    """A building replaces whatever was selected, a pixel included."""
    st.session_state.gs_building = int(id_start)
    st.session_state.gs_pixel = None
    if focus_bounds is not None:
        st.session_state.gs_focus = {"bounds": focus_bounds, "nonce": time.time()}


def _select_pixel(e, n):
    """A pixel replaces whatever was selected, a building included."""
    st.session_state.gs_pixel = (float(e), float(n))
    st.session_state.gs_building = None


# ── render ───────────────────────────────────────────────────────────────────


def render_sidebar():
    _init_state()
    st.sidebar.markdown("---")
    st.sidebar.radio(
        ui_text.t("gs.reach_select"),
        REACH_OPTIONS,
        key=language.translated_options("gs_reach"),
        format_func=_reach_label,
        help=ui_text.t("gs.reach_select_help"),
    )
    st.sidebar.radio(
        ui_text.t("gs.variant_select"),
        gs.VARIANTS,
        key=language.translated_options("gs_variant"),
        format_func=_variant_label,
        help=ui_text.t("gs.variant_select_help"),
    )
    st.sidebar.radio(
        ui_text.t("gs.min_depth_select"),
        gs.MIN_DEPTHS_CM,
        key=language.translated_options("gs_min_depth"),
        format_func=ui_text.gs_min_depth_option,
        help=ui_text.t("gs.min_depth_select_help"),
    )
    st.sidebar.caption(
        ui_text.gs_variant_help(st.session_state.gs_variant, st.session_state.gs_min_depth)
    )
    with st.sidebar.form("gs_building_form", border=False):
        typed = st.number_input(
            ui_text.t("gs.building_input"),
            min_value=1,
            step=1,
            value=None,
            placeholder=ui_text.t("gs.building_placeholder"),
            format="%d",
        )
        if st.form_submit_button(ui_text.t("gs.building_submit"), width="stretch") and typed:
            rows = _building_rows(int(typed), st.session_state.gs_reach)
            if rows.empty:
                st.error(ui_text.t("gs.building_no_pixels", id_start=int(typed)))
            else:
                _select_building(typed, _rows_wgs_bounds(rows))
    if st.session_state.gs_building is not None or st.session_state.gs_pixel is not None:
        if st.sidebar.button(ui_text.t("area.reset"), key="gs_reset_btn", width="stretch"):
            st.session_state.gs_building = None
            st.session_state.gs_pixel = None
            st.rerun()


def _mask_link(bbox_server):
    """The canton mask the map shows, as a GeoTIFF passed through from S3 by
    derivate_bbox_server's /canton route."""
    partition = (
        f"{st.session_state.gs_variant}_{st.session_state.gs_reach}_{st.session_state.gs_min_depth}"
    )
    with st.sidebar:
        download_link_button(
            ui_text.t("gs.mask_download"),
            bbox_server_url(
                bbox_server, f"/canton/{GEBAEUDESCHATTEN_METRIC}.tif?partition={partition}"
            ),
            key="gs_mask",
            help=ui_text.t("gs.mask_download_help"),
            width="stretch",
        )


def _load_building(reach, variant, min_depth, message):
    """(rows, per-pixel status) of the selected building under the chosen
    simulation, or (None, None). Adds the simulation picker to the sidebar."""
    if st.session_state.gs_building is None:
        return None, None
    rows = _building_rows(st.session_state.gs_building, reach)
    if rows.empty:
        message.info(
            ui_text.t(
                "gs.building_no_reach",
                id_start=st.session_state.gs_building,
                reach_label=_reach_label(reach),
            )
        )
        return None, None
    # The options are the German labels, the GeoTIFF's "Simulation" tag, and
    # None for "alle (Maximum)", so the choice stays when the language changes.
    simulations = rows[_SIMULATION_COLUMNS].itertuples()
    labels = pd.Series(
        [_sim_label(simulation, lang=ui_text.EXPORT_LANGUAGE) for simulation in simulations],
        index=rows.index,
    )
    sim_names = {
        _sim_label(simulation, lang=ui_text.EXPORT_LANGUAGE): _sim_label(simulation)
        for simulation in rows[_SIMULATION_COLUMNS].drop_duplicates().itertuples()
    }
    sim = st.sidebar.selectbox(
        ui_text.t("gs.simulation"),
        [None] + sorted(labels.unique()),
        key=language.translated_options(f"gs_sim_{st.session_state.gs_building}"),
        format_func=lambda label: ui_text.t("gs.all_sims") if label is None else sim_names[label],
        help=ui_text.t("gs.simulation_help"),
    )
    shown = rows if sim is None else rows[labels == sim]
    return rows, _pixel_status(shown, variant, min_depth)


def _load_pixel(reach, variant, min_depth):
    """(per-building summary at the selected pixel, those buildings' own and
    ring pixels), or (None, None) if no pixel is selected or none reaches it."""
    if st.session_state.gs_pixel is None:
        return None, None
    e, n = st.session_state.gs_pixel
    rows = _pixel_rows(e, n, reach)
    if rows.empty:
        return None, None
    per_building = []
    for id_start, building_rows in rows.groupby("id_start"):
        status = _pixel_status(building_rows, variant, min_depth).iloc[0]
        per_building.append(
            {
                "id_start": id_start,
                "depth": int(building_rows.Fliesstiefe.max()),
                "n_sims": len(building_rows),
                "counts": bool(status.counts),
                "reason": None if status.counts else status.reason,
            }
        )
    summary = pd.DataFrame(per_building)
    # A reaching building's footprint lies within its reach plus its own extent.
    search_m = reach + gs.MAX_BUILDING_EXTENT_M
    near = (e - search_m, n - search_m, e + search_m, n + search_m)
    footprints = _footprints(tuple(summary.id_start.tolist()), reach, near)
    return summary, footprints


def _overlay(id, label, geojson, **style):
    """One outline layer for the map; style: color, width, and optionally dash, fill."""
    return dict(id=id, label=label, geojson=geojson, dash=None, fill=None, visible=True) | style


def _building_overlays():
    return [
        _overlay(
            "b_foot",
            ui_text.t("gs.layer_building"),
            _footprint_geojson([st.session_state.gs_building]),
            color="#263238",
            width=2,
            fill="#37474f",
        )
    ]


def _pixel_overlays(pixel_buildings):
    overlays = []
    if pixel_buildings is not None:
        counting = pixel_buildings.loc[pixel_buildings.counts, "id_start"]
        others = pixel_buildings.loc[~pixel_buildings.counts, "id_start"]
        overlays += [
            _overlay(
                "p_foot_yes",
                ui_text.t("gs.layer_shadowing"),
                _footprint_geojson(counting) if len(counting) else None,
                color="#111111",
                width=2,
            ),
            _overlay(
                "p_foot_no",
                ui_text.t("gs.layer_reaching"),
                _footprint_geojson(others) if len(others) else None,
                color="#757575",
                width=2,
                dash=[2, 1],
            ),
        ]
    if st.session_state.gs_pixel is not None:
        e, n = st.session_state.gs_pixel
        overlays.append(
            _overlay(
                "p_pixel",
                ui_text.t("gs.layer_pixel"),
                _feature_collection([_pixel_union([e], [n])]),
                color="#e377c2",
                width=3.5,
            )
        )
    return overlays


def _handle_click(click):
    """Applies a new map click (the component repeats its last value on every
    rerun, so only a new nonce counts)."""
    if not click or click.get("nonce") == st.session_state.gs_click_nonce:
        return
    st.session_state.gs_click_nonce = click["nonce"]
    if click["type"] == "building":
        _select_building(click["id_start"])
    else:
        _select_pixel(click["e"], click["n"])
    st.rerun()


def render(servers: dict, bbox_server: dict):
    """The view's main area. servers: {'pmtiles_port', 'pmtiles_path_prefix'};
    bbox_server: {'port', 'path_prefix'} of derivate_bbox_server."""
    _init_state()
    # Always shown, selection or not: an element that comes and goes above
    # the map would remount it.
    page_header(ui_text.t("nav.gebaeudeschatten"), ui_text.t("header.gs_hint"), _chips())
    _mask_link(bbox_server)
    reach, variant, min_depth = (
        st.session_state.gs_reach,
        st.session_state.gs_variant,
        st.session_state.gs_min_depth,
    )
    message = st.empty()  # unconditional, so a message never remounts the map below it
    building_rows, building_pixels = _load_building(reach, variant, min_depth, message)
    pixel_buildings, pixel_footprints = _load_pixel(reach, variant, min_depth)

    overlays = _building_overlays() if building_rows is not None else []
    overlays += _pixel_overlays(pixel_buildings)
    cell_parts = []
    if building_pixels is not None:
        cell_parts.append(_building_cells(building_pixels, min_depth))
    if pixel_buildings is not None:
        cell_parts.append(
            _shadowing_cells(pixel_buildings, pixel_footprints, st.session_state.gs_building)
        )
    cells = (
        pd.concat(cell_parts)
        if cell_parts
        else pd.DataFrame(columns=["x", "y", "color", "tooltip"])
    )
    layers = dict(
        buildings_pmtiles=gs.BUILDINGS_PMTILES_KEY,
        buildings_layer=gs.BUILDINGS_PMTILES_LAYER,
        mask=dict(
            metric=GEBAEUDESCHATTEN_METRIC,
            partition=f"{variant}_{reach}_{min_depth}",
            label=ui_text.gs_mask_label(_variant_label(variant), _reach_label(reach), min_depth),
            server_port=bbox_server["port"],
            path_prefix=bbox_server["path_prefix"],
        ),
        cells_geojson=_cells_geojson(cells) if len(cells) else None,
        # The language too: the tooltips are in it.
        cells_version=f"{st.session_state.gs_building}|{st.session_state.gs_pixel}|{reach}|{variant}|{min_depth}|"
        f"{st.session_state.get(f'gs_sim_{st.session_state.gs_building}')}|{ui_text.language()}",
        cells_label=ui_text.t("gs.layer_cells"),
        cells_legend=_cells_legend(),
        overlays=overlays,
    )
    _handle_click(
        gebaeudeschatten_map(_CANTON_BOUNDS, layers, servers, focus=st.session_state.gs_focus)
    )
    with downloads_section():
        _render_details(building_rows, building_pixels, pixel_buildings, min_depth)
    downloads_cue()


def _chips() -> list[str]:
    """The header chip of the selected building or pixel (never both)."""
    if st.session_state.gs_building is not None:
        return [ui_text.chip_building(st.session_state.gs_building)]
    if st.session_state.gs_pixel is not None:
        return [ui_text.chip_pixel(*st.session_state.gs_pixel)]
    return []


def _render_details(building_rows, building_pixels, pixel_buildings, min_depth):
    """The selection's details below the map: the building's or the pixel's
    (never both, see _select_building/_select_pixel)."""
    if building_pixels is not None:
        _building_details(building_rows, building_pixels, min_depth)
    elif st.session_state.gs_pixel is not None:
        _pixel_details(pixel_buildings, min_depth)
    with st.expander(ui_text.t("gs.variants_expander")):
        st.markdown(
            "\n".join(
                f"- **{_variant_label(each_variant)}**: "
                f"{ui_text.gs_variant_help(each_variant, min_depth)}"
                for each_variant in gs.VARIANTS
            )
        )
        st.markdown(ui_text.t("gs.variants_rules"))


def _settings():
    return st.session_state.gs_reach, st.session_state.gs_variant, st.session_state.gs_min_depth


def _building_details(building_rows, building_pixels, min_depth):
    id_start = st.session_state.gs_building
    st.subheader(ui_text.t("gs.building_heading", id_start=id_start))
    simulations = building_rows.drop_duplicates(_SIMULATION_COLUMNS)
    all_pixels = building_rows.drop_duplicates(["x", "y"])
    sims_column, own_column, ring_column = st.columns(3)
    sims_column.metric(ui_text.t("gs.metric_sims"), len(simulations))
    own_column.metric(ui_text.t("gs.metric_own"), int((all_pixels.own_building_mask == 1).sum()))
    ring_column.metric(ui_text.t("gs.metric_ring"), int((all_pixels.own_building_mask == 2).sum()))
    summary = []
    for each_variant in gs.VARIANTS:
        status = _pixel_status(building_rows, each_variant, min_depth)
        summary.append(
            {
                ui_text.t("gs.col_variant"): _variant_label(each_variant),
                ui_text.t("gs.col_shadowed"): int(status.counts.sum()),
                ui_text.t("gs.col_excluded"): int((~status.counts).sum()),
            }
        )
    st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    reasons = (
        building_pixels.loc[~building_pixels.counts, "reason"]
        .map(lambda reason: _reason_label(reason, min_depth))
        .value_counts()
    )
    if not reasons.empty:
        st.caption(ui_text.gs_excluded_summary(reasons.to_dict()))
    reach, variant, _ = _settings()
    sim = st.session_state.get(f"gs_sim_{id_start}")
    tags = {
        "Gebaeude": id_start,
        "Reichweite_m": reach,
        "Variante": variant,
        "Mindest_Fliesstiefe_m": f"{min_depth / 100:.2f}",
        "Simulation": ui_text.t("gs.all_sims", lang=ui_text.EXPORT_LANGUAGE)
        if sim is None
        else sim,
    }
    tif_col, csv_col = st.columns(2)
    tif_col.download_button(
        ui_text.t("gs.building_tif"),
        gebaeudeschatten_export.building_geotiff_bytes(building_pixels, tags),
        file_name=gebaeudeschatten_export.building_geotiff_name(
            id_start, reach, variant, min_depth
        ),
        mime="image/tiff",
        key="gs_building_tif",
        on_click="ignore",
        help=ui_text.t("gs.building_tif_help"),
    )
    export = gebaeudeschatten_export.building_export_df(
        building_rows,
        gs.reason_column(variant, min_depth),
        lambda reason: _reason_label(reason, min_depth, lang=ui_text.EXPORT_LANGUAGE),
    )
    csv_col.download_button(
        ui_text.t("gs.building_csv"),
        gebaeudeschatten_export.csv_bytes(export),
        file_name=gebaeudeschatten_export.building_file_name(id_start, reach, variant, min_depth),
        mime="text/csv",
        key="gs_building_csv",
        on_click="ignore",
        help=ui_text.t("gs.building_csv_help"),
    )


def _pixel_table(
    pixel_buildings: pd.DataFrame, min_depth: int, lang: str | None = None
) -> pd.DataFrame:
    """The buildings at the selected pixel, as shown and as downloaded.

    lang: as for ui_text.t; EXPORT_LANGUAGE for the CSV."""
    yes_no = {True: ui_text.t("gs.yes", lang=lang), False: ui_text.t("gs.no", lang=lang)}
    return pd.DataFrame(
        {
            ui_text.t("gs.col_building", lang=lang): pixel_buildings.id_start,
            ui_text.t("gs.col_depth", lang=lang): pixel_buildings.depth / 100,
            ui_text.t("gs.col_sims", lang=lang): pixel_buildings.n_sims,
            ui_text.t("gs.col_counts", lang=lang): pixel_buildings.counts.map(yes_no),
            ui_text.t("gs.col_reason", lang=lang): pixel_buildings.reason.map(
                lambda reason: (
                    "" if pd.isna(reason) else _reason_label(reason, min_depth, lang=lang)
                )
            ),
        }
    )


def _pixel_details(pixel_buildings, min_depth):
    e, n = st.session_state.gs_pixel
    st.subheader(ui_text.gs_pixel_heading(e, n))
    if pixel_buildings is None:
        st.caption(ui_text.t("gs.pixel_no_sim"))
        return
    st.caption(
        ui_text.gs_pixel_summary(
            int(pixel_buildings.counts.sum()),
            len(pixel_buildings),
            _variant_label(st.session_state.gs_variant),
            min_depth,
        )
    )
    # The buildings that count first, then the deepest Fliesstiefe.
    pixel_buildings = pixel_buildings.sort_values(["counts", "depth"], ascending=[False, False])
    table = _pixel_table(pixel_buildings, min_depth)
    pick = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"gs_pixel_table_{e}_{n}",
    )
    reach, variant, _ = _settings()
    st.download_button(
        ui_text.t("gs.pixel_csv"),
        gebaeudeschatten_export.csv_bytes(
            _pixel_table(pixel_buildings, min_depth, lang=ui_text.EXPORT_LANGUAGE)
        ),
        file_name=gebaeudeschatten_export.pixel_file_name(e, n, reach, variant, min_depth),
        mime="text/csv",
        key="gs_pixel_csv",
        on_click="ignore",
    )
    picked_table_rows = pick.selection.rows if pick else []
    if picked_table_rows:
        picked_building = int(pixel_buildings.iloc[picked_table_rows[0]].id_start)
        choice = (e, n, picked_building)
        # The selection repeats on every rerun: act on a new pick only.
        if choice != st.session_state.gs_table_pick:
            st.session_state.gs_table_pick = choice
            # Like a click on the building: it replaces the pixel.
            picked_rows = _building_rows(picked_building, reach)
            _select_building(picked_building, _rows_wgs_bounds(picked_rows))
            st.rerun()
