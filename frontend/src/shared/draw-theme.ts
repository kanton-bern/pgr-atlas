// mapbox-gl-draw's theme with its "drawing" colour changed. The default orange
// is hard to see on the gold coverage and the orange Betroffen mask, so the
// selection's magenta: no viridis stop, mask or coverage layer is near it.

import MapboxDraw, { type DrawStyle } from "@mapbox/mapbox-gl-draw";

import { SELECTION_COLOR } from "@/shared/selection-color";

const THEME_ACTIVE = "#fbb03b";
export const DRAW_ACTIVE_COLOR = SELECTION_COLOR;

function replaceColor(value: unknown, from: string, to: string): unknown {
  if (value === from) return to;
  if (Array.isArray(value)) return value.map((v) => replaceColor(v, from, to));
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([k, v]) => [k, replaceColor(v, from, to)]),
    );
  }
  return value;
}

/** `theme` with every use of `from` replaced by `to`; the input is not changed. */
export function recolorTheme(theme: readonly DrawStyle[], from: string, to: string): DrawStyle[] {
  return theme.map((style) => replaceColor(style, from, to) as DrawStyle);
}

export function drawTheme(): DrawStyle[] {
  return recolorTheme(MapboxDraw.lib.theme, THEME_ACTIVE, DRAW_ACTIVE_COLOR);
}
