from pathlib import Path
import streamlit.components.v1 as components

import map_labels
import ui_text

# Built from frontend/src/raster_bbox_map/ by `npm run build` (frontend/README.md).
_FRONTEND_DIR = Path(__file__).parent / "raster_bbox_map" / "dist"

_component_func = components.declare_component(
    "raster_bbox_map",
    path=str(_FRONTEND_DIR),
)
# The Raster map's own texts (frontend/src/raster_bbox_map/args.ts).
_LABELS = (
    "raster_layer",
    "var_switch_title",
    "legend_title_unit",
    "log_scale",
    "mask_ticks",
    "pixel_value",
    "pixel_value_unitless",
    "pixel_mask_yes",
    "pixel_mask_no",
    "crop_loading",
    "crop_error",
    "derivate_error",
    "image_error",
    "values_error",
)


def texts() -> dict:
    """The map's `labels` and `locale` render args, in the session's language."""
    return map_labels.render_args(
        map_labels.chrome(),
        map_labels.tiles(),
        map_labels.selection(),
        map_labels.raster_opacity(),
        {name: ui_text.template(f"map.raster.{name}") for name in _LABELS},
    )


def raster_bbox_map(
    center_lat: float,
    center_lon: float,
    coverage_version: str | None = None,
    selected_selection: dict | None = None,
    raster_overlays: dict | None = None,
    active_variable: str | None = None,
    coverage_fill_opacity: float | None = None,
    derivate_bbox_metric: str | None = None,
    derivate_bbox_partition: str | None = None,
    derivate_bbox_band: int | None = None,
    derivate_bbox_label: str | None = None,
    derivate_bbox_unit: str | None = None,
    derivate_bbox_scale: str | None = None,
    derivate_bbox_ramp: str | None = None,
    derivate_bbox_vmin: float | None = None,
    derivate_bbox_vmax: float | None = None,
    derivate_bbox_note: str | None = None,
    derivate_bbox_server_port: int = 8503,
    derivate_bbox_path_prefix: str = "",
    pmtiles_port: int = 8505,
    pmtiles_path_prefix: str = "",
    key: str = "raster_bbox_map",
):
    """Drag-to-select LV95 area map for the Raster-Karten view -- same
    gold-coverage + 5x5 m pixel-grid chrome as ifk_pixel_map (see
    frontend/src/overview_ifk/), but the interaction is a toggled draw-a-
    rectangle OR draw-a-polygon (mapbox-gl-draw) instead of a single pixel
    click. Rectangle corners snap to the gold pixel lattice; polygon
    vertices don't need to (point-in-polygon containment is computed per
    actual pixel center server-side, not from vertex position).

    Returns {'selection': {'type': 'bbox'|'polygon', 'ring': [[E, N], ...]}
    | None, 'nonce': ...} after EVERY completed rectangle drag, polygon
    draw, or "Löschen" click (nonce is a fresh value each time, same
    disambiguation pattern frontend/src/overview_ifk/'s "Anriss öffnen" popup
    uses -- callers compare the nonce, not the selection payload, since two
    different interactions can otherwise carry an identical or None payload,
    e.g. "Löschen" clicked when nothing was drawn directly in this component
    instance yet). Returns bare None (no envelope at all) before this
    component instance has EVER sent a value, its truly-untouched initial
    state -- callers must NOT treat that the same as an explicit
    {'selection': None, ...} from a real "Löschen" click, since a caller
    that set the CURRENT selection some other way (e.g. views/raster_karten.py's file
    upload, entirely outside this component) needs "never touched" to leave
    that selection alone, not silently clear it. `ring` is a closed LV95
    ring, last point == first -- same shape ifk_and_raster.py's
    normalize_selection/selection_bounds consume directly. selected_selection
    (the argument, NOT wrapped in a nonce envelope) is that same bare
    {'type', 'ring'} shape, passed back in to redisplay a previous selection
    after a rerun.

    coverage_version: version of a coverage in coverage_store: the gold
    kacheln (Raster-Karten, see ui_common.load_coverage) or the metric's
    precomputed kacheln (Raster-Derivate). The JS side fetches it once from
    pmtiles_server.py's /coverage.geojson?v=<version>.

    raster_overlays, if given, is a {'depth'|'velocity'|'pressure':
    descriptor} dict -- one entry per finished file from the last raster job
    (mode B computes all three in a single pass, see build_raster_for_bbox,
    so all of them are already sitting on disk, not just the currently-
    selected one). See views/raster_karten.py's _register_raster_job for the descriptor
    ({job_id, var, corners, gradient, label, unit, log_scale, vmin_label,
    vmid_label, vmax_label, hover_caption, hover: {width, height, xmin,
    ymax, res} | None}). The component fetches the image from
    derivate_bbox_server.py's /job/<job_id>/<var>.png (reached via
    derivate_bbox_server_port/_path_prefix) and draws it as a maplibre image
    layer, and fetches the hover grid from /job/<job_id>/<var>.f32 once per
    variable. A radio group appears (only) when more than one entry is
    present, switching between them entirely client-side -- no rerun, no
    recompute. active_variable picks which entry is shown first. None/empty
    (before a raster exists, or after "Zurücksetzen") removes any overlay.

    pmtiles_port/pmtiles_path_prefix: reaches pmtiles_server.py for the
    "Prozessquellen" toggle layer (off by default) -- served from
    the static Prozessquellen tileset (frontend/README.md, "Tilesets")
    (s3://maxi/prozessquelle.pmtiles), same proxy the Overview map's anriss
    tileset already uses, not inlined GeoJSON (that stalled the proxy's own
    thread, see app.py's git history).

    coverage_fill_opacity: override the coverage layer's default gold fill
    (0.25 opacity). None/omitted keeps the JS side's own default, so the
    existing Raster-Karten call site (which never passes it) is unaffected.

    derivate_bbox_server_port/_path_prefix are used by both views.
    derivate_bbox_* (the rest): drives the Raster-Derivate view's live map layer
    (see derivate_bbox_server.py's module docstring). The component asks derivate_bbox_server.py (a local Tornado
    service, reached via derivate_bbox_server_port/_path_prefix the same
    way pmtiles_port/_path_prefix reaches pmtiles_server.py) for a fresh
    crop of the current viewport on every pan/zoom -- ONE dynamic image
    source, not one per kachel, so there's no viewport cap. The service
    crops+colorizes entirely in native LV95 (no reprojection) and reports
    back the crop's own true, pixel-snapped bounds, which the component
    places via the same zero-reprojection mechanism raster_overlay.py
    uses (transform only the 4 corners, MapLibre's GPU warps the
    untouched pixels). derivate_bbox_metric/_partition/_band (1-based band
    index) select which canton mosaic COG + band the service reads (derivate
    lake layout, see probe_core.derivate.derivate_lake); a None metric
    removes the layer. derivate_bbox_scale ('log'|'linear'|'mask')/_ramp/
    _vmin/_vmax are the colour style -- forwarded as-is to the service, which
    colorizes with exactly these, AND used for the legend, so pixels and
    legend can't disagree. _label/_unit/_note feed the same legend box
    raster_overlays uses (the two features never run in the same component
    instance)."""
    if not (_FRONTEND_DIR / "index.html").is_file():
        # Streamlit would serve an empty frame, with no error anywhere.
        raise FileNotFoundError(
            f"{_FRONTEND_DIR / 'index.html'} is missing: run `npm ci && npm run build` in frontend/"
        )
    return _component_func(
        center_lat=center_lat,
        center_lon=center_lon,
        coverage_version=coverage_version,
        selected_selection=selected_selection,
        raster_overlays=raster_overlays,
        active_variable=active_variable,
        coverage_fill_opacity=coverage_fill_opacity,
        derivate_bbox_metric=derivate_bbox_metric,
        derivate_bbox_partition=derivate_bbox_partition,
        derivate_bbox_band=derivate_bbox_band,
        derivate_bbox_label=derivate_bbox_label,
        derivate_bbox_unit=derivate_bbox_unit,
        derivate_bbox_scale=derivate_bbox_scale,
        derivate_bbox_ramp=derivate_bbox_ramp,
        derivate_bbox_note=derivate_bbox_note,
        derivate_bbox_vmin=derivate_bbox_vmin,
        derivate_bbox_vmax=derivate_bbox_vmax,
        derivate_bbox_server_port=derivate_bbox_server_port,
        derivate_bbox_path_prefix=derivate_bbox_path_prefix,
        pmtiles_port=pmtiles_port,
        pmtiles_path_prefix=pmtiles_path_prefix,
        key=key,
        **texts(),
    )
