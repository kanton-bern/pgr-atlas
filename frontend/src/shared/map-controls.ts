// Map chrome shared by the MapLibre components: the control column (zoom,
// "Zoom Kanton Bern", coordinate search, basemaps), zoom readout, the
// Berechnete Kacheln (gold coverage) and Prozessquellen layers, and the map status line.
//
// Scope: chrome and pure utilities only. View-specific interaction (pixel
// selection, drawing, and the click priority between overlapping layers)
// stays in each component, because those rules differ per view and have
// caused subtle bugs when shared.

import * as maplibregl from "maplibre-gl";
import type { Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";

import { escapeHtml } from "./escape";
import { bindMapLibreLocale, MAPLIBRE_LABELS } from "./maplibre-locale";
import { formatNumber } from "./number-format";
import { PopoverGroup } from "./popover";
import { setPressed } from "./pressed";
import { type SearchError, searchInputError } from "./search-input";
import { TextPopup } from "./text-popup";
import { bindDataTexts, fill, labelOf, type TextArgs, type TextSource, UiTexts } from "./texts";
import { pmtilesUrl, type Sidecar } from "./urls";

/** The labels the chrome shows, MapLibre's own strings included. */
export const CHROME_LABELS = [
  ...MAPLIBRE_LABELS,
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
] as const;
export type ChromeLabelKey = (typeof CHROME_LABELS)[number];
type ChromeTexts = TextSource<ChromeLabelKey>;

/** The labels of the Prozessquellen layer (addProzessquelleLayer). */
export const PROZESSQUELLE_LABELS = ["prozessquelle_popup"] as const;

/**
 * MapLibre rejects a text layer without a glyphs URL. The glyphs ship with each
 * component (frontend/public/glyphs/, copied into its dist/), so the browser
 * loads none from another server. Only LABEL_FONT's range 0-255 is there: the
 * labels are numbers. MapLibre wants an absolute URL, hence the page's own.
 */
export function glyphsUrl(): string {
  return `${new URL(".", window.location.href).href}glyphs/{fontstack}/{range}.pbf`;
}

/**
 * The pointer over the map: "pointer" or "crosshair" over something clickable,
 * null for MapLibre's own (grab). A class on the canvas, styled in
 * map-controls.css.
 */
export function setCanvasCursor(map: MapLibreMap, cursor: "pointer" | "crosshair" | null): void {
  const classes = map.getCanvas().classList;
  classes.toggle("mc-cursor-pointer", cursor === "pointer");
  classes.toggle("mc-cursor-crosshair", cursor === "crosshair");
}

/** The one font the label layers may use: the folder name under glyphs/. */
const LABEL_FONT = "roboto-regular";

/**
 * Every map's attributionControl option: the basemap's copyright written
 * out. MapLibre's default folds it into an (i) button on a narrow map.
 */
export const ATTRIBUTION = { compact: false } as const;

/** The fixed whole-canton view behind "Zoom Kanton Bern". */
export const CANTON_BERN_VIEW = { lat: 46.8, lon: 7.5, zoom: 8 } as const;

// ── Chrome state shared across views ───────────────────────────────────────
// Each view is its own iframe, remounted on every view switch. The basemap and
// the two layer toggles live on window.top (every map iframe is a same-origin
// child of the one Streamlit page), so they survive the switch but not a page
// reload, like the rest of the app's state.

type BasemapId = "lk" | "relief" | "osm";

interface ChromeState {
  basemap: BasemapId;
  goldVisible: boolean;
  prozessquelleVisible: boolean;
}

declare global {
  interface Window {
    __probeMapChromeState?: ChromeState;
  }
}

function chromeState(): ChromeState {
  const top = window.top ?? window;
  top.__probeMapChromeState ??= { basemap: "lk", goldVisible: true, prozessquelleVisible: false };
  return top.__probeMapChromeState;
}

function setChromeState(patch: Partial<ChromeState>): void {
  Object.assign(chromeState(), patch);
}

// ── Collapsible boxes ───────────────────────────────────────────────────────
// A .legend-close button collapses the box named by its data-close-target to a
// "<label> ▸" chip in the same place; the chip opens it again (<label> is the
// label its data-open-label names, else "legend"). Collapsing is a
// class (.mc-collapsed), not style.display, because the views show and hide
// their data legends through style.display: a legend the view hides stays
// hidden, and one the user collapsed stays collapsed when the view shows it.
// Both are <button>s, so a keyboard reaches them; keyboard focus moves from
// the one that disappears to the one that takes its place.

function makeCollapsible(target: HTMLElement | null, btn: HTMLElement, texts: ChromeTexts): void {
  if (!target || btn.dataset.wired) return;
  btn.dataset.wired = "1";
  const chip = document.createElement("button");
  chip.type = "button";
  chip.className = "legend-open";
  target.appendChild(chip);
  texts.bind(() => {
    const { labels } = texts;
    const label = labelOf(texts, btn.dataset.openLabel ?? "legend");
    btn.title = labels.legend_hide;
    btn.setAttribute("aria-label", fill(labels.legend_hide_aria, { label }));
    chip.title = labels.legend_show;
    chip.setAttribute("aria-label", fill(labels.legend_show_aria, { label }));
    chip.textContent = fill(labels.legend_chip, { label });
  });
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const hadFocus = document.activeElement === btn;
    target.classList.add("mc-collapsed");
    if (hadFocus) chip.focus();
  });
  chip.addEventListener("click", (e) => {
    e.stopPropagation();
    const hadFocus = document.activeElement === chip;
    target.classList.remove("mc-collapsed");
    if (hadFocus) btn.focus();
  });
}

