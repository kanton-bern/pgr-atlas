// The gold 5x5 m pixels as map geometry: one pixel's square, and the grid
// lines over the visible part of the map. Both are built in LV95, where the
// pixels are square, and reprojected corner by corner.

import type { Feature, FeatureCollection, LineString, Polygon } from "geojson";
import type { Map as MapLibreMap } from "maplibre-gl";

import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import { fromWgs, snapToPixel, toWgs } from "@/shared/lv95";

const HALF = 2.5;
// Lines run this far (metres) past the view's edge, so none end on screen.
const PAD = 15;

/** Below this the grid lines are noise, so they are neither computed nor drawn. */
export const GRID_MIN_ZOOM = 17;

/** The visible part of the map, in WGS84. */
export interface ViewBounds {
  south: number;
  west: number;
  north: number;
  east: number;
}

function lonLat(east: number, north: number): [number, number] {
  const { lon, lat } = toWgs(east, north);
  return [lon, lat];
}

function line(from: [number, number], to: [number, number]): Feature<LineString> {
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "LineString", coordinates: [lonLat(...from), lonLat(...to)] },
  };
}

/** The square of the pixel centred at LV95 (x, y), or nothing for null. */
export function pixelSquare(pixel: readonly [number, number] | null): FeatureCollection<Polygon> {
  if (!pixel) return { type: "FeatureCollection", features: [] };
  const [x, y] = pixel;
  const ring = [
    [x - HALF, y - HALF],
    [x + HALF, y - HALF],
    [x + HALF, y + HALF],
    [x - HALF, y + HALF],
    [x - HALF, y - HALF],
  ].map(([e = 0, n = 0]) => lonLat(e, n));
  return {
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [ring] } },
    ],
  };
}

/** The pixel edges that cross `bounds`: lines on the 5 m lattice, between pixel centres. */
export function gridLines(bounds: ViewBounds): FeatureCollection<LineString> {
  const sw = fromWgs(bounds.south, bounds.west);
  const ne = fromWgs(bounds.north, bounds.east);
  const xmin = snapToPixel(Math.min(sw.E, ne.E) - PAD) - HALF;
  const xmax = snapToPixel(Math.max(sw.E, ne.E) + PAD) + HALF;
  const ymin = snapToPixel(Math.min(sw.N, ne.N) - PAD) - HALF;
  const ymax = snapToPixel(Math.max(sw.N, ne.N) + PAD) + HALF;

  const features: Feature<LineString>[] = [];
  // +0.01: the last line is included despite float drift in the sums.
  for (let x = xmin; x <= xmax + 0.01; x += 5) features.push(line([x, ymin], [x, ymax]));
  for (let y = ymin; y <= ymax + 0.01; y += 5) features.push(line([xmin, y], [xmax, y]));
  return { type: "FeatureCollection", features };
}

function viewBounds(map: MapLibreMap): ViewBounds {
  const bounds = map.getBounds();
  return {
    south: bounds.getSouth(),
    west: bounds.getWest(),
    north: bounds.getNorth(),
    east: bounds.getEast(),
  };
}

/**
 * Adds the grid lines as a layer on top of the current ones, and redraws them
 * for the visible part of the map after every move.
 */
export function addPixelGridLayer(map: MapLibreMap): void {
  map.addSource("pixel-grid", { type: "geojson", data: EMPTY });
  map.addLayer({
    id: "pixel-grid-lines",
    type: "line",
    source: "pixel-grid",
    minzoom: GRID_MIN_ZOOM,
    paint: { "line-color": "#000000", "line-opacity": 0.3, "line-width": 1 },
  });
  const grid = geojsonSource(map, "pixel-grid");
  const redraw = () => {
    replaceData(grid, map.getZoom() < GRID_MIN_ZOOM ? EMPTY : gridLines(viewBounds(map)));
  };
  redraw();
  map.on("moveend", redraw);
}
