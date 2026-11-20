// The IFK map: click a gold pixel to compute its IFK, see the anrisse that
// reach it as coloured circles, and open one of them. Or draw an area
// (rectangle or polygon) for the IFK of the area; its popup, also opened by a
// click inside it, computes it, and its anrisse show as one outline.

import * as maplibregl from "maplibre-gl";
import type { MapGeoJSONFeature, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";

import {
  type AnrissLegend,
  type ComputeAreaValue,
  type ComputeIfkValue,
  IFK_LABELS,
  type IfkArgs,
  type Pixel,
} from "@/overview_ifk/args";
import { addIfkLayers, CIRCLE_LAYERS, type IfkSources } from "@/overview_ifk/layers";
import { type Drawing, wireDrawing } from "@/shared/drawing";
import { EMPTY, replaceData } from "@/shared/geojson-source";
import { GRID_MIN_ZOOM, pixelSquare } from "@/shared/pixel-grid";
import { areaFilter, initialAreas } from "@/shared/anriss-areas";
import { buildAreaLegend } from "@/shared/area-legend";
import { escapeHtml } from "@/shared/escape";
import { fromWgs, snapToPixel, toWgs } from "@/shared/lv95";
import { maplibreLocale } from "@/shared/maplibre-locale";
import { formatNumber } from "@/shared/number-format";
import { selectionReadout } from "@/shared/pixel-footprint";
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
import { prefetchAnriss, prefetchIfk } from "@/shared/prefetch";
import { SELECTION_FILL_LAYER, SelectionLayer } from "@/shared/selection";
import { ringBounds } from "@/shared/selection-geometry";
import type { StreamlitBridge } from "@/shared/streamlit-bridge";
import { TextPopup } from "@/shared/text-popup";
import { fill, type TextSource } from "@/shared/texts";
import type { MapView, OpenAnrissValue, Selection, SelectionValue } from "@/shared/types";
import { coverageUrl, type Sidecar, tileSidecar } from "@/shared/urls";

type IfkTexts = TextSource<(typeof IFK_LABELS)[number]>;

/** The circles' property that holds the Anrissfläche. */
const AREA_PROPERTY = "anrissflaeche";

const DEFAULT_ZOOM = 9;
const MIN_ZOOM = 7;
const MAX_ZOOM = 21;
const SELECTED_PIXEL_ZOOM = 18;
const SELECTED_AREA_ZOOM = 15;
// Reads as "30 m" on the scale bar, and shows the pixel grid right away.
const SEARCH_ZOOM = 17.1;

/**
 * Names this map in app/ifk_prefetch.py. randomUUID needs a secure context
 * (https, localhost); plain http on a LAN address falls back to Math.random.
 */
function newClientId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function element(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`overview_ifk: #${id} is missing from index.html`);
  return el;
}

function currentView(map: MapLibreMap): MapView {
  const { lat, lng } = map.getCenter();
  return { lat, lon: lng, zoom: map.getZoom() };
}

function nonce(): number {
  return Date.now() + Math.random();
}

function applyAreaFilter(map: MapLibreMap, active: ReadonlySet<number>): void {
  const filter = areaFilter(active, AREA_PROPERTY);
  for (const id of CIRCLE_LAYERS) map.setFilter(id, filter);
}

/** Shows the circles' colour scale, or hides it for null (no pixel, or no anrisse). */
function showAnrissLegend(legend: AnrissLegend | null): void {
  const box = element("anriss-legend");
  if (!legend) {
    box.hidden = true;
    return;
  }
  element("al-bar").style.background = `linear-gradient(to right, ${legend.gradient})`;
  element("al-min").textContent = legend.vmin_label;
  element("al-mid").textContent = legend.vmid_label;
  element("al-max").textContent = legend.vmax_label;
  box.hidden = false;
}

/** `template` filled with `values`, escaped for popup HTML. */
function htmlText(template: string, values: Readonly<Record<string, string | number>> = {}) {
  return escapeHtml(fill(template, values));
}