/** Wires every .legend-close button in the page. Wiring twice is a no-op. */
function wireLegendCloseButtons(texts: ChromeTexts): void {
  document.querySelectorAll<HTMLElement>(".legend-close").forEach((btn) => {
    makeCollapsible(document.getElementById(btn.dataset.closeTarget ?? ""), btn, texts);
  });
}

/**
 * The component's texts from its first render args, with index.html's static
 * texts (data-text) and the legend close buttons wired to them. `keys` are
 * every label the component takes, the chrome's included.
 */
export function pageTexts<K extends string>(
  keys: readonly (K | ChromeLabelKey)[],
  args: TextArgs,
): UiTexts<K | ChromeLabelKey> {
  const texts = new UiTexts(keys, args);
  bindDataTexts(document, texts);
  wireLegendCloseButtons(texts);
  return texts;
}

// ── Basemaps ────────────────────────────────────────────────────────────────
// swisstopo's WMTS tile cache (pre-rendered, cacheable), not WMS GetMap.
// maxzoom is the deepest level each layer is offered at; MapLibre scales it up
// beyond that.
//
// A basemap is one or more zoom bands, each its own raster layer. Below
// LANDESKARTE_10_MIN_ZOOM the LK basemap is swisstopo's multi-scale national map
// series (pixelkarte), whose tiles switch scale by themselves from an overview
// map through 1:1 Mio. … 1:50'000; from there it is the 1:10'000 Landeskarte,
// a little earlier than pixelkarte itself would reach it (which skips 1:25'000).
// The 1:10'000 map alone would be grey noise when zoomed out.

/** The zoom from which the LK basemap shows the 1:10'000 Landeskarte. */
const LANDESKARTE_10_MIN_ZOOM = 14;

function swisstopoWmts(
  layer: string,
  maxzoom: number,
  format: "png" | "jpeg" = "png",
): maplibregl.RasterSourceSpecification {
  return {
    type: "raster",
    tiles: [`https://wmts.geo.admin.ch/1.0.0/${layer}/default/current/3857/{z}/{x}/{y}.${format}`],
    tileSize: 256,
    maxzoom,
    attribution: "© swisstopo",
  };
}

/** One zoom band of a basemap: shown from minzoom (inclusive) to maxzoom (exclusive). */
interface BasemapBand {
  /** The layer id is `bg-<basemap>` plus this suffix; the source id is `basemap-<basemap>` plus it. */
  idSuffix: string;
  source: maplibregl.RasterSourceSpecification;
  minzoom?: number;
  maxzoom?: number;
}

