// What a click on the Gebäudeschatten map selects. A building wins unless
// Shift is held; anything else selects the 5 m pixel under the click.

import type { ClickValue } from "@/gebaeudeschatten_map/args";
import { fromWgs, isPlausible, snapToPixel } from "@/shared/lv95";

/**
 * The value to send for a click at WGS84 `lat`/`lon`; `building` is the
 * id_start of the building under it, if any. Null outside Switzerland.
 */
export function clickValue(
  click: { lat: number; lon: number; shift: boolean; building: number | null },
  nonce: number,
): ClickValue | null {
  if (click.building !== null && !click.shift) {
    return { type: "building", id_start: click.building, nonce };
  }
  const { E, N } = fromWgs(click.lat, click.lon);
  if (!isPlausible(E, N)) return null;
  return { type: "pixel", e: snapToPixel(E), n: snapToPixel(N), nonce };
}
