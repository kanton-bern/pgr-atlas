from pathlib import Path
import streamlit.components.v1 as components

import map_labels
import ui_text

# Built from frontend/src/overview_ifk/ by `npm run build` (frontend/README.md).
_FRONTEND_DIR = Path(__file__).parent / "overview_ifk" / "dist"

_component_func = components.declare_component(
    "ifk_pixel_map",
    path=str(_FRONTEND_DIR),
)
# The IFK map's own texts (frontend/src/overview_ifk/args.ts). Its
# "gold_coverage" replaces the shared one: only its Kacheln are clickable.
_LABELS = (
    "gold_coverage",
    "anriss_area",
    "anriss_outline",
    "anriss_legend_title",
    "anriss_popup_rate",
    "pixel_popup_title",
    "pixel_popup_coords",
    "ifk_compute",
    "area_popup_title",
    "area_popup_too_large",
)


def texts() -> dict:
    """The map's `labels` and `locale` render args, in the session's language."""
    return map_labels.render_args(
        map_labels.chrome(),
        map_labels.tiles(),
        map_labels.selection(),
        map_labels.anriss_popup(),
        map_labels.area_classes(),
        {name: ui_text.template(f"map.ifk.{name}") for name in _LABELS},
    )


def ifk_pixel_map(
    center_lat: float,
    center_lon: float,
    coverage_version: str | None = None,
    selected_pixel: tuple[float, float] | None = None,
    selected_selection: dict | None = None,
    area_too_large: bool = False,
    anriss_circles_geojson: dict | None = None,
    anriss_outline_geojson: dict | None = None,
    anriss_legend: dict | None = None,
    pmtiles_port: int = 8505,
    pmtiles_path_prefix: str = "",
    initial_zoom: float | None = None,
    initial_active_areas: list[float] | None = None,
    highlight_id_anriss: int | None = None,
    highlight_pixel: tuple[float, float] | None = None,
    key: str = "ifk_pixel_map",
):
    """Click-to-select LV95 pixel map for the IFK view: shows finalized gold
    kacheln (only they're clickable) and a faint 5x5 m grid at high zoom.
    The map also has Raster-Karten's rectangle and polygon tools, for the IFK
    of an area: a finished drawing or "Löschen" returns {'selection':
    {'type': 'bbox'|'polygon', 'ring': [[E, N], ...]} | None, 'nonce': ...},
    as raster_bbox_map does. A finished drawing, and a click inside the
    selected area, open the area's popup instead of a pixel's; its "IFK
    berechnen" returns {'selection': <that area>, 'nonce': ...,
    'compute': True} (views/ifk_area.py's handle_map_selection).
    Returns {'x': ..., 'y': ..., 'nonce': ..., 'view': {...},
    'prefetch_client': ...} (LV95, snapped to the gold pixel lattice) after
    "IFK berechnen" -- prefetch_client names this map instance in
    ifk_prefetch, which the pixel popup already asked to compute -- or {'id_anriss': ..., 'nonce': ...,
    'view': {...}} after the "Anriss öffnen" popup button, or None before
    the first interaction. `view` is the map's live center/zoom at the
    moment of the click (see views/ifk.py's _open_anriss, which stores it to
    restore this exact pan/zoom on return).

    coverage_version: version of the gold coverage in coverage_store (see
    ui_common.load_coverage). The JS side fetches it once from
    pmtiles_server.py's /coverage.geojson?v=<version>. None shows no
    coverage.

    anriss_circles_geojson (optional): the selected pixel's contributing
    anrisse (compute_ifk_default's anriss_events) as true-scale circles,
    already reprojected + colored server-side (see views/ifk.py's
    _anriss_events_geojson) -- the component only ever renders exact,
    precomputed geometry/color, no client-side transform or color math.

    selected_selection (optional): the selected area, that same bare {'type',
    'ring'} shape, to draw it: an upload or a link, or a drawn one echoed
    back. Never together with selected_pixel (views/ifk_area.py).

    area_too_large: the selected area is over the limits the sidebar names
    (ui_common.selection_limit_error); the area popup then says so and
    disables its button.

    anriss_outline_geojson (optional): one WGS84 outline around all Anrisse
    that reach the selected area (views/ifk_area.py's
    anriss_outline_geojson) -- an area can have 100'000 of them, too many
    for single circles.

    anriss_legend (optional): the color-scale legend for those circles --
    {'gradient', 'vmin_label', 'vmid_label', 'vmax_label'}, see views/ifk.py's
    _anriss_legend_payload. Built from the exact same vmin/vmax
    anriss_circles_geojson normalizes its colors by, so the two never drift
    out of sync. None hides the legend box (no circles to explain yet).

    pmtiles_port/pmtiles_path_prefix: reaches pmtiles_server.py for the
    "Prozessquellen" toggle layer (off by default) -- served from
    the static Prozessquellen tileset (frontend/README.md, "Tilesets")
    (s3://maxi/prozessquelle.pmtiles), same proxy the Overview map's anriss
    tileset already uses, not inlined GeoJSON (that stalled the proxy's own
    thread, see app.py's git history).

    initial_zoom: zoom level to mount at when selected_pixel is None (the
    JS side otherwise defaults to 9) -- lets views/ifk.py restore the viewport the
    user had before navigating away, same purpose as maplibre_overview's
    identical parameter. Ignored once selected_pixel is set (that already
    forces zoom 18, centered on the pixel itself).

    initial_active_areas: which Anrissfläche size-class legend checkboxes
    should start ticked on this mount (see views/ifk.py's _ifk_last_areas,
    captured from the "Anriss öffnen" click's own activeAnrissAreas) --
    lets "Anriss abwählen" restore the filter the user had set up instead
    of always remounting with every class back on. None means "all classes
    on" (the JS side's own default); an empty list means none ("Keine").

    highlight_id_anriss: draws a blue highlight ring around this one
    id_anriss among the selected pixel's contributing anrisse (views/ifk.py's
    _ifk_last_selected_id) -- the anriss that was open just before
    navigating away. None draws no ring.

    highlight_pixel: draws a dashed grey "ghost" square (LV95 x, y) at the
    pixel "Pixel abwählen" most recently cleared (views/ifk.py's
    _ifk_deselected_pixel) -- distinct from selected_pixel's own solid blue
    square, which marks the currently active pixel (if any). None draws no
    ghost square; cleared automatically once a new pixel is actively
    selected."""
    if not (_FRONTEND_DIR / "index.html").is_file():
        # Streamlit would serve an empty frame, with no error anywhere.
        raise FileNotFoundError(
            f"{_FRONTEND_DIR / 'index.html'} is missing: run `npm ci && npm run build` in frontend/"
        )
    return _component_func(
        center_lat=center_lat,
        center_lon=center_lon,
        coverage_version=coverage_version,
        selected_pixel=list(selected_pixel) if selected_pixel else None,
        selected_selection=selected_selection,
        area_too_large=area_too_large,
        anriss_circles_geojson=anriss_circles_geojson,
        anriss_outline_geojson=anriss_outline_geojson,
        anriss_legend=anriss_legend,
        pmtiles_port=pmtiles_port,
        pmtiles_path_prefix=pmtiles_path_prefix,
        initial_zoom=initial_zoom,
        initial_active_areas=initial_active_areas,
        highlight_id_anriss=highlight_id_anriss,
        highlight_pixel=list(highlight_pixel) if highlight_pixel else None,
        key=key,
        **texts(),
    )