const BASEMAP_ORDER: readonly BasemapId[] = ["lk", "relief", "osm"];
const BASEMAP_LABELS = {
  lk: "basemap_lk",
  relief: "basemap_relief",
  osm: "basemap_osm",
} as const satisfies Record<BasemapId, ChromeLabelKey>;
const BASEMAPS: Readonly<Record<BasemapId, readonly BasemapBand[]>> = {
  lk: [
    {
      idSuffix: "",
      source: swisstopoWmts("ch.swisstopo.pixelkarte-grau", LANDESKARTE_10_MIN_ZOOM, "jpeg"),
      maxzoom: LANDESKARTE_10_MIN_ZOOM,
    },
    {
      idSuffix: "-10k",
      source: swisstopoWmts("ch.swisstopo.landeskarte-grau-10", 19),
      minzoom: LANDESKARTE_10_MIN_ZOOM,
    },
  ],
  relief: [
    { idSuffix: "", source: swisstopoWmts("ch.swisstopo.swissalti3d-reliefschattierung", 18) },
  ],
  osm: [
    {
      idSuffix: "",
      source: {
        type: "raster",
        tiles: ["a", "b", "c"].map((s) => `https://${s}.tile.openstreetmap.org/{z}/{x}/{y}.png`),
        tileSize: 256,
        maxzoom: 19,
        attribution: "© OpenStreetMap contributors",
      },
    },
  ],
};

/** The layer ids that draw one basemap, smallest scale first. */
function basemapLayerIds(basemap: BasemapId): string[] {
  return BASEMAPS[basemap].map((band) => `bg-${basemap}${band.idSuffix}`);
}

function currentBasemap(): BasemapId {
  const basemap = chromeState().basemap;
  return BASEMAP_ORDER.includes(basemap) ? basemap : "lk";
}

/** Adds every basemap's layers; the basemap in the chrome state is visible. */
export function addBasemapLayers(map: MapLibreMap): void {
  const shown = currentBasemap();
  for (const basemap of BASEMAP_ORDER) {
    for (const band of BASEMAPS[basemap]) {
      const sourceId = `basemap-${basemap}${band.idSuffix}`;
      map.addSource(sourceId, band.source);
      map.addLayer({
        id: `bg-${basemap}${band.idSuffix}`,
        type: "raster",
        source: sourceId,
        ...(band.minzoom === undefined ? {} : { minzoom: band.minzoom }),
        ...(band.maxzoom === undefined ? {} : { maxzoom: band.maxzoom }),
        layout: { visibility: basemap === shown ? "visible" : "none" },
      });
    }
  }
}

/** The ✕ in a popover's title row; initControlColumn wires it to close. */
function popoverCloseHtml(panelId: string): string {
  return `<button type="button" class="mc-popover-close" id="${panelId}-close">✕</button>`;
}

/** A popover panel's group label, title and ✕, now and after a language switch. */
function bindPanelTexts(el: HTMLElement, texts: ChromeTexts, title: "basemap" | "search"): void {
  texts.bind(() => {
    const { labels } = texts;
    el.setAttribute("aria-label", labels[title]);
    child(el, `${el.id}-title`).textContent = labels[title];
    const close = child(el, `${el.id}-close`);
    close.title = labels.close;
    close.setAttribute("aria-label", labels.close);
  });
}

/** The basemap choices: the panel of the control column's basemap popover. */
function basemapPanel(map: MapLibreMap, texts: ChromeTexts): HTMLElement {
  const el = document.createElement("div");
  el.id = "basemap-ctrl";
  el.className = "mc-popover";
  el.setAttribute("role", "group");
  let current = currentBasemap();
  el.innerHTML =
    '<div class="mc-ctrl-title" id="basemap-ctrl-title"></div>' +
    popoverCloseHtml(el.id) +
    BASEMAP_ORDER.map(
      (basemap) =>
        `<button type="button" id="bm-${basemap}" class="bm-btn" data-bm="${basemap}"></button>`,
    ).join("");
  bindPanelTexts(el, texts, "basemap");
  const buttons = [...el.querySelectorAll<HTMLElement>(".bm-btn")];
  texts.bind(() => {
    for (const btn of buttons) {
      const label = texts.labels[BASEMAP_LABELS[btn.dataset.bm as BasemapId]];
      btn.textContent = label;
      // The bold text's width, reserved in map-controls.css.
      btn.dataset.label = label;
    }
  });
  for (const btn of buttons) {
    setPressed(btn, btn.dataset.bm === current);
    btn.addEventListener("click", () => {
      const picked = btn.dataset.bm as BasemapId;
      if (picked === current) return;
      for (const bm of BASEMAP_ORDER) {
        for (const layerId of basemapLayerIds(bm)) {
          map.setLayoutProperty(layerId, "visibility", bm === picked ? "visible" : "none");
        }
      }
      current = picked;
      setChromeState({ basemap: picked });
      for (const b of buttons) setPressed(b, b === btn);
    });
  }
  return el;
}

