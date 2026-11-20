// The pixels a selection takes, as drawn on the map: the outer edges of the
// 5 m gold pixels, not the ring itself. The server decides by pixel centre:
// a rectangle takes every centre on or inside it (x >= xmin AND x <= xmax,
// ifk_and_raster._selection_where_sql; derivate_lake.snapped_window snaps
// outward), a polygon every centre strictly inside it (ST_Contains,
// geometry_mask). So a rectangle's corners on pixel centres draw 2.5 m
// further out, and a polygon draws as the staircase around its pixels.

import type { Lv95Point, Selection } from "@/shared/types";
import {
  type Bounds,
  type ReadoutTexts,
  rectRing,
  ringBounds,
  sizeReadout,
} from "@/shared/selection-geometry";

const PIXEL_M = 5;
const HALF_PIXEL_M = PIXEL_M / 2;

/** Pixels with centre PIXEL_M*i + HALF_PIXEL_M for i in [first, last]. */
interface Run {
  first: number;
  last: number;
}

export interface Footprint {
  /** The fill: pixel rows, consecutive rows with the same runs merged. */
  rects: Bounds[];
  /** The outline: closed rings along the pixel edges (outer and holes alike). */
  rings: Lv95Point[][];
}

/** Index of the first pixel centre >= v. */
function firstCentreAtOrAbove(v: number): number {
  return Math.ceil((v - HALF_PIXEL_M) / PIXEL_M);
}

/** Index of the last pixel centre <= v. */
function lastCentreAtOrBelow(v: number): number {
  return Math.floor((v - HALF_PIXEL_M) / PIXEL_M);
}

/** Index of the first pixel centre > v. */
function firstCentreAbove(v: number): number {
  return Math.floor((v - HALF_PIXEL_M) / PIXEL_M) + 1;
}

/** Index of the last pixel centre < v. */
function lastCentreBelow(v: number): number {
  return Math.ceil((v - HALF_PIXEL_M) / PIXEL_M) - 1;
}

/** A ring's non-horizontal edges as [x, y] low end, [x, y] high end; lowest first. */
type Edge = [number, number, number, number];

function sortedEdges(ring: readonly Lv95Point[]): Edge[] {
  const edges: Edge[] = [];
  ring.forEach(([x1, y1], index) => {
    const [x2, y2] = ring[(index + 1) % ring.length] ?? [x1, y1];
    if (y1 !== y2) edges.push(y1 < y2 ? [x1, y1, x2, y2] : [x2, y2, x1, y1]);
  });
  return edges.sort((edge, other) => edge[1] - other[1]);
}

/** The runs of pixel centres strictly between each pair of sorted crossings. */
function runsBetween(xs: readonly number[]): Run[] {
  const runs: Run[] = [];
  for (let entry = 0; entry + 1 < xs.length; entry += 2) {
    const first = firstCentreAbove(xs[entry] ?? 0);
    const last = lastCentreBelow(xs[entry + 1] ?? 0);
    if (first > last) continue;
    const previous = runs[runs.length - 1];
    if (previous && first <= previous.last + 1) previous.last = Math.max(previous.last, last);
    else runs.push({ first, last });
  }
  return runs;
}

/**
 * Per pixel row (by row index, bottom first), the runs of pixels whose centre
 * is strictly inside the ring. A scanline through each row's centre, with the
 * edges sorted by their lower end so each row only looks at the edges it crosses.
 */
function polygonRows(ring: readonly Lv95Point[]): { firstRow: number; rows: Run[][] } {
  const edges = sortedEdges(ring);
  const { ymin, ymax } = ringBounds(ring);
  const firstRow = firstCentreAbove(ymin);
  const rows: Run[][] = [];
  let active: Edge[] = [];
  let nextEdge = 0;
  for (let row = firstRow; row <= lastCentreBelow(ymax); row++) {
    const centreY = PIXEL_M * row + HALF_PIXEL_M;
    for (; nextEdge < edges.length && (edges[nextEdge]?.[1] ?? Infinity) <= centreY; nextEdge++) {
      active.push(edges[nextEdge] as Edge);
    }
    // Half-open in y, so a vertex on the scanline counts once.
    active = active.filter((edge) => edge[3] > centreY);
    const crossings = active.map(
      ([x1, y1, x2, y2]) => x1 + ((centreY - y1) * (x2 - x1)) / (y2 - y1),
    );
    rows.push(runsBetween(crossings.sort((left, right) => left - right)));
  }
  return { firstRow, rows };
}

/** The parts of `a` not covered by `b`, both sorted and disjoint. */
function subtract(a: readonly Run[], b: readonly Run[]): Run[] {
  const out: Run[] = [];
  for (const run of a) {
    let start = run.first;
    for (const cut of b) {
      if (cut.last < start || cut.first > run.last) continue;
      if (cut.first > start) out.push({ first: start, last: cut.first - 1 });
      start = cut.last + 1;
    }
    if (start <= run.last) out.push({ first: start, last: run.last });
  }
  return out;
}

function sameRuns(a: readonly Run[], b: readonly Run[]): boolean {
  return (
    a.length === b.length &&
    a.every((run, index) => {
      const other = b[index];
      return other !== undefined && run.first === other.first && run.last === other.last;
    })
  );
}

/**
 * The pixel edges around the runs, as directed segments with the pixels on
 * their left, chained into closed rings. Where two rings touch at a corner,
 * either continuation closes a valid ring.
 */
