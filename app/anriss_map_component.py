from pathlib import Path
import streamlit.components.v1 as components

import map_labels
import ui_text

# Built from frontend/src/anriss_map/ by `npm run build` (frontend/README.md).
_FRONTEND_DIR = Path(__file__).parent / "anriss_map" / "dist"

_component_func = components.declare_component(
    "anriss_result_map",
    path=str(_FRONTEND_DIR),
)
# The Anriss map's own texts (frontend/src/anriss_map/args.ts).
_LABELS = ("variable", "cell_value")


def texts() -> dict:
    """The map's `labels` and `locale` render args, in the session's language."""
    return map_labels.render_args(
        map_labels.chrome(),
        {name: ui_text.template(f"map.anriss.{name}") for name in _LABELS},
    )


def anriss_result_map(
    bounds: list[list[float]],
    cells_geojson: dict | None,
    cells_version: str,
    cells_label: str,
    legend: dict | None,
    overlays: list[dict],
    variables: list[dict],
    active_variable: str,
    pmtiles_port: int = 8505,
    pmtiles_path_prefix: str = "",
    key: str = "anriss_result_map",
):
    """Result map of the Anriss view: one scenario's pixels colored by the
    selected variable, with the Umhüllende/Anriss/800m-circle outlines on top.

    bounds: WGS84 [[lat_min, lon_min], [lat_max, lon_max]] the map opens on.
    Read at mount only -- pass a key per anriss, so a new anriss remounts
    (and frames itself) while a parameter change keeps the user's pan/zoom.

    cells_geojson: square pixel polygons, already reprojected and colored
    server-side (views/anriss.py's _continuous_cells_geojson): each feature carries
    fillColor and value_label (shown on hover). The map only re-reads it when
    cells_version changes, so a rerun that only touches the sidebar doesn't
    rebuild the layer.

    cells_label: the variable's German name, for the layer box and the hover
    text ("Fliesstiefe: 0.42 m").

    legend: {'title', 'gradient', 'vmin_label', 'vmid_label', 'vmax_label'}
    or None (no legend).

    overlays: outline layers in drawing order (bottom first), each
    {'id', 'label', 'geojson', 'color', 'width', 'dash' (list or None),
    'opacity', 'visible'}. Each gets a checkbox in the layer box; 'visible'
    is its default, followed on every render until the user ticks the box
    themselves. An overlay with geojson None gets neither layer nor checkbox.

    variables: the variable switcher's buttons, [{'key', 'label'}], with
    active_variable (a key) highlighted.

    Returns {'variable': <key>} once the user picks another variable in the
    switcher, else None."""
    if not (_FRONTEND_DIR / "index.html").is_file():
        # Streamlit would serve an empty frame, with no error anywhere.
        raise FileNotFoundError(
            f"{_FRONTEND_DIR / 'index.html'} is missing: run `npm ci && npm run build` in frontend/"
        )
    return _component_func(
        bounds=bounds,
        cells_geojson=cells_geojson,
        cells_version=cells_version,
        cells_label=cells_label,
        legend=legend,
        overlays=overlays,
        variables=variables,
        active_variable=active_variable,
        pmtiles_port=pmtiles_port,
        pmtiles_path_prefix=pmtiles_path_prefix,
        key=key,
        default=None,
        **texts(),
    )