// ── Zoom readout (bottom left, above the scale bar) ─────────────────────────

function initZoomDebug(map: MapLibreMap, texts: ChromeTexts): void {
  const el = document.createElement("div");
  el.id = "zoom-debug";
  document.body.appendChild(el);
  const update = () => {
    const zoom = formatNumber(map.getZoom(), texts.locale, { digits: 2, group: false });
    el.textContent = fill(texts.labels.zoom_level, { zoom });
  };
  map.on("zoom", update);
  texts.bind(update);
}

// ── Coordinate search (a popover of the control column) ────────────────────

export interface SearchOptions {
  /** Moves the map to an LV95 point; the target zoom differs per view. */
  onSearch: (east: number, north: number) => void;
  /** "Zoom Kanton Bern"; the button is left out without it. */
  onCanton?: () => void;
}

const SEARCH_HTML =
  '<div class="mc-ctrl-title" id="search-ctrl-title"></div>' +
  popoverCloseHtml("search-ctrl") +
  '<div class="search-grid">' +
  '<div class="search-field"><label for="search-x">X</label>' +
  '<input id="search-x" type="number" step="any" placeholder="2600000" aria-label="X (LV95)"></div>' +
  '<div class="search-field"><label for="search-y">Y</label>' +
  '<input id="search-y" type="number" step="any" placeholder="1200000" aria-label="Y (LV95)"></div>' +
  '<button type="button" id="search-go"></button>' +
  "</div>" +
  '<div id="search-error" class="mc-search-error"></div>';

/** The element with `id` in `root`. The markup is this module's own, so a miss is a bug. */
function child(root: HTMLElement, id: string): HTMLElement {
  const found = root.querySelector<HTMLElement>(`#${id}`);
  if (!found) throw new Error(`map-controls: #${id} is missing from its own markup`);
  return found;
}

/** The coordinate search: the panel of the control column's search popover. */
function searchPanel(opts: SearchOptions, texts: ChromeTexts): HTMLElement {
  const el = document.createElement("div");
  el.id = "search-ctrl";
  el.className = "mc-popover";
  el.setAttribute("role", "group");
  el.innerHTML = SEARCH_HTML;
  bindPanelTexts(el, texts, "search");

  const xEl = child(el, "search-x") as HTMLInputElement;
  const yEl = child(el, "search-y") as HTMLInputElement;
  const errEl = child(el, "search-error");
  const go = child(el, "search-go");
  let error: SearchError | null = null;
  const showError = () => {
    errEl.textContent = error ? texts.labels[error] : "";
  };
  texts.bind(() => {
    go.textContent = texts.labels.search_go;
    go.title = texts.labels.search_go_title;
    showError();
  });
  const submit = () => {
    const xRaw = xEl.value.trim();
    const yRaw = yEl.value.trim();
    error = xRaw || yRaw ? searchInputError(xRaw, yRaw) : null;
    showError();
    if (xRaw && yRaw && !error) opts.onSearch(Number.parseFloat(xRaw), Number.parseFloat(yRaw));
  };
  go.addEventListener("click", submit);
  for (const input of [xEl, yEl]) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
  }
  return el;
}

// ── The control column (top right, below the zoom buttons) ─────────────────
// One MapLibre control group, styled like the zoom buttons: "Zoom Kanton
// Bern", then the coordinate search and the basemap choice, which open their
// panel as a popover to the left of the column. The panels sit next to the
// column in MapLibre's corner, not inside its .maplibregl-ctrl: MapLibre's
// control button rules don't reach their buttons, and Tab goes from the
// column's buttons on into an open panel.

const ICON_ATTRS =
  'class="mc-tool-icon" viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" ' +
  'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" ' +
  'stroke-linejoin="round"';
const ICONS = {
  home: `<svg ${ICON_ATTRS}><path d="M3.5 11.5 12 4.5l8.5 7"/><path d="M6 10v9.5h12V10"/></svg>`,
  search: `<svg ${ICON_ATTRS}><circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/></svg>`,
  basemap:
    `<svg ${ICON_ATTRS}><path d="M9 4.5 3.5 6.5v13l5.5-2 6 2 5.5-2v-13l-5.5 2z"/>` +
    '<path d="M9 4.5v13M15 6.5v13"/></svg>',
} as const;

