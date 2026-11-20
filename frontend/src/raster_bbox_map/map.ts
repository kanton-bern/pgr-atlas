// The raster map of Raster-Karten and Raster-Derivate: draw or upload an
// area, see the finished rasters (Raster-Karten) or live canton crops
// (Raster-Derivate) with their legend and pixel values.
//
// The map is built from the first render. Every render then goes through
// render(), which compares each part of the args with what is on the map by
// a key and only changes what differs. Renders that arrive
// before the map has loaded are kept, and the latest is applied on 'load'.

import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";

import { RASTER_LABELS, type RasterArgs, type RasterTexts } from "@/raster_bbox_map/args";
import {
  DERIVATE_LAYER,
  DERIVATE_OPACITY_PERCENT,
  DerivateLayer,
  derivateKey,
  derivateParams,
} from "@/raster_bbox_map/derivate";
import { type Drawing, wireDrawing } from "@/shared/drawing";
import {
  OVERLAY_LAYER,
  OVERLAY_OPACITY_PERCENT,
  RasterOverlays,
  overlaysKey,
} from "@/raster_bbox_map/overlays";
import { LayerBox, swatch } from "@/shared/layer-box";
import { hideLegend, hideTooltip } from "@/raster_bbox_map/panels";
import { SelectionLayer } from "@/shared/selection";
import { ringBounds } from "@/shared/selection-geometry";
import { toWgs } from "@/shared/lv95";
import { maplibreLocale } from "@/shared/maplibre-locale";
import {
  addBasemapLayers,
  addGoldCoverageLayer,
  addProzessquelleLayer,
  CANTON_BERN_VIEW,
  ATTRIBUTION,
  glyphsUrl,
  initChrome,
  type MapStatus,
  pageTexts,
  type ProzessquelleLayer,
} from "@/shared/map-controls";
import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import { addPixelGridLayer } from "@/shared/pixel-grid";
import type { StreamlitBridge } from "@/shared/streamlit-bridge";
import type { Selection, SelectionValue } from "@/shared/types";
import { coverageUrl, derivateSidecar, tileSidecar, type Sidecar } from "@/shared/urls";

const DEFAULT_ZOOM = 9;
const SELECTION_ZOOM = 15;
const MIN_ZOOM = 7;
const MAX_ZOOM = 21;
// Reads as "200 m" on the scale bar.
const SEARCH_ZOOM = 14.9;
// The layer-box rows of the two raster layers; a view shows one of them.
const OVERLAY_ROW = "raster-overlay";
const DERIVATE_ROW = "derivate";

interface Parts {
  tiles: Sidecar;
  coverage: GeoJSONSource;
  box: LayerBox;
  overlays: RasterOverlays;
  derivate: DerivateLayer;
  selection: SelectionLayer;
  drawing: Drawing;
  prozessquelle: ProzessquelleLayer;
  /** A failed value request ("Raster-Derivate"), in the status line. */
  showDerivateError: (err: unknown) => void;
}

/** What every part of the map needs from the component. */
interface Context {
  bridge: StreamlitBridge;
  texts: RasterTexts;
  status: MapStatus;
}

/** What is on the map, by key; `undefined` for "not applied yet". */
interface Applied {
  coverage?: string | null;
  overlays?: string | null;
  derivate?: string | null;
}

function createMap(args: RasterArgs, texts: RasterTexts): MapLibreMap {
  const selection = args.selected_selection;
  let center = { lat: args.center_lat, lon: args.center_lon };
  if (selection) {
    const bounds = ringBounds(selection.ring);
    center = toWgs((bounds.xmin + bounds.xmax) / 2, (bounds.ymin + bounds.ymax) / 2);
  }
  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, glyphs: glyphsUrl(), sources: {}, layers: [] },
    attributionControl: ATTRIBUTION,
    locale: maplibreLocale(texts.labels),
    center: [center.lon, center.lat],
    zoom: selection ? SELECTION_ZOOM : DEFAULT_ZOOM,
    minZoom: MIN_ZOOM,
    maxZoom: MAX_ZOOM,
  });
  // Debug handle: in DevTools, pick this iframe in the console's context menu
  // and use window.debugMap. The component tests reach the map through it.
  window.debugMap = map;
  // The canvas takes the container's size at creation, and Streamlit may set
  // the frame height after that, so follow the container's size.
  new ResizeObserver(() => {
    map.resize();
  }).observe(map.getContainer());
  return map;
}

function sendSelection(bridge: StreamlitBridge, selection: Selection | null): void {
  const value: SelectionValue = { selection, nonce: Date.now() + Math.random() };
  bridge.setComponentValue(value);
}

/**
 * A click shows the value under it (Raster-Derivate asks the server,
 * Raster-Karten reads its hover grid; the hover alone never fires on touch),
 * then a Prozessquelle popup. Not while drawing: the click is a vertex then.
 */
function wireClicks(map: MapLibreMap, parts: Parts): void {
  map.on("mousemove", (e) => {
    // Raster-Derivate's click value uses the same tooltip; moving on mustn't hide it.
    if (!parts.derivate.active) parts.overlays.showValueAt(e.lngLat, e.point);
  });
  map.getContainer().addEventListener("mouseleave", hideTooltip);
  map.on("click", (e: MapMouseEvent) => {
    if (parts.drawing.active) return;
    if (parts.derivate.active) {
      parts.derivate.showValueAt(e.lngLat, e.point).catch(parts.showDerivateError);
    } else {
      parts.overlays.showValueAt(e.lngLat, e.point);
    }
    parts.prozessquelle.tryHandleClick(e);
  });
}

