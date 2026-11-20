// Validation for the coordinate search box (map-controls.ts).

import { isPlausible } from "./lv95";

/** The label key of each error the search box shows. */
export type SearchError = "search_error_format" | "search_error_outside";

/**
 * The error for the search box's X/Y input, or null when both are a
 * plausible LV95 point. The caller treats two empty fields as "nothing to do".
 */
export function searchInputError(xRaw: string, yRaw: string): SearchError | null {
  const east = Number.parseFloat(xRaw);
  const north = Number.parseFloat(yRaw);
  if (!Number.isFinite(east) || !Number.isFinite(north)) return "search_error_format";
  if (!isPlausible(east, north)) return "search_error_outside";
  return null;
}
