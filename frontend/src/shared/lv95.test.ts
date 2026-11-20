import { describe, expect, it } from "vitest";

import { fromWgs, isPlausible, snapToPixel, toWgs } from "./lv95";

// pyproj 3.7 (EPSG:2056 -> EPSG:4326, always_xy), the reference the app's
// Python side uses.
const PYPROJ: [east: number, north: number, lat: number, lon: number][] = [
  [2600000, 1200000, 46.951082772, 7.438632421],
  [2616000, 1149000, 46.492125907, 7.647037147],
  [2554000, 1128000, 46.301826861, 6.841596403],
  [2660000, 1170000, 46.678529455, 8.222836589],
];

// 1e-7 degrees is about 1 cm.
const DEG_7 = 7;

describe("toWgs / fromWgs", () => {
  it.each(PYPROJ)("matches pyproj at E %i N %i", (east, north, lat, lon) => {
    const wgs = toWgs(east, north);
    expect(wgs.lat).toBeCloseTo(lat, DEG_7);
    expect(wgs.lon).toBeCloseTo(lon, DEG_7);
  });

  it.each(PYPROJ)("maps pyproj's WGS84 back to E %i N %i within 1 cm", (east, north, lat, lon) => {
    const lv95 = fromWgs(lat, lon);
    expect(Math.abs(lv95.E - east)).toBeLessThan(0.01);
    expect(Math.abs(lv95.N - north)).toBeLessThan(0.01);
  });

  it.each(PYPROJ)("round-trips E %i N %i within 1 mm", (east, north) => {
    const wgs = toWgs(east, north);
    const lv95 = fromWgs(wgs.lat, wgs.lon);
    expect(Math.abs(lv95.E - east)).toBeLessThan(0.001);
    expect(Math.abs(lv95.N - north)).toBeLessThan(0.001);
  });
});

describe("snapToPixel", () => {
  it.each([
    [2616002.5, 2616002.5],
    [2616000, 2616002.5], // halfway between two centres: the upper one
    [2616004.9, 2616002.5],
    [2616005.1, 2616007.5],
    [1148999.9, 1148997.5],
  ])("snaps %d to %d", (v, centre) => {
    expect(snapToPixel(v)).toBe(centre);
  });
});

describe("isPlausible", () => {
  it("accepts Kanton Bern and the edges of the box", () => {
    expect(isPlausible(2616000, 1149000)).toBe(true);
    expect(isPlausible(2460000, 1050000)).toBe(true);
    expect(isPlausible(2860000, 1320000)).toBe(true);
  });

  it("rejects swapped X/Y, WGS84 degrees and points just outside", () => {
    expect(isPlausible(1149000, 2616000)).toBe(false);
    expect(isPlausible(7.6, 46.5)).toBe(false);
    expect(isPlausible(2459999.9, 1149000)).toBe(false);
    expect(isPlausible(2616000, 1320000.1)).toBe(false);
  });

  it("rejects non-finite values", () => {
    expect(isPlausible(Number.NaN, 1149000)).toBe(false);
    expect(isPlausible(2616000, Number.POSITIVE_INFINITY)).toBe(false);
  });
});
