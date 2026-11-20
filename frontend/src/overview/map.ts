// The overview map (Simulierte Ereignisse): every anriss as a circle coloured by its area
// class, a popup with "Anriss öffnen", and the shared chrome.

import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, MapGeoJSONFeature, MapMouseEvent } from "maplibre-gl";

import { OVERVIEW_LABELS, type OverviewArgs } from "@/overview/args";
import { AREA_COLOR_EXPR, AREA_PROPERTY, AREA_SORT_KEY } from "@/overview/areas";
import { readSavedView, saveView } from "@/overview/saved-view";
import { areaFilter, initialAreas } from "@/shared/anriss-areas";
import { buildAreaLegend } from "@/shared/area-legend";
import { escapeHtml } from "@/shared/escape";
import { toWgs } from "@/shared/lv95";
import { maplibreLocale } from "@/shared/maplibre-locale";
import {
  addBasemapLayers,
  addGoldCoverageLayer,
  addProzessquelleLayer,
  ATTRIBUTION,
  CANTON_BERN_VIEW,
  glyphsUrl,
  initChrome,
  pageTexts,
  type ProzessquelleLayer,
  setCanvasCursor,
} from "@/shared/map-controls";
import { prefetchAnriss } from "@/shared/prefetch";
import type { StreamlitBridge } from "@/shared/streamlit-bridge";
import { TextPopup } from "@/shared/text-popup";
import { fill, type Labels, type TextSource } from "@/shared/texts";
import type { MapView, OpenAnrissValue } from "@/shared/types";
import { coverageUrl, pmtilesUrl, type Sidecar, tileSidecar } from "@/shared/urls";

type OverviewLabelKey = (typeof OVERVIEW_LABELS)[number];

// The tileset's name and layer vary per build, so Python passes them; these
// are the fallbacks. The layer holds real circle polygons (overview/
// overview_preprocessing.py), drawn at every zoom.
const DEFAULT_PMTILES_FILENAME = "overview_anrisse_maxi_test.pmtiles";
const DEFAULT_SOURCE_LAYER = "anrisse_circles";

const DEFAULT_ZOOM = 8;
// About the whole country on screen; further out the data is a speck.
const MIN_ZOOM = 7;
const MAX_ZOOM = 19;
// Reads as "100 m" on the scale bar: single anriss circles are clear.
const SEARCH_ZOOM = 15.8;

const CIRCLE_LAYERS = ["anrisse-circles-fill", "anrisse-circles-outline"] as const;
const HIGHLIGHT_LAYERS = ["anrisse-circles-highlight-halo", "anrisse-circles-highlight"] as const;

/** Python's viewport if it sent one, else the saved one, else its centre at zoom 8. */
function startView(args: OverviewArgs): MapView {
  if (args.initial_zoom != null) {
    return { lat: args.center_lat, lon: args.center_lon, zoom: args.initial_zoom };
  }
  return readSavedView() ?? { lat: args.center_lat, lon: args.center_lon, zoom: DEFAULT_ZOOM };
}

function currentView(map: MapLibreMap): MapView {
  const { lat, lng } = map.getCenter();
  return { lat, lon: lng, zoom: map.getZoom() };
}

function legendElement(id: string): HTMLElement {
  const element = document.getElementById(id);
  if (!element) throw new Error(`overview: #${id} is missing from index.html`);
  return element;
}

function applyAreaFilter(map: MapLibreMap, active: ReadonlySet<number>): void {
  const filter = areaFilter(active, AREA_PROPERTY);
  for (const id of CIRCLE_LAYERS) map.setFilter(id, filter);
}

function addCoverageTooltip(map: MapLibreMap): void {
  const tooltip = new maplibregl.Popup({ closeButton: false, closeOnClick: false });
  map.on("mousemove", "gold-coverage-fill", (e) => {
    setCanvasCursor(map, "pointer");
    const region = e.features?.[0]?.properties.region as string | undefined;
    tooltip
      .setLngLat(e.lngLat)
      .setHTML(`<b>${escapeHtml(region ?? "")}</b>`)
      .addTo(map);
  });
  map.on("mouseleave", "gold-coverage-fill", () => {
    setCanvasCursor(map, null);
    tooltip.remove();
  });
}

/** Matches the highlighted anriss, or nothing when there is none. */
function highlightFilter(highlightId: number | null): maplibregl.FilterSpecification {
  return highlightId == null ? ["boolean", false] : ["==", ["get", "id_anriss"], highlightId];
}

function applyHighlight(map: MapLibreMap, highlightId: number | null): void {
  const filter = highlightFilter(highlightId);
  for (const id of HIGHLIGHT_LAYERS) map.setFilter(id, filter);
}

function addAnrissLayers(map: MapLibreMap, sourceLayer: string, highlightId: number | null): void {
  const common = { source: "anrisse", "source-layer": sourceLayer } as const;
  map.addLayer({
    ...common,
    id: "anrisse-circles-fill",
    type: "fill",
    layout: { "fill-sort-key": AREA_SORT_KEY },
    paint: { "fill-color": AREA_COLOR_EXPR, "fill-opacity": 0.6 },
  });
  map.addLayer({
    ...common,
    id: "anrisse-circles-outline",
    type: "line",
    layout: { "line-sort-key": AREA_SORT_KEY },
    paint: {
      "line-color": "#000000",
      "line-width": ["interpolate", ["linear"], ["zoom"], 13, 0.5, 15, 1],
      "line-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 15, 0.8],
    },
  });
  // "You were just here": a ring around the anriss that was open last. The
  // area filter doesn't apply, so it shows even when its class is off. The
  // layers always exist, so a rerun only changes their filter.
  const filter = highlightFilter(highlightId);
  map.addLayer({
    ...common,
    id: "anrisse-circles-highlight-halo",
    type: "line",
    filter,
    paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.9 },
  });
  map.addLayer({
    ...common,
    id: "anrisse-circles-highlight",
    type: "line",
    filter,
    paint: { "line-color": "#2979ff", "line-width": 3, "line-opacity": 1 },
  });
}