function anrissPopupHtml(props: MapGeoJSONFeature["properties"], texts: IfkTexts): string {
  const { labels, locale } = texts;
  const id = props.id_anriss as number;
  const area = formatNumber(Number(props.anrissflaeche), locale);
  const rate = formatNumber(Number(props.lambda_ereignis_sum), locale, { digits: 3 });
  return (
    `<b>${htmlText(labels.anriss_popup_title, { id })}</b><br>` +
    `${htmlText(labels.anriss_popup_area, { area })}<br>` +
    htmlText(labels.anriss_popup_rate, { rate }) +
    `<button type="button" class="popup-open-btn" data-anriss-id="${escapeHtml(id)}">` +
    `${htmlText(labels.anriss_open)}</button>`
  );
}

function pixelPopupHtml([x, y]: Pixel, texts: IfkTexts): string {
  const { labels, locale } = texts;
  const coords = {
    x: formatNumber(x, locale, { digits: 1, group: false }),
    y: formatNumber(y, locale, { digits: 1, group: false }),
  };
  return (
    `<b>${htmlText(labels.pixel_popup_title)}</b><br>` +
    htmlText(labels.pixel_popup_coords, coords) +
    `<button type="button" class="popup-open-btn" data-x="${String(x)}" data-y="${String(y)}">` +
    `${htmlText(labels.ifk_compute)}</button>`
  );
}

/**
 * The area popup: its HTML reads the state, so a rerun can update it in place.
 * One `html` function, so TextPopup.showing tells this popup from the others.
 */
interface AreaPopup {
  readonly html: () => string;
  /** Python's area_too_large; false for a fresh drawing until Python has checked it. */
  tooLarge: boolean;
}

function areaPopupHtml(selection: Selection | null, tooLarge: boolean, texts: IfkTexts): string {
  if (!selection) return "";
  const { labels } = texts;
  return (
    `<b>${htmlText(labels.area_popup_title)}</b><br>` +
    escapeHtml(selectionReadout(selection, texts)) +
    (tooLarge ? `<br>${htmlText(labels.area_popup_too_large)}` : "") +
    `<button type="button" class="popup-open-btn" data-area${tooLarge ? " disabled" : ""}>` +
    `${htmlText(labels.ifk_compute)}</button>`
  );
}

/** The area's northernmost corner, where its popup opens after drawing: on the outline, whatever the shape. */
function topCorner(selection: Selection): [number, number] {
  const [e, n] = selection.ring.reduce((top, point) => (point[1] > top[1] ? point : top));
  const { lon, lat } = toWgs(e, n);
  return [lon, lat];
}

/** An area shows one outline of its anrisse and no circles, so the class filter has nothing to filter. */
function showAnrissOutline(sources: IfkSources, outline: IfkArgs["anriss_outline_geojson"]): void {
  replaceData(sources.outline, outline ?? EMPTY);
  element("anriss-outline-row").hidden = !outline;
  element("anriss-area-box").hidden = Boolean(outline);
}

interface ClickContext {
  map: MapLibreMap;
  texts: IfkTexts;
  drawing: Drawing;
  selection: SelectionLayer;
  area: AreaPopup;
  tiles: Sidecar;
  sources: IfkSources;
  prozessquelle: ProzessquelleLayer;
  active: ReadonlySet<number>;
  bridge: StreamlitBridge;
  clientId: string;
}

function selectPixel(ctx: ClickContext, popups: TextPopup, e: MapMouseEvent): void {
  const { E, N } = fromWgs(e.lngLat.lat, e.lngLat.lng);
  const pixel: Pixel = [snapToPixel(E), snapToPixel(N)];
  replaceData(ctx.sources.selected, pixelSquare(pixel));
  // A new pixel replaces the square of the one "Pixel abwählen" cleared.
  replaceData(ctx.sources.deselected, EMPTY);
  const { lat, lon } = toWgs(...pixel);
  popups.show([lon, lat], () => pixelPopupHtml(pixel, ctx.texts));
  prefetchIfk(ctx.tiles, pixel[0], pixel[1], ctx.clientId);
}

