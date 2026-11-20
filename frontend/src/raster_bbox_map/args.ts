// Render args of the raster map (app/raster_bbox_component.py,
// raster_bbox_map), used by two views: Raster-Karten (drawn selection,
// finished raster overlays) and Raster-Derivate (live canton crops).
// Python sends every key; None arrives as null.

import { CHROME_LABELS, PROZESSQUELLE_LABELS } from "@/shared/map-controls";
import { RASTER_OPACITY_LABELS } from "@/shared/layer-box";
import { SELECTION_LABELS } from "@/shared/selection";
import type { TextArgs, TextSource } from "@/shared/texts";
import type { CoverageArgs, DerivateSidecarArgs, Selection, TileSidecarArgs } from "@/shared/types";

/** Every label the raster map takes in `labels`. */
export const RASTER_LABELS = [
  ...CHROME_LABELS,
  ...PROZESSQUELLE_LABELS,
  ...SELECTION_LABELS,
  ...RASTER_OPACITY_LABELS,
  "layers",
  "gold_coverage",
  "prozessquellen",
  "raster_layer",
  "var_switch_title",
  "legend_title_unit",
  "log_scale",
  "mask_ticks",
  "pixel_value",
  "pixel_value_unitless",
  "pixel_mask_yes",
  "pixel_mask_no",
  "crop_loading",
  "crop_error",
  "derivate_error",
  "image_error",
  "values_error",
] as const;

export type RasterTexts = TextSource<(typeof RASTER_LABELS)[number]>;

/** Where the hover grid's pixels are, in LV95 (row 0 is the north edge). */
export interface HoverGeometry {
  width: number;
  height: number;
  xmin: number;
  ymax: number;
  res: number;
}

/** One finished raster of a Raster-Karten job (views/raster_karten.py's _register_raster_job). */
export interface RasterOverlay {
  job_id: string;
  var: string;
  /** [lon, lat] corners: top left, top right, bottom right, bottom left. */
  corners: [[number, number], [number, number], [number, number], [number, number]];
  /** CSS colour stops for the legend bar. */
  gradient: string;
  label: string;
  unit: string;
  log_scale: boolean;
  vmin_label: string;
  vmid_label: string;
  vmax_label: string;
  /** Null when the raster is too big for a hover grid. */
  hover: HoverGeometry | null;
}

export type DerivateScale = "log" | "linear" | "mask";

export interface RasterArgs extends TileSidecarArgs, DerivateSidecarArgs, CoverageArgs, TextArgs {
  center_lat: number;
  center_lon: number;
  selected_selection: Selection | null;
  /** One overlay per variable of the last job; null: no raster. */
  raster_overlays: Record<string, RasterOverlay> | null;
  active_variable: string | null;
  /** Null: 0.25. */
  coverage_fill_opacity: number | null;
  /** Null: no Raster-Derivate layer. */
  derivate_bbox_metric: string | null;
  derivate_bbox_partition: string | null;
  /** 1-based band of the metric's mosaic. */
  derivate_bbox_band: number | null;
  derivate_bbox_label: string | null;
  derivate_bbox_unit: string | null;
  derivate_bbox_scale: DerivateScale | null;
  derivate_bbox_ramp: string | null;
  derivate_bbox_vmin: number | null;
  derivate_bbox_vmax: number | null;
  derivate_bbox_note: string | null;
}
