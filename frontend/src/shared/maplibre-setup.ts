// Global MapLibre setup a component does once, before it creates its map.

import { addProtocol, setWorkerUrl } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { Protocol } from "pmtiles";

/**
 * Points MapLibre at its bundled worker and registers the pmtiles:// protocol.
 *
 * MapLibre 6 looks for its worker next to its own module file, which a bundle
 * doesn't have. Vite builds the worker, with the code it imports, into one
 * file of its own and gives its URL.
 */
export function setupMapLibre(): void {
  setWorkerUrl(workerUrl);
  addProtocol("pmtiles", new Protocol().tile);
}
