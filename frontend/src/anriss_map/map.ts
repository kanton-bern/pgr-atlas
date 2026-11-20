// The Anriss view's result map: one scenario's pixels coloured by the chosen
// variable, with the Umhüllende, Anriss and 800m-circle outlines on top.
//
// The map is built from the first render and keeps its view across reruns
// (views/anriss.py keys the component per Anriss). Every render updates the
// cells (only when cells_version changes), the legend, the variable switch
// and the outlines. Renders that arrive before 'load' are kept, and the
// latest is applied on 'load'.

import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap } from "maplibre-gl";

import { ANRISS_LABELS, type AnrissArgs, type VariableValue } from "@/anriss_map/args";
import { showValueLegend, showVariableButtons } from "@/anriss_map/panels";
import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import { LayerBox, swatch } from "@/shared/layer-box";
import { toWgs } from "@/shared/lv95";
import { maplibreLocale } from "@/shared/maplibre-locale";
import {
  ATTRIBUTION,
  addBasemapLayers,
  CANTON_BERN_VIEW,
  glyphsUrl,
  initChrome,
  pageTexts,
} from "@/shared/map-controls";
import { type OutlineOverlay, OutlineOverlays } from "@/shared/outline-overlays";
import type { StreamlitBridge } from "@/shared/streamlit-bridge";
import { fill, type TextSource } from "@/shared/texts";

type AnrissTexts = TextSource<(typeof ANRISS_LABELS)[number]>;

// Search-jump target, as in the folium map this replaced.
const SEARCH_ZOOM = 17;
const CELLS_LAYER = "cells-fill";
const CELLS_SWATCH = "linear-gradient(to right,#440154,#21918c,#fde725)";

interface Parts {
  box: LayerBox;
  overlays: OutlineOverlays;
  /** The cells_version whose cells are on the map; undefined before the first. */
  cellsVersion?: string;
  cellsLabel: string;
}

function createMap(args: AnrissArgs, texts: AnrissTexts): MapLibreMap {
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
  });
  // Debug handle for DevTools; the component tests reach the map through it.
  window.debugMap = map;
  // Streamlit may set the frame height after the canvas took its size.
  new ResizeObserver(() => {
    map.resize();
  }).observe(map.getContainer());
  return map;
}

function outlineSwatch(ov: OutlineOverlay): HTMLElement {
  return swatch("legend-line", {
    borderTopColor: ov.color,
    borderTopStyle: ov.dash ? "dashed" : "solid",
  });
}

function wireHover(map: MapLibreMap, parts: Parts, texts: AnrissTexts): void {
  const hover = new maplibregl.Popup({
    closeButton: false,
    closeOnClick: false,
    className: "cell-tooltip",
    offset: 12,
  });
  map.on("mousemove", CELLS_LAYER, (e) => {
    const value = e.features?.[0]?.properties.value_label as string | undefined;
    if (value === undefined) return;
    const text = document.createElement("div");
    text.textContent = fill(texts.labels.cell_value, { label: parts.cellsLabel, value });
    hover.setLngLat(e.lngLat).setDOMContent(text).addTo(map);
  });
  map.on("mouseleave", CELLS_LAYER, () => {
    hover.remove();
  });
}

function addLayers(map: MapLibreMap): Parts {
  addBasemapLayers(map);
  map.addSource("cells", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: CELLS_LAYER,
    type: "fill",
    source: "cells",
    // No antialiasing: with it, the edges between neighbouring 5 m squares
    // show as faint seams at this opacity.
    paint: { "fill-color": ["get", "fillColor"], "fill-opacity": 0.7, "fill-antialias": false },
  });
  const box = new LayerBox(map);
  return { box, overlays: new OutlineOverlays(map, box, outlineSwatch), cellsLabel: "" };
}

function applyRender(map: MapLibreMap, parts: Parts, args: AnrissArgs, bridge: StreamlitBridge) {
  if (args.cells_version !== parts.cellsVersion) {
    replaceData(geojsonSource(map, "cells"), args.cells_geojson ?? EMPTY);
    parts.cellsVersion = args.cells_version;
  }
  parts.cellsLabel = args.cells_label;
  // The cells row first, above the outline rows.
  parts.box.set("cells", {
    label: args.cells_label,
    swatch: swatch("legend-dot", { background: CELLS_SWATCH }),
    layers: [CELLS_LAYER],
    visible: true,
    shown: true,
  });
  showValueLegend(args.legend);
  showVariableButtons(args.variables, args.active_variable, (variable) => {
    const value: VariableValue = { variable };
    bridge.setComponentValue(value);
  });
  parts.overlays.show(args.overlays);
}

/** Builds the map from the first render args; returns the handler for every render. */
export function initAnrissMap(
  first: AnrissArgs,
  bridge: StreamlitBridge,
): (args: AnrissArgs) => void {
  const texts = pageTexts(ANRISS_LABELS, first);
  const map = createMap(first, texts);
  initChrome(map, texts, {
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
  map.on("load", () => {
    parts = addLayers(map);
    wireHover(map, parts, texts);
    applyRender(map, parts, latest, bridge);
  });

  return (args) => {
    texts.update(args);
    latest = args;
    if (parts) applyRender(map, parts, args, bridge);
  };
}
