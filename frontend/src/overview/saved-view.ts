// The last map view, in localStorage. Python restores the view after an
// "Anriss öffnen" click (initial_zoom), but not after an anriss picked by ID in
// the sidebar. localStorage survives Streamlit unmounting this iframe, so the
// map comes back where it was in that case too.

import type { MapView } from "@/shared/types";

const SAVED_VIEW_KEY = "pgr_atlas_overview_last_view";

/** The subset of Storage used here (a Map-backed fake in the tests). */
export type ViewStorage = Pick<Storage, "getItem" | "setItem">;

function isMapView(value: unknown): value is MapView {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.lat === "number" && typeof v.lon === "number" && typeof v.zoom === "number";
}

/**
 * The saved view, or null if there is none, it is malformed, or storage is
 * blocked (a browser setting, where localStorage throws).
 */
export function readSavedView(storage: () => ViewStorage = () => localStorage): MapView | null {
  try {
    const raw = storage().getItem(SAVED_VIEW_KEY);
    const parsed: unknown = raw === null ? null : JSON.parse(raw);
    return isMapView(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/** Saves the view; does nothing when storage is blocked or full. */
export function saveView(view: MapView, storage: () => ViewStorage = () => localStorage): void {
  try {
    storage().setItem(SAVED_VIEW_KEY, JSON.stringify(view));
  } catch {
    // The saved view is a convenience; the map works without it.
  }
}
