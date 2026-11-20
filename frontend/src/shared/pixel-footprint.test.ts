import { describe, expect, it } from "vitest";

import type { Lv95Point, Selection } from "@/shared/types";
import { pixelFootprint, selectionReadout } from "@/shared/pixel-footprint";
import { type ReadoutTexts, rectRing } from "@/shared/selection-geometry";

const DE: ReadoutTexts = {
  labels: {
    length_m: "{value} m",
    length_km: "{value} km",
    selection_size_rect: "{width} × {height} · {area} m²",
    selection_size_polygon: "Polygon ({vertices} Eckpunkte) · {width} × {height} · {area} m²",
  },
  locale: "de-CH",
};

const E = 2600000;
const N = 1200000;

function polygon(points: [number, number][]): Selection {
  const ring: Lv95Point[] = points.map(([x, y]) => [E + x, N + y]);
  return { type: "polygon", ring: [...ring, ring[0] as Lv95Point] };
}

/** Pixel centres inside `selection` per the server's rule, by brute force. */
function centresInside(selection: Selection, from: number, to: number): number {
  let count = 0;
  for (let x = from + 2.5; x < to; x += 5) {
    for (let y = from + 2.5; y < to; y += 5) {
      if (strictlyInside([E + x, N + y], selection.ring)) count++;
    }
  }
  return count;
}

function strictlyInside([px, py]: Lv95Point, ring: readonly Lv95Point[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 2; i < ring.length - 1; j = i++) {
    const [xi, yi] = ring[i] as Lv95Point;
    const [xj, yj] = ring[j] as Lv95Point;
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Signed areas of the outline rings add up to the pixels' area (holes count negative). */
function outlineArea(rings: readonly Lv95Point[][]): number {
  return rings.reduce((sum, ring) => {
    let twice = 0;
    ring.forEach(([x1, y1], i) => {
      const [x2, y2] = ring[(i + 1) % ring.length] ?? [x1, y1];
      twice += x1 * y2 - x2 * y1;
    });
    return sum + twice / 2;
  }, 0);
}

describe("pixelFootprint of a rectangle", () => {
  it("draws corners on pixel centres half a pixel further out", () => {
    const selection: Selection = {
      type: "bbox",
      ring: rectRing({ xmin: E + 2.5, ymin: N + 2.5, xmax: E + 12.5, ymax: N + 22.5 }),
    };
    const rect = { xmin: E, ymin: N, xmax: E + 15, ymax: N + 25 };
    expect(pixelFootprint(selection)).toEqual({ rects: [rect], rings: [rectRing(rect)] });
  });

  it("takes only the centres inside corners off the lattice", () => {
    const selection: Selection = {
      type: "bbox",
      ring: rectRing({ xmin: E + 1, ymin: N + 3, xmax: E + 14, ymax: N + 20 }),
    };
    expect(pixelFootprint(selection)?.rects).toEqual([
      { xmin: E, ymin: N + 5, xmax: E + 15, ymax: N + 20 },
    ]);
  });
});

describe("pixelFootprint of a polygon", () => {
  it("covers exactly the pixels whose centre is inside, outlined as one ring", () => {
    const selection = polygon([
      [1, 1],
      [48, 3],
      [7, 44],
    ]);
    const footprint = pixelFootprint(selection);
    if (!footprint) throw new Error("no footprint");
    const pixels = centresInside(selection, 0, 50);
    const fillArea = footprint.rects.reduce((s, r) => s + (r.xmax - r.xmin) * (r.ymax - r.ymin), 0);
    expect(fillArea).toBe(pixels * 25);
    expect(footprint.rings).toHaveLength(1);
    expect(Math.abs(outlineArea(footprint.rings))).toBe(pixels * 25);
    for (const ring of footprint.rings) {
      expect(ring[0]).toEqual(ring[ring.length - 1]);
      for (const [x, y] of ring) {
        expect((x - E) % 5).toBe(0);
        expect((y - N) % 5).toBe(0);
      }
    }
  });

  it("outlines a hole as a ring of its own", () => {
    // A U-turn polygon: an outer square with a notch cut to its middle, so
    // the centre pixels are outside but surrounded.
    const selection = polygon([
      [0.5, 0.5],
      [29.5, 0.5],
      [29.5, 29.5],
      [16, 29.5],
      [16, 21],
      [21, 21],
      [21, 9],
      [9, 9],
      [9, 21],
      [14, 21],
      [14, 29.5],
      [0.5, 29.5],
    ]);
    const footprint = pixelFootprint(selection);
    // The notch (x 14..16) holds no pixel centre, so the square's middle is a hole.
    expect(footprint?.rings).toHaveLength(2);
    expect(outlineArea(footprint?.rings ?? [])).toBe(centresInside(selection, 0, 30) * 25);
  });

  it("closes pixels that touch only at a corner", () => {
    // A thin band along the diagonal: centres (2.5, 2.5) and (7.5, 7.5) only.
    const selection = polygon([
      [0, 0],
      [1, 0],
      [10, 9],
      [10, 10],
      [9, 10],
      [0, 1],
    ]);
    const footprint = pixelFootprint(selection);
    expect(Math.abs(outlineArea(footprint?.rings ?? []))).toBe(50);
    for (const ring of footprint?.rings ?? []) expect(ring[0]).toEqual(ring[ring.length - 1]);
  });

  it("is null for a sliver without a pixel centre", () => {
    expect(
      pixelFootprint(
        polygon([
          [0, 0],
          [50, 1],
          [0, 2],
        ]),
      ),
    ).toBeNull();
  });
});

describe("selectionReadout", () => {
  const m2 = (n: number): string => `${n.toLocaleString("de-CH")} m²`;

  it("measures a rectangle's pixels: corners on centres, half a pixel further out", () => {
    const selection: Selection = {
      type: "bbox",
      ring: rectRing({ xmin: E + 2.5, ymin: N + 2.5, xmax: E + 102.5, ymax: N + 52.5 }),
    };
    expect(selectionReadout(selection, DE)).toBe(`105 m × 55 m · ${m2(5775)}`);
  });

  it("measures a polygon's pixels, whose centres lie strictly inside", () => {
    const selection = polygon([
      [2.5, 2.5],
      [102.5, 2.5],
      [102.5, 52.5],
      [2.5, 52.5],
    ]);
    // Centres on the ring are outside: 19 × 9 pixels.
    expect(selectionReadout(selection, DE)).toBe(
      `Polygon (4 Eckpunkte) · 95 m × 45 m · ${m2(4275)}`,
    );
  });

  it("gives a polygon without a pixel 0 m²", () => {
    const selection = polygon([
      [0, 0],
      [50, 1],
      [0, 2],
    ]);
    expect(selectionReadout(selection, DE)).toBe(`Polygon (3 Eckpunkte) · 50 m × 2 m · ${m2(0)}`);
  });
});