function outlineRings(firstRow: number, rows: readonly Run[][]): Lv95Point[][] {
  // Segment start point (as "x,y") -> the end points of the segments leaving it.
  const segmentsFrom = new Map<string, Lv95Point[]>();
  const addSegment = (from: Lv95Point, to: Lv95Point): void => {
    const key = from.join();
    const ends = segmentsFrom.get(key);
    if (ends) ends.push(to);
    else segmentsFrom.set(key, [to]);
  };
  const columnEdge = (column: number): number => PIXEL_M * column;
  rows.forEach((runs, rowIndex) => {
    const bottom = PIXEL_M * (firstRow + rowIndex);
    const top = bottom + PIXEL_M;
    for (const run of subtract(runs, rows[rowIndex - 1] ?? [])) {
      addSegment([columnEdge(run.first), bottom], [columnEdge(run.last + 1), bottom]);
    }
    for (const run of subtract(runs, rows[rowIndex + 1] ?? [])) {
      addSegment([columnEdge(run.last + 1), top], [columnEdge(run.first), top]);
    }
    for (const run of runs) {
      addSegment([columnEdge(run.last + 1), bottom], [columnEdge(run.last + 1), top]);
      addSegment([columnEdge(run.first), top], [columnEdge(run.first), bottom]);
    }
  });
  const rings: Lv95Point[][] = [];
  for (const [startKey, targets] of segmentsFrom) {
    while (targets.length) {
      const start = startKey.split(",").map(Number) as Lv95Point;
      const ring: Lv95Point[] = [start];
      let at: Lv95Point | undefined = targets.pop();
      while (at) {
        ring.push(at);
        if (at[0] === start[0] && at[1] === start[1]) break;
        at = segmentsFrom.get(at.join())?.pop();
      }
      rings.push(dropCollinear(ring));
    }
  }
  return rings;
}

/** A closed axis-parallel ring without the points in the middle of a straight side. */
function dropCollinear(ring: Lv95Point[]): Lv95Point[] {
  const open = ring.slice(0, -1);
  const kept = open.filter((point, index) => {
    const previous = open[(index - 1 + open.length) % open.length] ?? point;
    const next = open[(index + 1) % open.length] ?? point;
    const onVerticalSide = previous[0] === point[0] && point[0] === next[0];
    const onHorizontalSide = previous[1] === point[1] && point[1] === next[1];
    return !(onVerticalSide || onHorizontalSide);
  });
  const first = kept[0];
  return first ? [...kept, first] : ring;
}

/**
 * The footprint of `selection`; null for a polygon too thin to hold a pixel centre,
 * which is then drawn as its own ring.
 */
export function pixelFootprint(selection: Selection): Footprint | null {
  return selection.type === "bbox"
    ? bboxFootprint(selection.ring)
    : polygonFootprint(selection.ring);
}

function bboxFootprint(ring: readonly Lv95Point[]): Footprint | null {
  const bounds = ringBounds(ring);
  const rect = {
    xmin: PIXEL_M * firstCentreAtOrAbove(bounds.xmin),
    ymin: PIXEL_M * firstCentreAtOrAbove(bounds.ymin),
    xmax: PIXEL_M * (lastCentreAtOrBelow(bounds.xmax) + 1),
    ymax: PIXEL_M * (lastCentreAtOrBelow(bounds.ymax) + 1),
  };
  if (rect.xmin >= rect.xmax || rect.ymin >= rect.ymax) return null;
  return { rects: [rect], rings: [rectRing(rect)] };
}

function polygonFootprint(ring: readonly Lv95Point[]): Footprint | null {
  const { firstRow, rows } = polygonRows(ring);
  if (rows.every((runs) => runs.length === 0)) return null;
  const rects: Bounds[] = [];
  // Consecutive rows with the same runs become one rectangle per run.
  let groupStart = 0;
  while (groupStart < rows.length) {
    const runs = rows[groupStart] ?? [];
    let groupEnd = groupStart + 1;
    while (groupEnd < rows.length && sameRuns(rows[groupEnd] ?? [], runs)) groupEnd++;
    for (const run of runs) {
      rects.push({
        xmin: PIXEL_M * run.first,
        ymin: PIXEL_M * (firstRow + groupStart),
        xmax: PIXEL_M * (run.last + 1),
        ymax: PIXEL_M * (firstRow + groupEnd),
      });
    }
    groupStart = groupEnd;
  }
  return { rects, rings: outlineRings(firstRow, rows) };
}

/** The footprint's extent: the union of its rows. */
export function footprintBounds({ rects }: Footprint): Bounds {
  return {
    xmin: Math.min(...rects.map((rect) => rect.xmin)),
    ymin: Math.min(...rects.map((rect) => rect.ymin)),
    xmax: Math.max(...rects.map((rect) => rect.xmax)),
    ymax: Math.max(...rects.map((rect) => rect.ymax)),
  };
}

/** The footprint's area: its pixels, 25 m² each. */
export function footprintArea({ rects }: Footprint): number {
  return rects.reduce((sum, rect) => sum + (rect.xmax - rect.xmin) * (rect.ymax - rect.ymin), 0);
}

/**
 * The size of what the selection takes, as the map draws it: the pixels'
 * extent and area, not the ring's (the sidebar measures the same,
 * ui_common.selection_footprint). No pixel: the ring's extent, 0 m².
 */
export function selectionReadout(selection: Selection, texts: ReadoutTexts): string {
  const footprint = pixelFootprint(selection);
  const bounds = footprint ? footprintBounds(footprint) : ringBounds(selection.ring);
  // A rectangle's footprint is one rectangle: its area is width × height.
  if (selection.type === "bbox") return sizeReadout(bounds, texts);
  return sizeReadout(bounds, texts, {
    vertices: selection.ring.length - 1,
    area: footprint ? footprintArea(footprint) : 0,
  });
}
