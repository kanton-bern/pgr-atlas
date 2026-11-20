// Geometry of a drawn selection, in LV95 metres: the ring of a dragged
// rectangle, bounds, area and the size readout. A rectangle is the 4-corner
// case of the same closed ring a polygon uses (ifk_and_raster.py's
// rect_ring and normalize_selection).

import type { Lv95Point, Selection } from "@/shared/types";
import { snapToPixel } from "@/shared/lv95";
import { formatNumber } from "@/shared/number-format";
import { fill, type Labels, type Locale } from "@/shared/texts";

/** A drag smaller than this (after snapping) is a click, not a rectangle. */
export const MIN_BBOX_SIZE_M = 5;

export interface Bounds {
  xmin: number;
  ymin: number;
  xmax: number;
  ymax: number;
}

export function rectRing({ xmin, ymin, xmax, ymax }: Bounds): Lv95Point[] {
  return [
    [xmin, ymin],
    [xmax, ymin],
    [xmax, ymax],
    [xmin, ymax],
    [xmin, ymin],
  ];
}

/** The rectangle between two corners of a drag, in any order. */
export function dragBounds(a: Lv95Point, b: Lv95Point): Bounds {
  return {
    xmin: Math.min(a[0], b[0]),
    ymin: Math.min(a[1], b[1]),
    xmax: Math.max(a[0], b[0]),
    ymax: Math.max(a[1], b[1]),
  };
}

/**
 * The finished rectangle of a drag, its corners snapped to gold pixel centres;
 * null when it is too small to be one.
 */
export function snappedRect(a: Lv95Point, b: Lv95Point): Selection | null {
  const raw = dragBounds(a, b);
  const bounds = {
    xmin: snapToPixel(raw.xmin),
    ymin: snapToPixel(raw.ymin),
    xmax: snapToPixel(raw.xmax),
    ymax: snapToPixel(raw.ymax),
  };
  if (bounds.xmax - bounds.xmin < MIN_BBOX_SIZE_M || bounds.ymax - bounds.ymin < MIN_BBOX_SIZE_M) {
    return null;
  }
  return { type: "bbox", ring: rectRing(bounds) };
}

export function ringBounds(ring: readonly Lv95Point[]): Bounds {
  const eastings = ring.map((point) => point[0]);
  const northings = ring.map((point) => point[1]);
  return {
    xmin: Math.min(...eastings),
    ymin: Math.min(...northings),
    xmax: Math.max(...eastings),
    ymax: Math.max(...northings),
  };
}

/** Shoelace formula; the ring may be closed or not. */
export function ringArea(ring: readonly Lv95Point[]): number {
  let twice = 0;
  ring.forEach(([x1, y1], i) => {
    const [x2, y2] = ring[(i + 1) % ring.length] ?? [x1, y1];
    twice += x1 * y2 - x2 * y1;
  });
  return Math.abs(twice) / 2;
}

/** The labels of the size readout. */
export const READOUT_LABELS = [
  "length_m",
  "length_km",
  "selection_size_rect",
  "selection_size_polygon",
] as const;

export interface ReadoutTexts {
  labels: Labels<(typeof READOUT_LABELS)[number]>;
  locale: Locale;
}

export function formatLength(metres: number, { labels, locale }: ReadoutTexts): string {
  if (metres >= 1000) {
    const value = formatNumber(metres / 1000, locale, { digits: 2, group: false });
    return fill(labels.length_km, { value });
  }
  const value = formatNumber(Math.round(metres), locale, { group: false });
  return fill(labels.length_m, { value });
}

/**
 * The size, not the coordinates: width × height of the bounding box and the
 * area. A polygon's own area, which its bounding box would overstate.
 */
export function sizeReadout(
  bounds: Bounds,
  texts: ReadoutTexts,
  polygon?: { vertices: number; area: number },
): string {
  const width = bounds.xmax - bounds.xmin;
  const height = bounds.ymax - bounds.ymin;
  const values = {
    width: formatLength(width, texts),
    height: formatLength(height, texts),
    area: formatNumber(Math.round(polygon?.area ?? width * height), texts.locale),
  };
  return polygon
    ? fill(texts.labels.selection_size_polygon, { ...values, vertices: polygon.vertices })
    : fill(texts.labels.selection_size_rect, values);
}

/** Tells two selections apart: the same ring is the same selection. */
export function selectionKey(selection: Selection | null): string | null {
  return selection ? JSON.stringify(selection.ring) : null;
}