/** The gap between the column and an open panel, in px. */
const POPOVER_GAP = 8;

function toolButton(
  id: string,
  texts: ChromeTexts,
  label: "canton" | "search" | "basemap",
  icon: string,
): HTMLButtonElement {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.id = id;
  btn.innerHTML = icon;
  texts.bind(() => {
    btn.title = texts.labels[label];
    btn.setAttribute("aria-label", texts.labels[label]);
  });
  return btn;
}

/** Puts `panel` to the left of `column`, its top level with `trigger`. */
function placeBeside(panel: HTMLElement, trigger: HTMLElement, column: HTMLElement): void {
  const corner = panel.parentElement;
  if (!corner) return;
  const box = corner.getBoundingClientRect();
  const top = trigger.getBoundingClientRect().top - box.top;
  const right = box.right - column.getBoundingClientRect().left + POPOVER_GAP;
  panel.style.top = `${String(top)}px`;
  panel.style.right = `${String(right)}px`;
}

function initControlColumn(map: MapLibreMap, texts: ChromeTexts, search?: SearchOptions): void {
  const column = document.createElement("div");
  column.id = "map-tools";
  column.className = "maplibregl-ctrl maplibregl-ctrl-group";
  map.addControl(
    {
      onAdd: () => column,
      onRemove: () => {
        column.remove();
      },
    },
    "top-right",
  );
  const onCanton = search?.onCanton;
  if (onCanton) {
    const canton = toolButton("canton-btn", texts, "canton", ICONS.home);
    canton.addEventListener("click", onCanton);
    column.appendChild(canton);
  }

  const popovers = new PopoverGroup(document);
  const addPopover = (trigger: HTMLElement, panel: HTMLElement, focus: () => HTMLElement) => {
    column.appendChild(trigger);
    column.after(panel);
    const place = () => {
      placeBeside(panel, trigger, column);
    };
    const popover = popovers.add({ trigger, panel, place, initialFocus: focus });
    panel.querySelector(".mc-popover-close")?.addEventListener("click", () => {
      popover.close(true);
    });
    window.addEventListener("resize", () => {
      if (popover.isOpen) place();
    });
  };
  if (search) {
    const panel = searchPanel(search, texts);
    const trigger = toolButton("search-toggle", texts, "search", ICONS.search);
    addPopover(trigger, panel, () => child(panel, "search-x"));
  }
  const panel = basemapPanel(map, texts);
  const trigger = toolButton("basemap-toggle", texts, "basemap", ICONS.basemap);
  addPopover(trigger, panel, () => child(panel, `bm-${currentBasemap()}`));
}

// ── Layer toggles ───────────────────────────────────────────────────────────

/** Wires a legend checkbox to layers' visibility, starting from `visible`. */
function wireLayerToggle(
  map: MapLibreMap,
  checkboxId: string,
  layerIds: readonly string[],
  visible: boolean,
  onChange: (visible: boolean) => void,
): void {
  const toggle = document.getElementById(checkboxId) as HTMLInputElement | null;
  if (!toggle) return;
  toggle.checked = visible;
  toggle.addEventListener("change", () => {
    const vis = toggle.checked ? "visible" : "none";
    for (const id of layerIds) map.setLayoutProperty(id, "visibility", vis);
    onChange(toggle.checked);
  });
}

// ── Gold coverage (finalized SIM_SPATIAL kacheln) ───────────────────────────

// The fill fades out from z11 to z13: at street scale it tints the whole
// basemap, and the outline alone shows the coverage.
const COVERAGE_FILL_FADE_START = 11;
const COVERAGE_FILL_FADE_END = 13;

export interface GoldCoverageOptions {
  /** The coverage URL (see urls.coverageUrl), or null for none yet. */
  geojson: string | null;
  /**
   * The fill opacity up to z11, default 0.25. Raster-Derivate passes 0:
   * borders only, its data is an image.
   */
  fillOpacity?: number;
}

