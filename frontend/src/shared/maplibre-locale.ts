// MapLibre's own UI strings (button titles, aria-labels), from the labels
// Python sends, for the `locale` option of every map and for a language
// switch on a live map.

import type { Map as MapLibreMap, ScaleControl } from "maplibre-gl";

import type { Labels, TextSource } from "@/shared/texts";

/** Every UI string key MapLibre has; a key added by a MapLibre upgrade fails the typecheck. */
type UiStringKey = Parameters<MapLibreMap["_getUIString"]>[0];

/** The label key of each MapLibre UI string. */
const MAPLIBRE_LABEL_KEYS = {
  "AttributionControl.ToggleAttribution": "maplibre_attribution_toggle",
  "AttributionControl.MapFeedback": "maplibre_attribution_feedback",
  "FullscreenControl.Enter": "maplibre_fullscreen_enter",
  "FullscreenControl.Exit": "maplibre_fullscreen_exit",
  "GeolocateControl.FindMyLocation": "maplibre_geolocate_find",
  "GeolocateControl.LocationNotAvailable": "maplibre_geolocate_unavailable",
  "LogoControl.Title": "maplibre_logo",
  "Map.Title": "maplibre_map",
  "Marker.Title": "maplibre_marker",
  "NavigationControl.ResetBearing": "maplibre_reset_bearing",
  "NavigationControl.ZoomIn": "maplibre_zoom_in",
  "NavigationControl.ZoomOut": "maplibre_zoom_out",
  "Popup.Close": "maplibre_popup_close",
  "ScaleControl.Feet": "maplibre_scale_feet",
  "ScaleControl.Meters": "maplibre_scale_meters",
  "ScaleControl.Kilometers": "maplibre_scale_kilometers",
  "ScaleControl.Miles": "maplibre_scale_miles",
  "ScaleControl.NauticalMiles": "maplibre_scale_nautical_miles",
  "GlobeControl.Enable": "maplibre_globe_enable",
  "GlobeControl.Disable": "maplibre_globe_disable",
  "TerrainControl.Enable": "maplibre_terrain_enable",
  "TerrainControl.Disable": "maplibre_terrain_disable",
  "CooperativeGesturesHandler.WindowsHelpText": "maplibre_cooperative_windows",
  "CooperativeGesturesHandler.MacHelpText": "maplibre_cooperative_mac",
  "CooperativeGesturesHandler.MobileHelpText": "maplibre_cooperative_mobile",
} as const satisfies Record<UiStringKey, string>;

export type MapLibreLabelKey = (typeof MAPLIBRE_LABEL_KEYS)[UiStringKey];

export const MAPLIBRE_LABELS: readonly MapLibreLabelKey[] = Object.values(MAPLIBRE_LABEL_KEYS);

/** The `locale` option of a map: MapLibre's keys with the labels' texts. */
export function maplibreLocale(labels: Labels<MapLibreLabelKey>): Record<UiStringKey, string> {
  const entries = Object.entries(MAPLIBRE_LABEL_KEYS) as [UiStringKey, MapLibreLabelKey][];
  return Object.fromEntries(entries.map(([ui, key]) => [ui, labels[key]])) as Record<
    UiStringKey,
    string
  >;
}

function setTitle(el: Element | null, text: string): void {
  el?.setAttribute("title", text);
  el?.setAttribute("aria-label", text);
}

/**
 * Keeps MapLibre's strings on a live map in step with the labels. MapLibre
 * has no API for a new locale: it reads its table (`_locale`) when it builds
 * a control or opens a popup. So the table is replaced, and the strings the
 * map already shows are set again: the canvas's aria-label, the zoom buttons,
 * the attribution button, the open popups' close buttons, and the scale bar
 * (setUnit redraws it). The controls the app doesn't use read the new table
 * whenever they would be built.
 */
export function bindMapLibreLocale(
  map: MapLibreMap,
  scale: ScaleControl,
  texts: TextSource<MapLibreLabelKey>,
): void {
  texts.bind(() => {
    const locale = maplibreLocale(texts.labels);
    map._locale = { ...map._locale, ...locale };
    const root = map.getContainer();
    map.getCanvas().setAttribute("aria-label", locale["Map.Title"]);
    setTitle(root.querySelector(".maplibregl-ctrl-zoom-in"), locale["NavigationControl.ZoomIn"]);
    setTitle(root.querySelector(".maplibregl-ctrl-zoom-out"), locale["NavigationControl.ZoomOut"]);
    setTitle(
      root.querySelector(".maplibregl-ctrl-attrib-button"),
      locale["AttributionControl.ToggleAttribution"],
    );
    root.querySelectorAll(".maplibregl-popup-close-button").forEach((btn) => {
      btn.setAttribute("aria-label", locale["Popup.Close"]);
    });
    scale.setUnit("metric");
  });
}