/**
 * One click handler for the whole map, not one per layer: MapLibre fires every
 * layer handler under the click, so the order is decided here. An anriss
 * circle wins, then a visible Prozessquelle, then the selected area (its
 * popup: a pixel inside the area would read as part of it), then the pixel
 * under the click.
 * Below GRID_MIN_ZOOM a click covers many pixels and the grid isn't shown, so
 * it zooms in instead of picking one. Not while drawing: the click is a vertex
 * then.
 */
function wireMapClicks(ctx: ClickContext, popups: TextPopup): void {
  const { map } = ctx;
  map.on("click", (e: MapMouseEvent) => {
    if (ctx.drawing.active) return;
    const [anriss] = map.queryRenderedFeatures(e.point, { layers: ["anriss-circles-fill"] });
    if (anriss) {
      popups.show(e.lngLat, () => anrissPopupHtml(anriss.properties, ctx.texts));
      prefetchAnriss(ctx.tiles, anriss.properties.id_anriss as number);
      return;
    }
    if (ctx.prozessquelle.tryHandleClick(e)) return;
    if (map.queryRenderedFeatures(e.point, { layers: [SELECTION_FILL_LAYER] }).length) {
      popups.show(e.lngLat, ctx.area.html);
      return;
    }
    if (map.getZoom() < GRID_MIN_ZOOM) {
      map.flyTo({ center: e.lngLat, zoom: GRID_MIN_ZOOM, speed: 1.2 });
      return;
    }
    selectPixel(ctx, popups, e);
  });
  for (const layer of ["anriss-circles-fill", "gold-coverage-fill"]) {
    map.on("mouseenter", layer, () => {
      setCanvasCursor(map, "pointer");
    });
    map.on("mouseleave", layer, () => {
      setCanvasCursor(map, null);
    });
  }
}

/** The popups' buttons are HTML, so their clicks are caught on the container. */
function wirePopupButtons(ctx: ClickContext, popups: TextPopup): void {
  ctx.map.getContainer().addEventListener("click", (e) => {
    const btn = e.target;
    if (!(btn instanceof HTMLElement) || !btn.classList.contains("popup-open-btn")) return;
    popups.close();
    const area = ctx.selection.current;
    if (btn.dataset.area !== undefined) {
      if (!area) return;
      const value: ComputeAreaValue = { selection: area, compute: true, nonce: nonce() };
      ctx.bridge.setComponentValue(value);
      return;
    }
    const view = currentView(ctx.map);
    const { anrissId, x, y } = btn.dataset;
    if (anrissId !== undefined) {
      const value: OpenAnrissValue = {
        id_anriss: Number.parseInt(anrissId, 10),
        nonce: nonce(),
        view,
        active_areas: [...ctx.active],
      };
      ctx.bridge.setComponentValue(value);
      return;
    }
    const value: ComputeIfkValue = {
      x: Number.parseFloat(x ?? ""),
      y: Number.parseFloat(y ?? ""),
      nonce: nonce(),
      view,
      prefetch_client: ctx.clientId,
    };
    ctx.bridge.setComponentValue(value);
  });
}

/** Where the map opens: on the selected pixel, else on the selected area, else at the given view. */
function initialView(args: IfkArgs): { lat: number; lon: number; zoom: number } {
  if (args.selected_pixel) return { ...toWgs(...args.selected_pixel), zoom: SELECTED_PIXEL_ZOOM };
  if (args.selected_selection) {
    const bounds = ringBounds(args.selected_selection.ring);
    const centre = toWgs((bounds.xmin + bounds.xmax) / 2, (bounds.ymin + bounds.ymax) / 2);
    return { ...centre, zoom: SELECTED_AREA_ZOOM };
  }
  return {
    lat: args.center_lat,
    lon: args.center_lon,
    zoom: args.initial_zoom ?? DEFAULT_ZOOM,
  };
}

