"""The texts of the map components, from app/texts.toml.

Each map component takes a `labels` render arg with exactly its own keys
(frontend/src/<component>/args.ts) and a `locale` for its numbers; a missing
or extra key stops the map with an error naming it. The groups here are the
texts several maps share; each app/*_component.py adds its own group
(map.<group>.* in texts.toml) and calls render_args().
"""

import ui_text

# MapLibre's own strings and the controls every map has (shared/map-controls.ts).
CHROME = (
    "maplibre_attribution_toggle",
    "maplibre_attribution_feedback",
    "maplibre_fullscreen_enter",
    "maplibre_fullscreen_exit",
    "maplibre_geolocate_find",
    "maplibre_geolocate_unavailable",
    "maplibre_logo",
    "maplibre_map",
    "maplibre_marker",
    "maplibre_reset_bearing",
    "maplibre_zoom_in",
    "maplibre_zoom_out",
    "maplibre_popup_close",
    "maplibre_scale_feet",
    "maplibre_scale_meters",
    "maplibre_scale_kilometers",
    "maplibre_scale_miles",
    "maplibre_scale_nautical_miles",
    "maplibre_globe_enable",
    "maplibre_globe_disable",
    "maplibre_terrain_enable",
    "maplibre_terrain_disable",
    "maplibre_cooperative_windows",
    "maplibre_cooperative_mac",
    "maplibre_cooperative_mobile",
    "legend",
    "legend_hide",
    "legend_hide_aria",
    "legend_show",
    "legend_show_aria",
    "legend_chip",
    "close",
    "basemap",
    "basemap_lk",
    "basemap_relief",
    "basemap_osm",
    "search",
    "search_go",
    "search_go_title",
    "search_error_format",
    "search_error_outside",
    "canton",
    "zoom_level",
    "map_data_error",
    "layers",
)
# The Kacheln and Prozessquellen layers of the Simulierte Ereignisse, IFK and Raster maps.
TILES = ("gold_coverage", "prozessquellen", "prozessquelle_popup")
# The drawing buttons and the size readout (shared/selection.ts).
SELECTION = (
    "length_m",
    "length_km",
    "selection_size_rect",
    "selection_size_polygon",
    "draw_rect",
    "draw_polygon",
    "draw_clear",
)
# The opacity slider of a raster layer (shared/layer-box.ts): Raster and Gebäudeschatten maps.
RASTER_OPACITY = ("opacity", "opacity_aria", "opacity_value")
# The Anriss popup of the Simulierte Ereignisse and IFK maps.
ANRISS_POPUP = ("anriss_popup_title", "anriss_popup_area", "anriss_open")
# "Alle · Keine" next to the area-class filter of the Simulierte Ereignisse and IFK maps.
AREA_CLASSES = (
    "area_classes_all",
    "area_classes_none",
    "area_classes_all_aria",
    "area_classes_none_aria",
)


def chrome() -> dict[str, str]:
    return {key: ui_text.template(f"map.chrome.{key}") for key in CHROME}


def tiles() -> dict[str, str]:
    return {key: ui_text.template(f"map.tiles.{key}") for key in TILES}


def selection() -> dict[str, str]:
    return {key: ui_text.template(f"map.selection.{key}") for key in SELECTION}


def raster_opacity() -> dict[str, str]:
    return {key: ui_text.template(f"map.raster_opacity.{key}") for key in RASTER_OPACITY}


def anriss_popup() -> dict[str, str]:
    return {key: ui_text.template(f"map.anriss_popup.{key}") for key in ANRISS_POPUP}


def area_classes() -> dict[str, str]:
    return {key: ui_text.template(f"map.area_classes.{key}") for key in AREA_CLASSES}


def render_args(*groups: dict[str, str]) -> dict:
    """The `labels` and `locale` render args, in the session's language.

    Args:
        *groups: the component's texts by key; a later group's key replaces
            an earlier one's (the IFK map's own "gold_coverage").
    """
    labels: dict[str, str] = {}
    for group in groups:
        labels |= group
    return {"labels": labels, "locale": ui_text.number_locale()}