export function addGoldCoverageLayer(map: MapLibreMap, opts: GoldCoverageOptions): void {
  const visible = chromeState().goldVisible;
  const visibility = visible ? "visible" : "none";
  map.addSource("gold-coverage", {
    type: "geojson",
    data: opts.geojson ?? { type: "FeatureCollection", features: [] },
  });
  map.addLayer({
    id: "gold-coverage-fill",
    type: "fill",
    source: "gold-coverage",
    layout: { visibility },
    paint: {
      "fill-color": "#D4AF37",
      "fill-opacity": [
        "interpolate",
        ["linear"],
        ["zoom"],
        COVERAGE_FILL_FADE_START,
        opts.fillOpacity ?? 0.25,
        COVERAGE_FILL_FADE_END,
        0,
      ],
    },
  });
  map.addLayer({
    id: "gold-coverage-outline",
    type: "line",
    source: "gold-coverage",
    layout: { visibility },
    paint: { "line-color": "#D4AF37", "line-width": 1.5 },
  });
  wireLayerToggle(
    map,
    "gold-toggle",
    ["gold-coverage-fill", "gold-coverage-outline"],
    visible,
    (goldVisible) => {
      setChromeState({ goldVisible });
    },
  );
}

// ── Prozessquellen (off by default, the same in every view) ─────────────────

const PROZESSQUELLE_LAYERS = [
  "prozessquelle-fill",
  "prozessquelle-outline",
  "prozessquelle-label-text",
] as const;
// Below this, about 5000 canton-wide id_pq labels overlap into noise.
const PROZESSQUELLE_LABEL_MIN_ZOOM = 14;

export interface ProzessquelleLayer {
  /** Opens the popup if the click hit a Prozessquelle; returns whether it did. */
  tryHandleClick(e: MapMouseEvent): boolean;
}

const PROZESSQUELLE_LABEL_BG = "prozessquelle-label-bg";

/** The app's accent colour, from the shared tokens (app/styles/tokens.css). */
function brandColor(): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue("--pgr-brand");
  return value.trim() || "#4E4E4E";
}

/**
 * A rounded rectangle in the accent colour, registered as a stretchable map
 * image: the label layer fits it around each number (icon-text-fit).
 */
function addLabelBackground(map: MapLibreMap): void {
  if (map.hasImage(PROZESSQUELLE_LABEL_BG)) return;
  const size = 32; // device pixels, drawn at pixelRatio 2
  const radius = 8;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return; // no 2D canvas: the labels then show without a background
  ctx.fillStyle = brandColor();
  ctx.beginPath();
  ctx.roundRect(0, 0, size, size, radius);
  ctx.fill();
  map.addImage(PROZESSQUELLE_LABEL_BG, ctx.getImageData(0, 0, size, size), {
    pixelRatio: 2,
    stretchX: [[radius, size - radius]],
    stretchY: [[radius, size - radius]],
    content: [radius / 2, radius / 4, size - radius / 2, size - radius / 4],
  });
}

function addProzessquelleLayers(map: MapLibreMap, visible: boolean): void {
  addLabelBackground(map);
  const common = {
    source: "prozessquelle",
    layout: { visibility: visible ? "visible" : "none" },
  } as const;
  map.addLayer({
    ...common,
    id: "prozessquelle-fill",
    type: "fill",
    "source-layer": "prozessquelle",
    paint: { "fill-color": "#A0785A", "fill-opacity": 0.2 },
  });
  map.addLayer({
    ...common,
    id: "prozessquelle-outline",
    type: "line",
    "source-layer": "prozessquelle",
    paint: { "line-color": "#A0785A", "line-width": 1 },
  });
  map.addLayer({
    ...common,
    id: "prozessquelle-label-text",
    type: "symbol",
    "source-layer": "prozessquelle_labels",
    minzoom: PROZESSQUELLE_LABEL_MIN_ZOOM,
    layout: {
      ...common.layout,
      "text-field": ["to-string", ["get", "id_pq"]],
      "text-font": [LABEL_FONT],
      "text-size": 11,
      "text-allow-overlap": true,
      "text-ignore-placement": true,
      // White numbers on an accent-coloured pill: readable on every basemap.
      "icon-image": PROZESSQUELLE_LABEL_BG,
      "icon-text-fit": "both",
      "icon-text-fit-padding": [1, 4, 1, 4],
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "text-color": "#ffffff" },
  });
}