/** A drawn area, or null for "Löschen". */
function sendSelection(bridge: StreamlitBridge, selection: Selection | null): void {
  const value: SelectionValue = { selection, nonce: nonce() };
  bridge.setComponentValue(value);
}

function createMap(args: IfkArgs, texts: IfkTexts): MapLibreMap {
  const view = initialView(args);
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

/** What a rerun updates on the loaded map. */
interface Loaded {
  sources: IfkSources;
  selection: SelectionLayer;
  popups: TextPopup;
  area: AreaPopup;
}

/** Applies a rerun's args to the loaded map. */
function applyRerun({ sources, selection, popups, area }: Loaded, args: IfkArgs): void {
  replaceData(sources.circles, args.anriss_circles_geojson ?? EMPTY);
  showAnrissOutline(sources, args.anriss_outline_geojson);
  // Python's area: an upload or a link (zoomed to), the echo of a drawn one
  // (a no-op), or null once a pixel is picked.
  selection.show(args.selected_selection, true);
  // An open area popup follows: Python's check of a drawn area's limits, or no area.
  area.tooLarge = args.area_too_large;
  if (popups.showing(area.html)) {
    if (args.selected_selection) popups.refresh();
    else popups.close();
  }
  showAnrissLegend(args.anriss_legend);
  // Python changes these on "Pixel abwählen"; after a user's own click they
  // repeat what the map already shows.
  replaceData(sources.selected, pixelSquare(args.selected_pixel));
  replaceData(sources.deselected, pixelSquare(args.highlight_pixel));
}

/**
 * Builds the map from the first render args. Returns the handler for later
 * renders: they carry the circles or outline and the legend, which Python
 * computes a rerun or more after the map was mounted, the pixel squares and
 * the selected area. Renders before the map has loaded are dropped, but for
 * their texts; 'load' uses the first render's args.
 */
export function initIfkMap(args: IfkArgs, bridge: StreamlitBridge): (args: IfkArgs) => void {
  const texts = pageTexts(IFK_LABELS, args);
  const tiles = tileSidecar(args);
  const active = initialAreas(args.initial_active_areas);
  const map = createMap(args, texts);
  let loaded: Loaded | null = null;
  buildAreaLegend({
    rows: element("anriss-area-rows"),
    allNoneButtons: element("anriss-area-all-none"),
    active,
    texts,
    showClassColors: false,
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
    const prozessquelle = addProzessquelleLayer(map, tiles, texts);
    const sources = addIfkLayers(map, {
      outline: args.anriss_outline_geojson,
      circles: args.anriss_circles_geojson,
      highlightId: args.highlight_id_anriss,
      selected: args.selected_pixel,
      deselected: args.highlight_pixel,
    });
    showAnrissLegend(args.anriss_legend);
    showAnrissOutline(sources, args.anriss_outline_geojson);
    applyAreaFilter(map, active);
    const selection = new SelectionLayer(map, args.selected_selection, texts);
    // One popup at a time: opening one closes the other.
    const popups = new TextPopup(map, texts, { closeButton: true, maxWidth: "220px" });
    const area: AreaPopup = {
      html: () => areaPopupHtml(selection.current, area.tooLarge, texts),
      tooLarge: args.area_too_large,
    };
    const drawing = wireDrawing(map, selection, (drawn) => {
      sendSelection(bridge, drawn);
      if (!drawn) {
        popups.close();
        return;
      }
      // Python checks the new area's limits; the rerun updates the popup.
      area.tooLarge = false;
      popups.show(topCorner(drawn), area.html);
    });
    const ctx = {
      map,
      texts,
      drawing,
      selection,
      area,
      tiles,
      sources,
      prozessquelle,
      active,
      bridge,
      clientId: newClientId(),
    };
    wireMapClicks(ctx, popups);
    wirePopupButtons(ctx, popups);
    loaded = { sources, selection, popups, area };
  });

  return (rerunArgs) => {
    texts.update(rerunArgs);
    if (loaded) applyRerun(loaded, rerunArgs);
  };
}
