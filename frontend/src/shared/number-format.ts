// The app's one number format, the same as app/ui_text.py's fmt_ch, in the
// locale Python sends. de-CH: ' groups thousands (2'584) and "." is the
// decimal point; fr-CH: a narrow no-break space groups (2 584) and "," is the
// decimal comma, as Intl writes fr-CH. A value below 0.001 (or from `sciFrom`
// on) is a power of ten with one decimal (8.4 × 10⁻⁸).

import type { Locale } from "@/shared/texts";

const SUPERSCRIPT: Readonly<Record<string, string>> = {
  "-": "⁻",
  "0": "⁰",
  "1": "¹",
  "2": "²",
  "3": "³",
  "4": "⁴",
  "5": "⁵",
  "6": "⁶",
  "7": "⁷",
  "8": "⁸",
  "9": "⁹",
};
// Below this a plain decimal is mostly zeros: 0.00000008 reads as 8.0 × 10⁻⁸.
const SCI_BELOW = 1e-3;

/**
 * The separators per locale. Written out, not taken from Intl: browsers write
 * de-CH's group as ' or ’ depending on their CLDR version, and the app writes '.
 */
export const SEPARATORS: Readonly<Record<Locale, { group: string; decimal: string }>> = {
  "de-CH": { group: "'", decimal: "." },
  "fr-CH": { group: " ", decimal: "," },
};

export interface NumberFormat {
  /** Decimals of a plain number (default 0). */
  digits?: number;
  /** The magnitude from which a large number is a power of ten, too (default never). */
  sciFrom?: number;
  /** Whether thousands are grouped (default true); false for coordinates and lengths. */
  group?: boolean;
}

function powerOfTen(v: number, decimal: string): string {
  const [mantissa = "", exponent = ""] = v.toExponential(1).split("e");
  const superscript = String(Number(exponent)).replace(/[-\d]/g, (c) => SUPERSCRIPT[c] ?? c);
  return `${mantissa.replace(".", decimal)} × 10${superscript}`;
}

function needsPowerOfTen(magnitude: number, sciFrom: number): boolean {
  return (magnitude > 0 && magnitude < SCI_BELOW) || magnitude >= sciFrom;
}

function plainNumber(v: number, digits: number, locale: Locale, group: boolean): string {
  const sep = SEPARATORS[locale];
  const fixed = v.toFixed(digits);
  // -0.004 rounds to "-0.00": a zero has no sign.
  const unsigned = Number(fixed) === 0 ? fixed.replace("-", "") : fixed;
  const grouped = group
    ? unsigned.replace(/^-?\d+/, (whole) => whole.replace(/\B(?=(\d{3})+(?!\d))/g, sep.group))
    : unsigned;
  return grouped.replace(".", sep.decimal);
}

/** `v` in the app's format for `locale`; null, NaN and ±Infinity read "-". */
export function formatNumber(
  v: number | null,
  locale: Locale,
  { digits = 0, sciFrom = Infinity, group = true }: NumberFormat = {},
): string {
  if (v === null || !Number.isFinite(v)) return "-";
  if (needsPowerOfTen(Math.abs(v), sciFrom)) return powerOfTen(v, SEPARATORS[locale].decimal);
  return plainNumber(v, digits, locale, group);
}