/**
 * Adds the Prozessquellen tileset, its hover cursor and its legend checkbox.
 * The caller's click handler decides when to call tryHandleClick, because the
 * click priority against other layers differs per view.
 */
export function addProzessquelleLayer(
  map: MapLibreMap,
  tiles: Sidecar,
  texts: TextSource<(typeof PROZESSQUELLE_LABELS)[number]>,
): ProzessquelleLayer {
  const visible = chromeState().prozessquelleVisible;
  map.addSource("prozessquelle", {
    type: "vector",
    url: pmtilesUrl(tiles, "prozessquelle.pmtiles"),
  });
  addProzessquelleLayers(map, visible);
  map.on("mouseenter", "prozessquelle-fill", () => {
    setCanvasCursor(map, "pointer");
  });
  map.on("mouseleave", "prozessquelle-fill", () => {
    setCanvasCursor(map, null);
  });
  wireLayerToggle(map, "prozessquelle-toggle", PROZESSQUELLE_LAYERS, visible, (v) => {
    setChromeState({ prozessquelleVisible: v });
  });

  const popup = new TextPopup(map, texts, { closeButton: true, maxWidth: "160px" });
  return {
    tryHandleClick(e) {
      const [feature] = map.queryRenderedFeatures(e.point, { layers: ["prozessquelle-fill"] });
      if (!feature) return false;
      const id = feature.properties.id_pq as string | number;
      popup.show(e.lngLat, () => {
        return `<b>${escapeHtml(fill(texts.labels.prozessquelle_popup, { id }))}</b>`;
      });
      return true;
    },
  };
}

// ── Map status (top centre) ─────────────────────────────────────────────────

/**
 * The status line: 'loading' or 'error' with a text, or hidden. An error
 * stays until the next call or a click on it, so a failed load doesn't look
 * like "no data here". The line is a button, so a keyboard closes an error
 * too; while loading it is disabled, as there is nothing to close. The text
 * is a function that reads the labels, so a language switch rewrites it.
 */
export class MapStatus {
  private readonly el = document.createElement("button");
  private text: (() => string) | null = null;

  constructor(private readonly texts: TextSource<"close">) {
    this.el.type = "button";
    this.el.id = "map-status";
    this.el.addEventListener("click", () => {
      this.clear();
    });
    document.body.appendChild(this.el);
    this.set(null);
    texts.bind(() => {
      this.render();
    });
  }

  set(kind: "loading" | "error" | null, text: () => string = () => ""): void {
    this.el.className = kind ?? "";
    this.el.disabled = kind !== "error";
    this.text = kind ? text : null;
    this.render();
  }

  clear(): void {
    this.set(null);
  }

  private render(): void {
    this.el.title = this.texts.labels.close;
    this.el.textContent = this.text?.() ?? "";
  }
}

/**
 * Reports data-source errors in the status line. A failed basemap tile shows as
 * a gap in the basemap, but a failed data tile looks the same as an area
 * without data.
 */
function reportSourceErrors(map: MapLibreMap, status: MapStatus, texts: ChromeTexts): void {
  map.on("error", (e) => {
    // MapLibre adds sourceId to the errors that come from a source.
    const { sourceId } = e as maplibregl.ErrorEvent & { sourceId?: string };
    console.error("Map error", sourceId ?? "", e.error);
    if (sourceId && !sourceId.startsWith("basemap-")) {
      status.set("error", () => texts.labels.map_data_error);
    }
  });
}

// ── The unified chrome ──────────────────────────────────────────────────────
// One control column on the right edge: zoom buttons, then "Zoom Kanton
// Bern", coordinate search and basemap choice. Scale and zoom readout bottom
// left. The layer box top left and any data legend belong to the view.

/**
 * Adds the chrome, its texts from `texts`, which it follows on a language
 * switch. Without `search`, the coordinate search is left out. Returns the
 * status line.
 */
export function initChrome(
  map: MapLibreMap,
  texts: ChromeTexts,
  search?: SearchOptions,
): MapStatus {
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  const scale = new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" });
  map.addControl(scale, "bottom-left");
  bindMapLibreLocale(map, scale, texts);
  initZoomDebug(map, texts);
  initControlColumn(map, texts, search);
  const status = new MapStatus(texts);
  reportSourceErrors(map, status, texts);
  return status;
}
