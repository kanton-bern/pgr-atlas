// How raster values and legend ticks are printed, and the Raster-Derivate
// colour ramps. The derivate pixels are coloured by derivate_bbox_server.py
// with the same scale, ramp, vmin and vmax this component gets, so the ramps
// here mirror raster_utils.py's RAMPS and MASK_COLOR.

import type { DerivateScale } from "@/raster_bbox_map/args";
import { formatNumber } from "@/shared/number-format";
import type { Locale } from "@/shared/texts";

type Rgb = readonly [number, number, number];

const VIRIDIS: readonly Rgb[] = [
  [68, 1, 84],
  [68, 57, 131],
  [49, 104, 142],
  [33, 145, 140],
  [53, 183, 121],
  [144, 215, 67],
  [253, 231, 37],
];
const RAMPS: Readonly<Record<string, readonly Rgb[]>> = {
  viridis: VIRIDIS,
  viridis_r: [...VIRIDIS].reverse(),
};
const MASK_COLOR: Rgb = [230, 85, 13];

function rgb(c: Rgb): string {
  return `rgb(${c.join(",")})`;
}

/** The CSS background of the legend bar; an unknown ramp is drawn as viridis. */
export function legendBarBackground(scale: DerivateScale, ramp: string | null): string {
  if (scale === "mask") return rgb(MASK_COLOR);
  const stops = RAMPS[ramp ?? "viridis"] ?? VIRIDIS;
  return `linear-gradient(to right, ${stops.map(rgb).join(", ")})`;
}

// Return periods extrapolate far out (up to 1e16 years): a power of ten from here.
const SCI_FROM = 1e6;

/**
 * A Raster-Karten hover value, like raster_overlay.py's _fmt_legend_value:
 * return periods (log scale, years) whole, or a power of ten past 1e6;
 * physical quantities with 2 decimals so small ones don't round to 0. Null
 * for nodata.
 */
export function formatHoverValue(v: number, logScale: boolean, locale: Locale): string | null {
  if (!Number.isFinite(v)) return null;
  return formatNumber(v, locale, logScale ? { sciFrom: SCI_FROM } : { digits: 2 });
}

/**
 * A Raster-Derivate value, readable across what the metrics span: return
 * periods up to 1e16 years, rates down to 1e-7 per year, probabilities 0..1.
 */
export function formatDerivateValue(
  v: number | null,
  scale: DerivateScale,
  locale: Locale,
): string {
  if (v === null || !Number.isFinite(v)) return "-";
  const magnitude = Math.abs(v);
  if (magnitude >= 100 || (magnitude > 0 && magnitude < 1e-3)) {
    return formatNumber(v, locale, { sciFrom: SCI_FROM });
  }
  if (scale === "log") return twoSignificantDigits(v, locale);
  return formatNumber(v, locale, { digits: magnitude >= 10 ? 1 : 2 });
}

/** `v` (from 0.001 to 100) to two significant digits, with as many decimals as they need. */
function twoSignificantDigits(v: number, locale: Locale): string {
  const rounded = Number(v.toPrecision(2));
  const digits = String(rounded).split(".")[1]?.length ?? 0;
  return formatNumber(rounded, locale, { digits });
}

function tickCount(vmin: number, vmax: number, scale: DerivateScale): number {
  if (scale !== "log") return 3;
  const decades = Math.log10(vmax) - Math.log10(vmin);
  const whole = Math.abs(decades - Math.round(decades)) < 1e-9;
  return whole && decades >= 2 && decades <= 5 ? Math.round(decades) + 1 : 4;
}

/**
 * Legend tick values, evenly spaced where the ramp is: in log10 for a log
 * scale, linearly otherwise, so each tick sits over its colour on the bar.
 * A log scale over 2 to 5 whole decades gets one tick per decade.
 */
export function derivateTickValues(vmin: number, vmax: number, scale: DerivateScale): number[] {
  const count = tickCount(vmin, vmax, scale);
  const low = scale === "log" ? Math.log10(vmin) : vmin;
  const high = scale === "log" ? Math.log10(vmax) : vmax;
  return Array.from({ length: count }, (_, tick) => {
    const at = low + (tick / (count - 1)) * (high - low);
    return scale === "log" ? 10 ** at : at;
  });
}
