// Small helpers for the GeoJSON sources the components update at runtime.

import type { FeatureCollection } from "geojson";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";

export const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

/** The GeoJSON source `id`; throws if the component never added it. */
export function geojsonSource(map: MapLibreMap, id: string): GeoJSONSource {
  const found = map.getSource<GeoJSONSource>(id);
  if (!found) throw new Error(`source ${id} was not added`);
  return found;
}

/**
 * Replaces a source's data, or the URL it is fetched from. MapLibre fetches
 * and parses it in its worker; a failure there rejects, and is logged, since
 * nothing on the map would show it.
 */
export function replaceData(target: GeoJSONSource, data: FeatureCollection | string): void {
  target.setData(data).catch((err: unknown) => {
    console.error(`could not update source ${target.id}`, err);
  });
}
