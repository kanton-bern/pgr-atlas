// The Gebäudeschatten map: the canton's affected mask, the buildings, and the
// pixels and footprints of the selected building or pixel.
//
// The map is built from the first render. Every render updates the mask (when
// its settings change), the cells (when cells_version changes), the outlines
// and the layer box, and frames a new focus. Renders that arrive before 'load'
// are kept, and the latest is applied on 'load'.

import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";

import { GEBAEUDESCHATTEN_LABELS, type GebaeudeschattenArgs } from "@/gebaeudeschatten_map/args";
import { clickValue } from "@/gebaeudeschatten_map/clicks";
import { MASK_LAYER, MASK_OPACITY_PERCENT, MaskLayer, maskKey } from "@/gebaeudeschatten_map/mask";
import { fillSwatch, outlineSwatch, showCellsKey, stripes } from "@/gebaeudeschatten_map/panels";
import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import { LayerBox } from "@/shared/layer-box";
import { toWgs } from "@/shared/lv95";
import { maplibreLocale } from "@/shared/maplibre-locale";
import {
  addBasemapLayers,
  ATTRIBUTION,
  CANTON_BERN_VIEW,
  glyphsUrl,
  initChrome,
  type MapStatus,
  pageTexts,
  setCanvasCursor,
} from "@/shared/map-controls";
import { OutlineOverlays } from "@/shared/outline-overlays";
import type { StreamlitBridge } from "@/shared/streamlit-bridge";
import { fill, type TextSource } from "@/shared/texts";
import { pmtilesUrl, tileSidecar } from "@/shared/urls";

type GsTexts = TextSource<(typeof GEBAEUDESCHATTEN_LABELS)[number]>;

const SEARCH_ZOOM = 17;
const FOCUS_MAX_ZOOM = 18;
// The dark outline of every cell, once the 5 m cells are big enough to read.
const CELL_GRID_MIN_ZOOM = 17;
const BUILDINGS_FILL = "buildings-fill";
const CELLS_FILL = "cells-fill";

interface Parts {
  box: LayerBox;
  mask: MaskLayer;
  overlays: OutlineOverlays;
  texts: GsTexts;
}

/** What is on the map, by key; `undefined` for "not applied yet". */
interface Applied {
  mask?: string | null;
  cells?: string;
  focus?: number;
}

function createMap(args: GebaeudeschattenArgs, texts: GsTexts): MapLibreMap {
  const [[latMin, lonMin], [latMax, lonMax]] = args.bounds;
  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, glyphs: glyphsUrl(), sources: {}, layers: [] },
    attributionControl: ATTRIBUTION,
    locale: maplibreLocale(texts.labels),
    bounds: [
      [lonMin, latMin],
      [lonMax, latMax],
    ],
    minZoom: 5,
    maxZoom: 21,
    // Shift-click selects the pixel under a building. Box zoom takes every
    // Shift+mousedown and suppresses the click after it.
    boxZoom: false,
  });
  // Debug handle for DevTools; the component tests reach the map through it.
  window.debugMap = map;
  // Streamlit may set the frame height after the canvas took its size.
  new ResizeObserver(() => {
    map.resize();
  }).observe(map.getContainer());
  return map;
}

function addDataLayers(map: MapLibreMap, args: GebaeudeschattenArgs): void {
  const layer = args.buildings_layer;
  map.addSource("buildings", {
    type: "vector",
    url: pmtilesUrl(tileSidecar(args), args.buildings_pmtiles),
  });
  map.addLayer({
    id: BUILDINGS_FILL,
    type: "fill",
    source: "buildings",
    "source-layer": layer,
    paint: { "fill-color": "#f5a54a", "fill-opacity": 0.12 },
  });
  map.addLayer({
    id: "buildings-line",
    type: "line",
    source: "buildings",
    "source-layer": layer,
    paint: { "line-color": "#f08c1a", "line-width": 1.4 },
  });
  map.addSource("cells", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: CELLS_FILL,
    type: "fill",
    source: "cells",
    paint: {
      "fill-color": ["get", "fillColor"],
      "fill-opacity": ["get", "fillOpacity"],
      "fill-antialias": false,
    },
  });
  map.addLayer({
    id: "cells-line",
    type: "line",
    source: "cells",
    minzoom: CELL_GRID_MIN_ZOOM,
    paint: { "line-color": "#1a1a1a", "line-width": 0.7, "line-opacity": 0.8 },
  });
}

/** The hover text of the cell and the building under `point`, one per line. */
function hoverText(
  map: MapLibreMap,
  point: maplibregl.Point,
  texts: GsTexts,
): { text: string; building: boolean } {
  const cell = map.queryRenderedFeatures(point, { layers: [CELLS_FILL] })[0];
  const bld = map.queryRenderedFeatures(point, { layers: [BUILDINGS_FILL] })[0];
  const lines: string[] = [];
  if (cell) lines.push(String(cell.properties.tooltip));
  if (bld) {
    const { id_start: id, area_m2: area } = bld.properties as { id_start: number; area_m2: number };
    lines.push(fill(texts.labels.building_hover, { id, area }));
  }
  return { text: lines.join("\n"), building: bld !== undefined };
}

