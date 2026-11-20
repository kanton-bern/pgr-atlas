// Asks the tile sidecar to start work while a popup is open, so the button in
// the popup usually finds the result ready. Nothing waits for the answer: on
// failure the view does the work itself when the user clicks.

import { httpBase, type Sidecar } from "@/shared/urls";

function post(url: string): void {
  fetch(url, { method: "POST", keepalive: true }).catch(() => undefined);
}

/** Reads the anriss's data for "Anriss öffnen" (app/anriss_prefetch.py). */
export function prefetchAnriss(tiles: Sidecar, idAnriss: number): void {
  post(`${httpBase(tiles)}/prefetch?id_anriss=${encodeURIComponent(idAnriss)}`);
}

/**
 * Computes the pixel's IFK for "IFK berechnen" (app/ifk_prefetch.py). `client`
 * names the map, so a new pixel replaces that map's previous one there.
 */
export function prefetchIfk(tiles: Sidecar, x: number, y: number, client: string): void {
  const query = new URLSearchParams({ x: String(x), y: String(y), client });
  post(`${httpBase(tiles)}/prefetch-ifk?${query.toString()}`);
}