function addLayers(map: MapLibreMap, args: RasterArgs, ctx: Context): Parts {
  const { bridge, texts, status } = ctx;
  const tiles = tileSidecar(args);
  addBasemapLayers(map);
  // Empty until applyRender sets its URL: the gold coverage (Raster-Karten)
  // or the metric's kacheln (Raster-Derivate), which change with the metric.
  addGoldCoverageLayer(map, {
    geojson: null,
    ...(args.coverage_fill_opacity === null ? {} : { fillOpacity: args.coverage_fill_opacity }),
  });
  const prozessquelle = addProzessquelleLayer(map, tiles, texts);
  addPixelGridLayer(map);
  const selection = new SelectionLayer(map, args.selected_selection, texts);
  const drawing = wireDrawing(map, selection, (drawn) => {
    sendSelection(bridge, drawn);
  });
  // The ports don't change while the app runs, so the first render's serve.
  const jobs = derivateSidecar(args);
  const box = new LayerBox(
    map,
    (id) => {
      if (id === OVERLAY_ROW) overlays.visibilityChanged();
      if (id === DERIVATE_ROW) derivate.visibilityChanged();
    },
    texts,
  );
  const overlays = new RasterOverlays(map, jobs, texts, status, () => box.rasterStyle(OVERLAY_ROW));
  const derivate = new DerivateLayer(map, jobs, texts, status, () => box.rasterStyle(DERIVATE_ROW));
  return {
    tiles,
    coverage: geojsonSource(map, "gold-coverage"),
    box,
    overlays,
    derivate,
    selection,
    drawing,
    prozessquelle,
    showDerivateError: (err) => {
      console.error("Raster-Derivate request failed", err);
      status.set("error", () => texts.labels.derivate_error);
    },
  };
}

/**
 * The layer-box row of a raster layer: shown while there is a raster, with
 * its opacity slider. `isNew` (a new job, metric or band) ticks the row
 * again: a new raster shows itself, at the opacity the user chose.
 */
function setRasterRow(
  parts: Parts,
  row: { id: string; layer: string; defaultPercent: number },
  shown: boolean,
  isNew: boolean,
  texts: RasterTexts,
): void {
  if (isNew) parts.box.reset(row.id);
  parts.box.set(row.id, {
    label: texts.labels.raster_layer,
    swatch: swatch("legend-dot legend-dot--raster", {}),
    layers: [row.layer],
    visible: true,
    shown,
    opacity: { memoryKey: row.id, defaultPercent: row.defaultPercent },
  });
}

/** Applies what changed in `args` since the last render. */
function applyRender(parts: Parts, applied: Applied, args: RasterArgs, texts: RasterTexts): void {
  const coverage = coverageUrl(parts.tiles, args);
  if (coverage !== applied.coverage) {
    applied.coverage = coverage;
    replaceData(parts.coverage, coverage ?? EMPTY);
  }
  const overlays = overlaysKey(args.raster_overlays);
  const newOverlays = overlays !== applied.overlays;
  const overlayRow = {
    id: OVERLAY_ROW,
    layer: OVERLAY_LAYER,
    defaultPercent: OVERLAY_OPACITY_PERCENT,
  };
  const hasOverlays = Object.keys(args.raster_overlays ?? {}).length > 0;
  setRasterRow(parts, overlayRow, hasOverlays, newOverlays, texts);
  if (newOverlays) {
    applied.overlays = overlays;
    parts.overlays.show(args.raster_overlays, args.active_variable);
  }
  const params = derivateParams(args);
  const derivate = derivateKey(params);
  const newDerivate = derivate !== applied.derivate;
  const derivateRow = {
    id: DERIVATE_ROW,
    layer: DERIVATE_LAYER,
    defaultPercent: DERIVATE_OPACITY_PERCENT,
  };
  setRasterRow(parts, derivateRow, params !== null, newDerivate, texts);
  if (newDerivate) {
    applied.derivate = derivate;
    parts.derivate.set(params);
    // The legend and tooltip belong to the rasters when there are any.
    if (!params && !parts.overlays.active) {
      hideLegend();
      hideTooltip();
    }
  }
  // Python's selection: an upload, or the echo of a drawn one (a no-op).
  parts.selection.show(args.selected_selection, true);
}

/** Builds the map from the first render args; returns the handler for every render. */
export function initRasterMap(
  first: RasterArgs,
  bridge: StreamlitBridge,
): (args: RasterArgs) => void {
  const texts = pageTexts(RASTER_LABELS, first);
  const map = createMap(first, texts);
  const status = initChrome(map, texts, {
    onSearch: (east, north) => {
      const { lat, lon } = toWgs(east, north);
      map.flyTo({ center: [lon, lat], zoom: SEARCH_ZOOM, speed: 1.4 });
    },
    onCanton: () => {
      const canton = CANTON_BERN_VIEW;
      map.flyTo({ center: [canton.lon, canton.lat], zoom: canton.zoom, speed: 1.4 });
    },
  });

  let latest = first;
  let parts: Parts | null = null;
  const applied: Applied = {};
  map.on("load", () => {
    parts = addLayers(map, first, { bridge, texts, status });
    wireClicks(map, parts);
    applyRender(parts, applied, latest, texts);
  });

  return (args) => {
    texts.update(args);
    latest = args;
    if (parts) applyRender(parts, applied, args, texts);
  };
}
