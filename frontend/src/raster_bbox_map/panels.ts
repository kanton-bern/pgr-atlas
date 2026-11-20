// The raster legend (bottom centre) and the pixel tooltip. Raster-Karten and
// Raster-Derivate share both: the two never run in the same component
// instance. Every value is set as text.

import type { PointLike } from "maplibre-gl";

import type { DerivateScale, RasterOverlay, RasterTexts } from "@/raster_bbox_map/args";
import { fill } from "@/shared/texts";
import {
  derivateTickValues,
  formatDerivateValue,
  legendBarBackground,
} from "@/raster_bbox_map/value-format";

function element(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`raster_bbox_map: #${id} is missing from index.html`);
  return el;
}

function setTicks(labels: readonly string[]): void {
  const ticks = element("rl-ticks");
  ticks.replaceChildren(
    ...labels.map((label) => {
      const span = document.createElement("span");
      span.textContent = label;
      return span;
    }),
  );
}

function showLegend(title: string, bar: string, ticks: readonly string[], note: string): void {
  element("rl-title").textContent = title;
  element("rl-bar").style.background = bar;
  setTicks(ticks);
  element("rl-note").textContent = note;
  element("raster-legend").hidden = false;
}

export function hideLegend(): void {
  element("raster-legend").hidden = true;
}

export function showOverlayLegend(overlay: RasterOverlay, { labels }: RasterTexts): void {
  showLegend(
    fill(labels.legend_title_unit, { label: overlay.label, unit: overlay.unit }),
    `linear-gradient(to right, ${overlay.gradient})`,
    [overlay.vmin_label, overlay.vmid_label, overlay.vmax_label],
    overlay.log_scale ? labels.log_scale : "",
  );
}

/** The colour style of the Raster-Derivate layer, as Python sends it. */
export interface DerivateStyle {
  label: string;
  unit: string | null;
  scale: DerivateScale;
  ramp: string | null;
  vmin: number | null;
  vmax: number | null;
  note: string | null;
}

function derivateTicks(style: DerivateStyle, texts: RasterTexts): string[] {
  if (style.scale === "mask") return [texts.labels.mask_ticks];
  if (style.vmin === null || style.vmax === null) return [];
  return derivateTickValues(style.vmin, style.vmax, style.scale).map((v) =>
    formatDerivateValue(v, style.scale, texts.locale),
  );
}

export function showDerivateLegend(style: DerivateStyle, texts: RasterTexts): void {
  const { label, unit } = style;
  showLegend(
    unit ? fill(texts.labels.legend_title_unit, { label, unit }) : label,
    legendBarBackground(style.scale, style.ramp),
    derivateTicks(style, texts),
    style.note ?? "",
  );
}

/** Shows `text` next to the pointer; `point` is in map-container pixels. */
export function showTooltip(text: string, point: PointLike): void {
  const tooltip = element("pixel-tooltip");
  const [x, y] = Array.isArray(point) ? point : [point.x, point.y];
  tooltip.textContent = text;
  tooltip.style.left = `${String(x + 14)}px`;
  tooltip.style.top = `${String(y + 14)}px`;
  tooltip.hidden = false;
}

export function hideTooltip(): void {
  element("pixel-tooltip").hidden = true;
}
