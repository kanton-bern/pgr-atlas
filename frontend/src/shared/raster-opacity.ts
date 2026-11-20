// How a raster layer (an image source drawn as a `raster` layer) is shown:
// its layer-box checkbox (visible or not) and its opacity slider. The layer
// box (layer-box.ts) holds the controls; the code that adds the layer reads
// the current style, since a crop is replaced after every move.
//
// The chosen opacity lives on window.top, like the basemap choice
// (map-controls.ts): every map iframe is a same-origin child of the one
// Streamlit page, so it survives a view switch and a remount of the map, but
// not a page reload.

import type { Map as MapLibreMap } from "maplibre-gl";

/** The slider's step; also what an arrow key moves it by. */
export const OPACITY_STEP_PERCENT = 5;

/** How a raster layer is drawn now. */
export interface RasterStyle {
  visible: boolean;
  /** From 0 (transparent) to 1 (opaque). */
  opacity: number;
}

/** The layout and paint of a raster layer added with `style`. */
export function rasterLayerStyle(style: RasterStyle): {
  layout: { visibility: "visible" | "none" };
  paint: { "raster-opacity": number };
} {
  return {
    layout: { visibility: style.visible ? "visible" : "none" },
    paint: { "raster-opacity": style.opacity },
  };
}

/** The part of the map that styles layers. */
export type StyledMap = Pick<MapLibreMap, "getLayer" | "setLayoutProperty" | "setPaintProperty">;

/**
 * Shows or hides those of `layers` that are on the map, and sets their
 * `raster-opacity` when `opacity` is given (layers that aren't rasters get
 * none). A layer that isn't there yet takes the style when it is added.
 */
export function styleLayers(
  map: StyledMap,
  layers: readonly string[],
  visible: boolean,
  opacity?: number,
): void {
  for (const layer of layers) {
    if (!map.getLayer(layer)) continue;
    map.setLayoutProperty(layer, "visibility", visible ? "visible" : "none");
    if (opacity !== undefined) map.setPaintProperty(layer, "raster-opacity", opacity);
  }
}

/**
 * A slider value (the input's string) as a whole percent from 0 to 100, on
 * the slider's steps; `fallback` for anything that isn't a number.
 */
export function opacityPercent(value: string | number, fallback: number): number {
  const percent = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(percent)) return fallback;
  const stepped = Math.round(percent / OPACITY_STEP_PERCENT) * OPACITY_STEP_PERCENT;
  return Math.min(100, Math.max(0, stepped));
}

/** The opacities the user chose, in percent, by the layer's memory key. */
export interface OpacityMemory {
  get(key: string): number | undefined;
  set(key: string, percent: number): void;
}

declare global {
  interface Window {
    __probeRasterOpacityPercent?: Record<string, number>;
  }
}

/** The page's memory, on window.top (see the top of this file). */
export function pageOpacityMemory(): OpacityMemory {
  const top = window.top ?? window;
  const percents = (top.__probeRasterOpacityPercent ??= {});
  return {
    get: (key) => percents[key],
    set: (key, percent) => {
      percents[key] = percent;
    },
  };
}
