// Render args of the IFK map (app/ifk_map_component.py, ifk_pixel_map).
// Python sends every key; None arrives as null.

import type { FeatureCollection } from "geojson";

import { AREA_LEGEND_LABELS } from "@/shared/area-legend";
import { CHROME_LABELS, PROZESSQUELLE_LABELS } from "@/shared/map-controls";
import { SELECTION_LABELS } from "@/shared/selection";
import type { TextArgs } from "@/shared/texts";
import type { CoverageArgs, MapView, Selection, TileSidecarArgs } from "@/shared/types";

/** Every label the IFK map takes in `labels`. */
export const IFK_LABELS = [
  ...CHROME_LABELS,
  ...PROZESSQUELLE_LABELS,
  ...SELECTION_LABELS,
  "layers",
  "gold_coverage",
  "prozessquellen",
  "anriss_area",
  ...AREA_LEGEND_LABELS,
  "anriss_outline",
  "anriss_legend_title",
  "anriss_popup_title",
  "anriss_popup_area",
  "anriss_popup_rate",
  "anriss_open",
  "pixel_popup_title",
  "pixel_popup_coords",
  "ifk_compute",
  "area_popup_title",
  "area_popup_too_large",
] as const;

/** An LV95 pixel centre (x, y). */
export type Pixel = [number, number];

/** The colour scale of the anriss circles (views/ifk.py's _anriss_legend_payload). */
export interface AnrissLegend {
  /** CSS colour stops, e.g. "#ffffcc, #bd0026". */
  gradient: string;
  vmin_label: string;
  vmid_label: string;
  vmax_label: string;
}

export interface IfkArgs extends TileSidecarArgs, CoverageArgs, TextArgs {
  center_lat: number;
  center_lon: number;
  /** The selected pixel; the map then opens on it at zoom 18. */
  selected_pixel: Pixel | null;
  /** The selected area (drawn, uploaded or from a link); never together with a pixel. */
  selected_selection: Selection | null;
  /** The selected area is over the limits the sidebar names: its popup disables "IFK berechnen". */
  area_too_large: boolean;
  /**
   * The anrisse that reach the selected pixel, as circles already coloured by
   * Python (`fillColor`, `id_anriss`, `anrissflaeche`, `lambda_ereignis_sum`).
   */
  anriss_circles_geojson: FeatureCollection | null;
  /**
   * One outline around all anrisse that reach the selected area (an area can
   * have 100'000 of them, too many for single circles); null: none.
   */
  anriss_outline_geojson: FeatureCollection | null;
  /** Null hides the colour-scale box. */
  anriss_legend: AnrissLegend | null;
  /** Zoom to mount at when no pixel is selected; null: zoom 9. */
  initial_zoom: number | null;
  /** Area classes (m²) ticked on mount; null: all of them, empty: none ("Keine"). */
  initial_active_areas: number[] | null;
  /** The anriss that was open last, drawn with a blue ring; null: none. */
  highlight_id_anriss: number | null;
  /** The pixel "Pixel abwählen" last cleared, drawn as a square; null: none. */
  highlight_pixel: Pixel | null;
}

/** The value sent to Python when the user clicks "IFK berechnen". */
export interface ComputeIfkValue {
  x: number;
  y: number;
  /** Tells a fresh click apart from Streamlit repeating the last value on a rerun. */
  nonce: number;
  view: MapView;
  /** Names this map in app/ifk_prefetch.py, which the popup already asked to compute. */
  prefetch_client: string;
}

/** The value sent to Python when the user clicks "IFK berechnen" in the area popup. */
export interface ComputeAreaValue {
  /** The area on the map: Python may not have handled its drawing yet. */
  selection: Selection;
  compute: true;
  /** Tells a fresh click apart from Streamlit repeating the last value on a rerun. */
  nonce: number;
}
