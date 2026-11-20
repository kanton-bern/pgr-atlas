// Render args of the Gebäudeschatten map, as
// app/gebaeudeschatten_map_component.py sends them.

import type { FeatureCollection } from "geojson";

import { CHROME_LABELS } from "@/shared/map-controls";
import { RASTER_OPACITY_LABELS } from "@/shared/layer-box";
import type { OutlineOverlay } from "@/shared/outline-overlays";
import type { TextArgs } from "@/shared/texts";
import type { LatLonBounds, TileSidecarArgs } from "@/shared/types";

/** Every label the Gebäudeschatten map takes in `labels`. */
export const GEBAEUDESCHATTEN_LABELS = [
  ...CHROME_LABELS,
  ...RASTER_OPACITY_LABELS,
  "layers",
  "mask_default",
  "mask_error",
  "buildings",
  "building_hover",
  "cells_default",
] as const;

/** The canton-wide affected mask, cropped per view by derivate_bbox_server.py. */
export interface MaskArgs {
  metric: string;
  partition: string;
  label: string;
  server_port: number;
  path_prefix: string;
}

export interface CellsKeyEntry {
  color: string;
  label: string;
}

export interface Focus {
  bounds: LatLonBounds;
  /** A new nonce is a new selection from the sidebar: the map frames it. */
  nonce: number;
}

export interface GebaeudeschattenArgs extends TileSidecarArgs, TextArgs {
  /** Read on the first render only. */
  bounds: LatLonBounds;
  /** The buildings tileset on the tile sidecar; features carry id_start and area_m2. */
  buildings_pmtiles: string;
  buildings_layer: string;
  mask: MaskArgs | null;
  /** Pixel squares with fillColor, fillOpacity and tooltip (multi-line). */
  cells_geojson: FeatureCollection | null;
  /** The cells are only re-read when this changes. */
  cells_version: string;
  cells_label: string;
  cells_legend: CellsKeyEntry[];
  overlays: OutlineOverlay[];
  focus: Focus | null;
}

/**
 * What a click sends back: a building, or the LV95 centre of a pixel. The
 * value repeats on every rerun until the next click; the nonce tells them apart.
 */
export type ClickValue =
  | { type: "building"; id_start: number; nonce: number }
  | { type: "pixel"; e: number; n: number; nonce: number };
