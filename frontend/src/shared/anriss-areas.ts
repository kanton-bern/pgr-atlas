// Anriss area classes (Anrissfläche), shared by the overview and IFK legends.

import type { FilterSpecification } from "maplibre-gl";

export interface AreaClass {
  /** Anrissfläche in m². */
  area: number;
  label: string;
  /** The overview's circle colour; IFK colours its circles by probability instead. */
  color: string;
}

/**
 * The six values the area takes in MAXI (maxi_event_manifest.parquet). The
 * colours live here, not in the tileset, so they change without a rebuild.
 */
export const AREA_CLASSES: readonly AreaClass[] = [
  { area: 55, label: "55 m²", color: "#228B22" },
  { area: 125, label: "125 m²", color: "#9ACD32" },
  { area: 250, label: "250 m²", color: "#FFD700" },
  { area: 400, label: "400 m²", color: "#FFA500" },
  { area: 700, label: "700 m²", color: "#FF4500" },
  { area: 1100, label: "1100 m²", color: "#8B0000" },
];

/**
 * The ticked classes on mount: the ones Python sent, or all of them when it
 * sent none (null). An empty list is "Keine": no class ticked.
 */
export function initialAreas(fromPython: readonly number[] | null | undefined): Set<number> {
  return new Set(fromPython ?? AREA_CLASSES.map((c) => c.area));
}

/**
 * The layer filter for the ticked classes on the feature property `property`
 * (the overview's tiles call it `A`, IFK's circles `anrissflaeche`); null (no
 * filter) when all are ticked.
 */
export function areaFilter(
  active: ReadonlySet<number>,
  property: string,
): FilterSpecification | null {
  if (active.size === 0) return ["==", ["get", property], -1];
  if (AREA_CLASSES.every((c) => active.has(c.area))) return null;
  return ["in", ["get", property], ["literal", [...active]]];
}
