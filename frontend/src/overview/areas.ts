// How the overview draws the anriss area classes: colours and draw order.

import type { DataDrivenPropertyValueSpecification, ExpressionSpecification } from "maplibre-gl";

import { AREA_CLASSES } from "@/shared/anriss-areas";

/** The tiles' property that holds the Anrissfläche. */
export const AREA_PROPERTY = "A";

/** A step at each class's own value, so each A gets its class's colour. */
export const AREA_COLOR_EXPR: ExpressionSpecification = [
  "step",
  ["get", AREA_PROPERTY],
  AREA_CLASSES[0]?.color ?? "#000000",
  ...AREA_CLASSES.slice(1).flatMap((c) => [c.area, c.color]),
];

/**
 * Circles overlap, and a higher sort key draws on top, so -A puts smaller
 * circles in front of larger ones.
 */
export const AREA_SORT_KEY: DataDrivenPropertyValueSpecification<number> = [
  "-",
  0,
  ["get", AREA_PROPERTY],
];
