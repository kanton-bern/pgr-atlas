from pathlib import Path
import streamlit.components.v1 as components

import map_labels
import ui_text

# Built from frontend/src/gebaeudeschatten_map/ by `npm run build` (frontend/README.md).
_FRONTEND_DIR = Path(__file__).parent / "gebaeudeschatten_map" / "dist"

_component_func = components.declare_component(
    "gebaeudeschatten_map",
    path=str(_FRONTEND_DIR),
)
# The Gebäudeschatten map's own texts (frontend/src/gebaeudeschatten_map/args.ts).
_LABELS = ("mask_default", "mask_error", "buildings", "building_hover", "cells_default")


def texts() -> dict:
    """The map's `labels` and `locale` render args, in the session's language."""
    return map_labels.render_args(
        map_labels.chrome(),
        map_labels.raster_opacity(),
        {name: ui_text.template(f"map.gs.{name}") for name in _LABELS},
    )


def gebaeudeschatten_map(
    bounds: list[list[float]],
    layers: dict,
    servers: dict,
    focus: dict | None = None,
    key: str = "gebaeudeschatten_map",
):
    """Map of the Gebäudeschatten view.

    bounds: WGS84 [[lat_min, lon_min], [lat_max, lon_max]], read at mount only.

    layers: dict with the keys below. servers: {'pmtiles_port',
    'pmtiles_path_prefix'} of pmtiles_server (the buildings tiles).

    buildings_pmtiles / buildings_layer: the buildings tileset (a root-level
    key of the gold bucket, served by pmtiles_server) and its source layer;
    features carry id_start and area_m2.

    mask: the affected-mask overlay, cropped per viewport by
    derivate_bbox_server: {'metric', 'partition', 'label', 'server_port',
    'path_prefix'}, or None for no mask.

    cells_geojson: square pixel polygons with fillColor, fillOpacity and
    tooltip (a multi-line string shown on hover). Re-read only when
    cells_version changes. cells_label names the layer in the layer box, and
    cells_legend ([{'color', 'label'}]) lists its colours below it.

    overlays: outline layers in drawing order (bottom first), each
    {'id', 'label', 'geojson', 'color', 'width', 'dash' (list or None),
    'fill' (colour or None), 'visible'}. An overlay with geojson None keeps
    no checkbox; one missing from a later render is emptied.

    focus: {'bounds', 'nonce'} -- the map fits these bounds whenever the
    nonce changes (a selection from the sidebar), else None.

    Returns {'type': 'building', 'id_start', 'nonce'} after a click on a
    building, {'type': 'pixel', 'e', 'n', 'nonce'} (LV95 pixel center) after
    a click anywhere else or a Shift-click, else None. The value repeats on
    every rerun until the next click, so compare the nonce."""
    if not (_FRONTEND_DIR / "index.html").is_file():
        # Streamlit would serve an empty frame, with no error anywhere.
        raise FileNotFoundError(
            f"{_FRONTEND_DIR / 'index.html'} is missing: run `npm ci && npm run build` in frontend/"
        )
    return _component_func(
        bounds=bounds, focus=focus, key=key, default=None, **layers, **servers, **texts()
    )