function wireHover(map: MapLibreMap, texts: GsTexts): void {
  const hover = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    className: "cell-tooltip",
    offset: 12,
  });
  map.on("mousemove", (e) => {
    const { text, building } = hoverText(map, e.point, texts);
    setCanvasCursor(map, building ? "pointer" : "crosshair");
    if (!text) {
      hover.remove();
      return;
    }
    const div = document.createElement("div");
    div.textContent = text;
    hover.setLngLat(e.lngLat).setDOMContent(div).addTo(map);
  });
  map.on("mouseout", () => {
    hover.remove();
  });
}

function wireClicks(map: MapLibreMap, bridge: StreamlitBridge): void {
  map.on("click", (e) => {
    const bld = map.queryRenderedFeatures(e.point, { layers: [BUILDINGS_FILL] })[0];
    const value = clickValue(
      {
        lat: e.lngLat.lat,
        lon: e.lngLat.lng,
        shift: e.originalEvent.shiftKey,
        building: bld ? Number(bld.properties.id_start) : null,
      },
      Date.now() + Math.random(),
    );
    if (value) bridge.setComponentValue(value);
  });
}

function addLayers(
  map: MapLibreMap,
  args: GebaeudeschattenArgs,
  texts: GsTexts,
  status: MapStatus,
): Parts {
  addBasemapLayers(map);
  addDataLayers(map, args);
  const box = new LayerBox(
    map,
    (id, visible) => {
      if (id === "mask" && visible) mask.refreshSoon();
    },
    texts,
  );
  const mask = new MaskLayer(map, BUILDINGS_FILL, () => box.rasterStyle("mask"), {
    status,
    text: () => texts.labels.mask_error,
  });
  return { box, mask, overlays: new OutlineOverlays(map, box, outlineSwatch), texts };
}

function applyCells(map: MapLibreMap, parts: Parts, applied: Applied, args: GebaeudeschattenArgs) {
  if (args.cells_version !== applied.cells) {
    applied.cells = args.cells_version;
    replaceData(geojsonSource(map, "cells"), args.cells_geojson ?? EMPTY);
  }
  const shown = args.cells_geojson !== null;
  parts.box.set("cells", {
    label: args.cells_label || parts.texts.labels.cells_default,
    swatch: fillSwatch(stripes(args.cells_legend)),
    layers: [CELLS_FILL, "cells-line"],
    visible: true,
    shown,
  });
  showCellsKey(parts.box.element("cells"), args.cells_legend, shown);
}

function applyRender(map: MapLibreMap, parts: Parts, applied: Applied, args: GebaeudeschattenArgs) {
  parts.box.set("mask", {
    label: args.mask?.label ?? parts.texts.labels.mask_default,
    swatch: fillSwatch("rgba(155,111,201,0.45)"),
    layers: [MASK_LAYER],
    visible: true,
    shown: args.mask !== null,
    opacity: { memoryKey: "gebaeudeschatten-mask", defaultPercent: MASK_OPACITY_PERCENT },
  });
  // An unticked mask stays off with new settings (and isn't fetched) until the user ticks it.
  const mask = maskKey(args.mask);
  if (mask !== applied.mask) {
    applied.mask = mask;
    parts.mask.set(args.mask);
  }
  parts.box.set("buildings", {
    label: parts.texts.labels.buildings,
    swatch: fillSwatch("rgba(245,165,74,0.12)", "2px solid #f08c1a"),
    layers: [BUILDINGS_FILL, "buildings-line"],
    visible: true,
    shown: true,
  });
  applyCells(map, parts, applied, args);
  parts.overlays.show(args.overlays);
  if (args.focus && args.focus.nonce !== applied.focus) {
    applied.focus = args.focus.nonce;
    const [[latMin, lonMin], [latMax, lonMax]] = args.focus.bounds;
    map.fitBounds(
      [
        [lonMin, latMin],
        [lonMax, latMax],
      ],
      { padding: 60, maxZoom: FOCUS_MAX_ZOOM, duration: 800 },
    );
  }
}

/** Builds the map from the first render args; returns the handler for every render. */
export function initGebaeudeschattenMap(
  first: GebaeudeschattenArgs,
  bridge: StreamlitBridge,
): (args: GebaeudeschattenArgs) => void {
  const texts = pageTexts(GEBAEUDESCHATTEN_LABELS, first);
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
    parts = addLayers(map, first, texts, status);
    wireHover(map, texts);
    wireClicks(map, bridge);
    applyRender(map, parts, applied, latest);
  });

  return (args) => {
    texts.update(args);
    latest = args;
    if (parts) applyRender(map, parts, applied, args);
  };
}