function anrissPopupHtml(
  props: MapGeoJSONFeature["properties"],
  labels: Labels<OverviewLabelKey>,
): string {
  const id = props.id_anriss as number;
  const line = (template: string, values: Record<string, string | number>) =>
    escapeHtml(fill(template, values));
  return (
    `<b>${line(labels.anriss_popup_title, { id })}</b><br>` +
    `${line(labels.anriss_popup_area, { area: props.A as number })}<br>` +
    line(labels.anriss_popup_prozessquelle, { id: props.id_prozessquelle as number }) +
    `<button type="button" class="popup-open-btn" data-id="${escapeHtml(id)}">` +
    `${escapeHtml(labels.anriss_open)}</button>`
  );
}

interface ClickContext {
  map: MapLibreMap;
  texts: TextSource<OverviewLabelKey>;
  tiles: Sidecar;
  prozessquelle: ProzessquelleLayer;
  active: ReadonlySet<number>;
  bridge: StreamlitBridge;
}

/**
 * One click handler for the whole map, not one per layer: an anriss circle wins
 * over the Prozessquelle under it, and two layer handlers would both fire.
 */
function wireClicks(ctx: ClickContext): void {
  const { map, texts } = ctx;
  const popup = new TextPopup(map, texts, { closeButton: true, maxWidth: "200px" });
  map.on("click", (e: MapMouseEvent) => {
    const [anriss] = map.queryRenderedFeatures(e.point, { layers: ["anrisse-circles-fill"] });
    if (!anriss) {
      ctx.prozessquelle.tryHandleClick(e);
      return;
    }
    popup.show(e.lngLat, () => anrissPopupHtml(anriss.properties, texts.labels));
    prefetchAnriss(ctx.tiles, anriss.properties.id_anriss as number);
  });
  map.on("mouseenter", "anrisse-circles-fill", () => {
    setCanvasCursor(map, "pointer");
  });
  map.on("mouseleave", "anrisse-circles-fill", () => {
    setCanvasCursor(map, null);
  });

  // The popup's button is HTML, so its click is caught on the container.
  map.getContainer().addEventListener("click", (e) => {
    const btn = e.target;
    if (!(btn instanceof HTMLElement) || !btn.classList.contains("popup-open-btn")) return;
    popup.close();
    const value: OpenAnrissValue = {
      id_anriss: Number.parseInt(btn.dataset.id ?? "", 10),
      nonce: Date.now() + Math.random(),
      view: currentView(map),
      active_areas: [...ctx.active],
    };
    ctx.bridge.setComponentValue(value);
  });
}

function createMap(args: OverviewArgs, texts: TextSource<OverviewLabelKey>): MapLibreMap {
  const view = startView(args);
  const map = new maplibregl.Map({
    container: "map",
    style: { version: 8, glyphs: glyphsUrl(), sources: {}, layers: [] },
    attributionControl: ATTRIBUTION,
    locale: maplibreLocale(texts.labels),
    center: [view.lon, view.lat],
    zoom: view.zoom,
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

/**
 * Builds the map from the first render args. Returns the handler for later
 * renders, which applies only `highlight_id_anriss` and the texts: the other
 * args are start values the user changes on the map. A render before 'load'
 * is applied on load.
 */
export function initOverviewMap(
  args: OverviewArgs,
  bridge: StreamlitBridge,
): (args: OverviewArgs) => void {
  const texts = pageTexts(OVERVIEW_LABELS, args);
  const tiles = tileSidecar(args);
  const active = initialAreas(args.initial_active_areas);
  const map = createMap(args, texts);
  let loaded = false;
  let highlightId = args.highlight_id_anriss;
  buildAreaLegend({
    rows: legendElement("area-rows"),
    allNoneButtons: legendElement("area-all-none"),
    active,
    texts,
    showClassColors: true,
    onChange: () => {
      if (loaded) applyAreaFilter(map, active);
    },
  });
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

  map.on("load", () => {
    addBasemapLayers(map);
    addGoldCoverageLayer(map, { geojson: coverageUrl(tiles, args) });
    addCoverageTooltip(map);
    // Added before the anriss source, so it draws below the circles.
    const prozessquelle = addProzessquelleLayer(map, tiles, texts);
    map.addSource("anrisse", {
      type: "vector",
      url: pmtilesUrl(tiles, args.pmtiles_filename ?? DEFAULT_PMTILES_FILENAME),
    });
    addAnrissLayers(map, args.source_layer ?? DEFAULT_SOURCE_LAYER, highlightId);
    loaded = true;
    applyAreaFilter(map, active);
    map.on("moveend", () => {
      saveView(currentView(map));
    });
    wireClicks({ map, texts, tiles, prozessquelle, active, bridge });
  });

  return (rerunArgs) => {
    texts.update(rerunArgs);
    if (rerunArgs.highlight_id_anriss === highlightId) return;
    highlightId = rerunArgs.highlight_id_anriss;
    if (loaded) applyHighlight(map, highlightId);
  };
}
