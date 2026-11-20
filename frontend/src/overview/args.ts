// Render args of the overview (app/overview_component.py, maplibre_overview).
// Python sends every key; None arrives as null.

import { AREA_LEGEND_LABELS } from "@/shared/area-legend";
import { CHROME_LABELS, PROZESSQUELLE_LABELS } from "@/shared/map-controls";
import type { TextArgs } from "@/shared/texts";
import type { CoverageArgs, TileSidecarArgs } from "@/shared/types";

/** Every label the overview takes in `labels`. */
export const OVERVIEW_LABELS = [
  ...CHROME_LABELS,
  ...PROZESSQUELLE_LABELS,
  "layers",
  "area",
  ...AREA_LEGEND_LABELS,
  "gold_coverage",
  "prozessquellen",
  "anriss_popup_title",
  "anriss_popup_area",
  "anriss_popup_prozessquelle",
  "anriss_open",
] as const;

export interface OverviewArgs extends TileSidecarArgs, CoverageArgs, TextArgs {
  center_lat: number;
  center_lon: number;
  /** Null: DEFAULT_PMTILES_FILENAME. */
  pmtiles_filename: string | null;
  /** Null: DEFAULT_SOURCE_LAYER. */
  source_layer: string | null;
  /** Start view (last click or a link, views/overview.py); null: saved view, else zoom 8. */
  initial_zoom: number | null;
  /** Area classes (m²) ticked on mount; null: all of them, empty: none ("Keine"). */
  initial_active_areas: number[] | null;
  /** The anriss that was open last, drawn with a blue ring; null: none. */
  highlight_id_anriss: number | null;
}
