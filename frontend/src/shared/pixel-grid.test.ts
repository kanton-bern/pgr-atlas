import { describe, expect, it } from "vitest";

import { gridLines, pixelSquare } from "@/shared/pixel-grid";
import { fromWgs, toWgs } from "@/shared/lv95";

// The WGS84 round trip is off by up to about 1 mm.
const CM = 0.01;

function onLattice(v: number): boolean {
  return Math.abs(v - 5 * Math.round(v / 5)) < CM;
}

function lv95([lon = 0, lat = 0]: number[]): [number, number] {
  const { E, N } = fromWgs(lat, lon);
  return [E, N];
}

describe("pixelSquare", () => {
  it("is empty for no pixel", () => {
    expect(pixelSquare(null).features).toEqual([]);
  });

  it("is the closed 5 m square around the pixel centre", () => {
    const [feature] = pixelSquare([2600002.5, 1200002.5]).features;
    const ring = feature?.geometry.coordinates[0] ?? [];
    expect(ring).toHaveLength(5);
    expect(ring[4]).toEqual(ring[0]);
    const corners = ring.slice(0, 4).map(lv95);
    const expected = [
      [2600000, 1200000],
      [2600005, 1200000],
      [2600005, 1200005],
      [2600000, 1200005],
    ];
    corners.forEach(([e, n], i) => {
      expect(Math.abs(e - (expected[i]?.[0] ?? NaN))).toBeLessThan(CM);
      expect(Math.abs(n - (expected[i]?.[1] ?? NaN))).toBeLessThan(CM);
    });
  });
});

describe("gridLines", () => {
  // 34 x 24 m around LV95 2600000 / 1200000, edges away from pixel centres.
  const sw = toWgs(2599983, 1199988);
  const ne = toWgs(2600017, 1200012);
  const lines = gridLines({ south: sw.lat, west: sw.lon, north: ne.lat, east: ne.lon }).features;
  const starts = lines.map((f) => lv95(f.geometry.coordinates[0] ?? []));
  const ends = lines.map((f) => lv95(f.geometry.coordinates[1] ?? []));

  it("puts every line on a pixel edge, a multiple of 5 m", () => {
    for (const [e, n] of starts) {
      expect(onLattice(e) && onLattice(n)).toBe(true);
    }
  });

  it("covers the view with some margin", () => {
    const xs = starts.filter((_, i) => Math.abs((starts[i]?.[0] ?? 0) - (ends[i]?.[0] ?? 0)) < 1);
    const eastings = xs.map(([e]) => e);
    expect(Math.min(...eastings)).toBeLessThan(2599983);
    expect(Math.max(...eastings)).toBeGreaterThan(2600017);
  });

  it("draws both directions, 5 m apart", () => {
    const vertical = starts.filter(
      (_, i) => Math.abs((starts[i]?.[0] ?? 0) - (ends[i]?.[0] ?? 0)) < 1,
    );
    const horizontal = lines.length - vertical.length;
    // With 15 m padding, rounded out to pixel edges: E 2599965..2600035 is 15
    // vertical lines, N 1199970..1200030 is 13 horizontal ones.
    expect(vertical).toHaveLength(15);
    expect(horizontal).toBe(13);
  });
});
