// The IFK map's own layers, added on 'load' after the gold coverage and the
// Prozessquellen. Order is draw order, bottom to top: the outline of an area's
// anrisse, a pixel's anriss circles, their highlight ring, the pixel grid, the
// selected pixel, the deselected pixel.

import type { FeatureCollection } from "geojson";
import type { FilterSpecification, GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

import type { Pixel } from "@/overview_ifk/args";
import { EMPTY, geojsonSource } from "@/shared/geojson-source";
import { addPixelGridLayer, pixelSquare } from "@/shared/pixel-grid";

export const CIRCLE_LAYERS = ["anriss-circles-fill", "anriss-circles-outline"] as const;

// Blue with a white halo: the circles under it are yellow to red, and the
// basemap can be light.
const BLUE = "#2979ff";

// The dark end of the circles' YlOrRd scale.
const ANRISS_OUTLINE_COLOR = "#bd0026";

export interface IfkSources {
  outline: GeoJSONSource;
  circles: GeoJSONSource;
  selected: GeoJSONSource;
  deselected: GeoJSONSource;
}

function addOutlineLayers(map: MapLibreMap): void {
  map.addLayer({
    id: "anriss-outline-fill",
    type: "fill",
    source: "anriss-outline",
    paint: { "fill-color": ANRISS_OUTLINE_COLOR, "fill-opacity": 0.12 },
  });
  map.addLayer({
    id: "anriss-outline-line",
    type: "line",
    source: "anriss-outline",
    paint: { "line-color": ANRISS_OUTLINE_COLOR, "line-width": 1.5, "line-opacity": 0.9 },
  });
}

function addCircleLayers(map: MapLibreMap, highlightId: number | null): void {
  map.addLayer({
    id: "anriss-circles-fill",
    type: "fill",
    source: "anriss-circles",
    paint: { "fill-color": ["get", "fillColor"], "fill-opacity": 0.55 },
  });
  map.addLayer({
    id: "anriss-circles-outline",
    type: "line",
    source: "anriss-circles",
    paint: { "line-color": ["get", "fillColor"], "line-width": 1.5, "line-opacity": 0.9 },
  });
  if (highlightId == null) return;
  // "You were just here": a ring around the anriss that was open last. The
  // area filter doesn't apply, so it shows even when its class is off.
  const filter: FilterSpecification = ["==", ["get", "id_anriss"], highlightId];
  map.addLayer({
    id: "anriss-circles-highlight-halo",
    type: "line",
    source: "anriss-circles",
    filter,
    paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.9 },
  });
  map.addLayer({
    id: "anriss-circles-highlight",
    type: "line",
    source: "anriss-circles",
    filter,
    paint: { "line-color": BLUE, "line-width": 3, "line-opacity": 1 },
  });
}

function addPixelLayers(
  map: MapLibreMap,
  id: string,
  pixel: Pixel | null,
  haloOpacity: number,
): void {
  map.addSource(id, { type: "geojson", data: pixelSquare(pixel) });
  map.addLayer({
    id: `${id}-halo`,
    type: "line",
    source: id,
    paint: { "line-color": "#ffffff", "line-width": 5, "line-opacity": haloOpacity },
  });
  map.addLayer({
    id: `${id}-outline`,
    type: "line",
    source: id,
    paint: { "line-color": BLUE, "line-width": 2.5 },
  });
}

export interface IfkLayerArgs {
  outline: FeatureCollection | null;
  circles: FeatureCollection | null;
  highlightId: number | null;
  selected: Pixel | null;
  deselected: Pixel | null;
}

export function addIfkLayers(map: MapLibreMap, args: IfkLayerArgs): IfkSources {
  map.addSource("anriss-outline", { type: "geojson", data: args.outline ?? EMPTY });
  addOutlineLayers(map);
  map.addSource("anriss-circles", { type: "geojson", data: args.circles ?? EMPTY });
  addCircleLayers(map, args.highlightId);
  addPixelGridLayer(map);
  addPixelLayers(map, "selected-pixel", args.selected, 0.9);
  // The pixel "Pixel abwählen" just cleared.
  addPixelLayers(map, "deselected-pixel", args.deselected, 0.8);
  return {
    outline: geojsonSource(map, "anriss-outline"),
    circles: geojsonSource(map, "anriss-circles"),
    selected: geojsonSource(map, "selected-pixel"),
    deselected: geojsonSource(map, "deselected-pixel"),
  };
}
