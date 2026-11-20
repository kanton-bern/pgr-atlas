// LV95 (EPSG:2056) <-> WGS84, and the gold pixel lattice.
//
// Exact datum-aware proj4 definition (Bursa-Wolf +towgs84 parameters from
// swisstopo), not swisstopo's approximate polynomial: a hand-written inverse of
// that polynomial once put every click about 160 m south-west of the real point.
// lv95.test.ts checks it against pyproj.

import proj4 from "proj4";

proj4.defs(
  "EPSG:2056",
  "+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 " +
    "+x_0=2600000 +y_0=1200000 +ellps=bessel " +
    "+towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs",
);
const LV95_WGS84 = proj4("EPSG:2056", "EPSG:4326");

// Switzerland's LV95 extent (about E 2,485,000–2,834,000 / N 1,075,000–1,296,000),
// padded a little: tight enough to catch a foreign coordinate or swapped X/Y in
// the search box. app.py's _LV95_PLAUSIBLE_BOUNDS is wider on purpose (it only
// catches a wrong CRS on upload).
const BOUNDS = { xmin: 2460000, xmax: 2860000, ymin: 1050000, ymax: 1320000 };

export function toWgs(east: number, north: number): { lat: number; lon: number } {
  const [lon, lat] = LV95_WGS84.forward([east, north]);
  return { lat, lon };
}

export function fromWgs(lat: number, lon: number): { E: number; N: number } {
  const [east, north] = LV95_WGS84.inverse([lon, lat]);
  return { E: east, N: north };
}

/**
 * The nearest gold pixel centre. Centres sit on a fixed 5 m lattice at k*5 + 2.5
 * (the master DTM's origin, 2554000/1128000, is a multiple of 5), never on plain
 * multiples of 5.
 */
export function snapToPixel(v: number): number {
  return 5 * Math.round((v - 2.5) / 5) + 2.5;
}

/** True for a finite coordinate inside (padded) Switzerland. */
export function isPlausible(east: number, north: number): boolean {
  return (
    Number.isFinite(east) &&
    Number.isFinite(north) &&
    east >= BOUNDS.xmin &&
    east <= BOUNDS.xmax &&
    north >= BOUNDS.ymin &&
    north <= BOUNDS.ymax
  );
}
