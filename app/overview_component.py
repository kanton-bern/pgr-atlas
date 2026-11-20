from pathlib import Path
import streamlit.components.v1 as components

import map_labels
import ui_text

# Built from frontend/src/overview/ by `npm run build` (frontend/README.md).
_FRONTEND_DIR = Path(__file__).parent / "overview" / "dist"

_component_func = components.declare_component(
    "maplibre_overview",
    path=str(_FRONTEND_DIR),
)
# The Simulierte Ereignisse map's own texts (frontend/src/overview/args.ts).
_LABELS = ("area", "anriss_popup_prozessquelle")


def texts() -> dict:
    """The map's `labels` and `locale` render args, in the session's language."""
    return map_labels.render_args(
        map_labels.chrome(),
        map_labels.tiles(),
        map_labels.anriss_popup(),
        map_labels.area_classes(),
        {name: ui_text.template(f"map.overview.{name}") for name in _LABELS},
    )


def maplibre_overview(
    center_lat: float,
    center_lon: float,
    pmtiles_port: int,
    pmtiles_path_prefix: str = "",
    coverage_version: str | None = None,
    pmtiles_filename: str | None = None,
    source_layer: str | None = None,
    initial_zoom: float | None = None,
    initial_active_areas: list[float] | None = None,
    highlight_id_anriss: int | None = None,
    key: str = "overview_map",
):
    """coverage_version: version of the gold coverage in coverage_store (see
    ui_common.load_coverage). The JS side fetches it once from
    pmtiles_server.py's /coverage.geojson?v=<version>. None shows no
    coverage.

    initial_zoom: starts the map at center_lat/center_lon and this zoom
    (where the user last clicked an Anriss, or a link's ?z=&lat=&lon=, see
    views/overview.py) instead of the view the map saved in the browser, or
    its default (8). None keeps those.

    initial_active_areas: which Anrissfläche size classes' legend checkboxes
    should start ticked on this mount (views/overview.py's _overview_last_areas,
    captured from the "Anriss öffnen" click's own activeAreas at the moment
    it fired) -- lets "Anriss abwählen" restore the filter the user had set
    up instead of always remounting with every class back on. None means
    "all classes on" (the JS side's own default); an empty list means none
    ("Keine").

    highlight_id_anriss: draws a blue highlight ring around this one
    id_anriss (views/overview.py's _overview_last_selected_id) -- the anriss that was
    open just before navigating away, so "Anriss abwählen" visibly marks
    where the user was. None draws no ring.

    key: the default is also the map's height rule: app.css (.st-key-overview_map)
    stretches the frame down to the footer."""
    if not (_FRONTEND_DIR / "index.html").is_file():
        # Streamlit would serve an empty frame, with no error anywhere.
        raise FileNotFoundError(
            f"{_FRONTEND_DIR / 'index.html'} is missing: run `npm ci && npm run build` in frontend/"
        )
    return _component_func(
        center_lat=center_lat,
        center_lon=center_lon,
        pmtiles_port=pmtiles_port,
        pmtiles_path_prefix=pmtiles_path_prefix,
        coverage_version=coverage_version,
        pmtiles_filename=pmtiles_filename,
        source_layer=source_layer,
        initial_zoom=initial_zoom,
        initial_active_areas=initial_active_areas,
        highlight_id_anriss=highlight_id_anriss,
        key=key,
        **texts(),
    )
