// Render args of the Anriss view's result map, as app/anriss_map_component.py
// sends them.

import type { FeatureCollection } from "geojson";

import { CHROME_LABELS } from "@/shared/map-controls";
import type { OutlineOverlay } from "@/shared/outline-overlays";
import type { TextArgs } from "@/shared/texts";
import type { LatLonBounds, TileSidecarArgs } from "@/shared/types";

/** Every label the Anriss map takes in `labels`. */
export const ANRISS_LABELS = [...CHROME_LABELS, "layers", "variable", "cell_value"] as const;

export interface ValueLegend {
  title: string;
  /** CSS colour stops of the bar, "#440154, #21918c, #fde725". */
  gradient: string;
  vmin_label: string;
  vmid_label: string;
  vmax_label: string;
}

export interface Variable {
  key: string;
  label: string;
}

/** What the map sends back when the user picks another variable. */
export interface VariableValue {
  variable: string;
}

export interface AnrissArgs extends TileSidecarArgs, TextArgs {
  /** Read on the first render only: a new Anriss gets a new component key. */
  bounds: LatLonBounds;
  /** Pixel squares with fillColor and value_label, coloured by Python. */
  cells_geojson: FeatureCollection | null;
  /** The cells are only re-read when this changes. */
  cells_version: string;
  cells_label: string;
  legend: ValueLegend | null;
  overlays: OutlineOverlay[];
  variables: Variable[];
  active_variable: string;
}
