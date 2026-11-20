// The selection on the map: its outline, the size readout and "Löschen".
// Both a drawn and an uploaded selection end up here; an uploaded one comes
// from Python on a rerun, with no gesture in this component. It is drawn
// along the edges of the pixels it takes (pixel-footprint.ts), not as the
// ring itself, which runs through pixel centres.

import type { Map as MapLibreMap } from "maplibre-gl";

import type { Selection } from "@/shared/types";
import { type Footprint, pixelFootprint, selectionReadout } from "@/shared/pixel-footprint";
import {
  type Bounds,
  READOUT_LABELS,
  rectRing,
  ringBounds,
  selectionKey,
} from "@/shared/selection-geometry";
import type { TextSource } from "@/shared/texts";
import { SELECTION_CASING_COLOR, SELECTION_COLOR } from "@/shared/selection-color";
import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import { snapToPixel, toWgs } from "@/shared/lv95";
import type { Lv95Point } from "@/shared/types";
import type { FeatureCollection, LineString, Polygon } from "geojson";

const FILL_SOURCE = "draw-bbox";
/** The selection's fill layer: a click inside the selection hits it. */
export const SELECTION_FILL_LAYER = "draw-bbox-fill";
const LINE_SOURCE = "draw-bbox-line";

function element(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from index.html`);
  return el;
}

function lonLat(ring: readonly Lv95Point[]): number[][] {
  return ring.map(([e, n]) => {
    const { lon, lat } = toWgs(e, n);
    return [lon, lat];
  });
}

function polygons(rings: readonly (readonly Lv95Point[])[]): FeatureCollection<Polygon> {
  return {
    type: "FeatureCollection",
    features: rings.map((ring) => ({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [lonLat(ring)] },
    })),
  };
}

function lines(rings: readonly (readonly Lv95Point[])[]): FeatureCollection<LineString> {
  return {
    type: "FeatureCollection",
    features: rings.map((ring) => ({
      type: "Feature",
      properties: {},
      geometry: { type: "LineString", coordinates: lonLat(ring) },
    })),
  };
}

/** Fill and outline of `selection`; its own ring if it takes no pixel. */
function shapes(selection: Selection | null): { fill: FeatureCollection; line: FeatureCollection } {
  if (!selection) return { fill: EMPTY, line: EMPTY };
  const footprint: Footprint | null = pixelFootprint(selection);
  if (!footprint) return { fill: polygons([selection.ring]), line: lines([selection.ring]) };
  return { fill: polygons(footprint.rects.map(rectRing)), line: lines(footprint.rings) };
}

/** The labels of the selection's readout and of the drawing buttons (index.html). */
export const SELECTION_LABELS = [
  ...READOUT_LABELS,
  "draw_rect",
  "draw_polygon",
  "draw_clear",
] as const;

export class SelectionLayer {
  // The selection on screen. `undefined`: none applied yet, so the next one
  // is applied even if it is null.
  private key: string | null | undefined = undefined;
  // What the readout measures: the selection, or the rectangle being dragged.
  private measured: Selection | null = null;
  // The selection on screen (show's last), not a dragged preview.
  private shown: Selection | null = null;

  constructor(
    private readonly map: MapLibreMap,
    initial: Selection | null,
    private readonly texts: TextSource<(typeof SELECTION_LABELS)[number]>,
  ) {
    const { fill, line } = shapes(initial);
    map.addSource(FILL_SOURCE, { type: "geojson", data: fill });
    map.addSource(LINE_SOURCE, { type: "geojson", data: line });
    // No antialiasing: it would draw seams between the fill's pixel rows.
    map.addLayer({
      id: SELECTION_FILL_LAYER,
      type: "fill",
      source: FILL_SOURCE,
      paint: { "fill-color": SELECTION_COLOR, "fill-opacity": 0.06, "fill-antialias": false },
    });
    map.addLayer({
      id: "draw-bbox-casing",
      type: "line",
      source: LINE_SOURCE,
      paint: { "line-color": SELECTION_CASING_COLOR, "line-width": 3, "line-opacity": 0.6 },
    });
    map.addLayer({
      id: "draw-bbox-outline",
      type: "line",
      source: LINE_SOURCE,
      paint: {
        "line-color": SELECTION_COLOR,
        "line-width": 1.5,
        "line-opacity": 0.85,
        "line-dasharray": [3, 2],
      },
    });
    this.show(initial, false);
    texts.bind(() => {
      this.measure(this.measured);
    });
  }

  /**
   * Shows `selection`, if it differs from the one on screen. `fit` zooms to it: for
   * an uploaded area, which can be anywhere; a drawn one is already in view.
   */
  show(selection: Selection | null, fit: boolean): void {
    const key = selectionKey(selection);
    if (key === this.key) return;
    this.key = key;
    this.shown = selection;
    element("clear-btn").hidden = !selection;
    this.draw(selection);
    this.measure(selection);
    if (selection && fit) this.fitTo(ringBounds(selection.ring));
  }

  /** The selection on screen; null for none. */
  get current(): Selection | null {
    return this.shown;
  }

  /**
   * A rectangle being dragged: drawn and measured as it will snap, not yet a
   * selection.
   */
  preview(bounds: Bounds): void {
    const snapped = {
      xmin: snapToPixel(bounds.xmin),
      ymin: snapToPixel(bounds.ymin),
      xmax: snapToPixel(bounds.xmax),
      ymax: snapToPixel(bounds.ymax),
    };
    const selection: Selection = { type: "bbox", ring: rectRing(snapped) };
    this.draw(selection);
    this.measure(selection);
  }

  /**
   * Clears a preview that didn't become a selection. The selection Python
   * holds is unchanged, so its next echo has to draw it again.
   */
  dropPreview(): void {
    this.draw(null);
    this.measure(null);
    this.key = undefined;
  }

  private measure(selection: Selection | null): void {
    this.measured = selection;
    element("bbox-readout").textContent = selection ? selectionReadout(selection, this.texts) : "";
  }

  private draw(selection: Selection | null): void {
    const { fill, line } = shapes(selection);
    replaceData(geojsonSource(this.map, FILL_SOURCE), fill);
    replaceData(geojsonSource(this.map, LINE_SOURCE), line);
  }

  private fitTo(bounds: Bounds): void {
    const sw = toWgs(bounds.xmin, bounds.ymin);
    const ne = toWgs(bounds.xmax, bounds.ymax);
    this.map.fitBounds(
      [
        [sw.lon, sw.lat],
        [ne.lon, ne.lat],
      ],
      { padding: 60, duration: 800, maxZoom: 18 },
    );
  }
}
