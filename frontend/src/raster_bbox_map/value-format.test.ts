import { describe, expect, it } from "vitest";

import {
  derivateTickValues,
  formatDerivateValue,
  formatHoverValue,
  legendBarBackground,
} from "@/raster_bbox_map/value-format";

describe("formatHoverValue", () => {
  it("is null for nodata", () => {
    expect(formatHoverValue(Number.NaN, false, "de-CH")).toBeNull();
    expect(formatHoverValue(Number.POSITIVE_INFINITY, true, "de-CH")).toBeNull();
  });

  it("keeps 2 decimals for physical quantities", () => {
    expect(formatHoverValue(0.004, false, "de-CH")).toBe("0.00");
    expect(formatHoverValue(3.25, false, "de-CH")).toBe("3.25");
  });

  it("prints return periods whole, and as a power of ten from 1e6", () => {
    expect(formatHoverValue(299.6, true, "de-CH")).toBe("300");
    expect(formatHoverValue(2.5e7, true, "de-CH")).toBe("2.5 × 10⁷");
  });
});

describe("formatDerivateValue", () => {
  it("prints a dash for no value", () => {
    expect(formatDerivateValue(null, "log", "de-CH")).toBe("-");
    expect(formatDerivateValue(Number.NaN, "linear", "de-CH")).toBe("-");
  });

  it("switches to a power of ten for very large and very small values", () => {
    expect(formatDerivateValue(1e14, "log", "de-CH")).toBe("1.0 × 10¹⁴");
    expect(formatDerivateValue(2e-7, "linear", "de-CH")).toBe("2.0 × 10⁻⁷");
    expect(formatDerivateValue(0, "linear", "de-CH")).toBe("0.00");
  });

  it("rounds by magnitude", () => {
    expect(formatDerivateValue(42, "log", "de-CH")).toBe("42");
    expect(formatDerivateValue(0.123, "log", "de-CH")).toBe("0.12");
    expect(formatDerivateValue(12.34, "linear", "de-CH")).toBe("12.3");
    expect(formatDerivateValue(0.456, "linear", "de-CH")).toBe("0.46");
    expect(formatDerivateValue(0.0012345, "log", "de-CH")).toBe("0.0012");
    expect(formatDerivateValue(99.7, "log", "de-CH")).toBe("100");
  });

  it("writes a decimal comma in fr-CH", () => {
    expect(formatDerivateValue(0.123, "log", "fr-CH")).toBe("0,12");
    expect(formatDerivateValue(12.34, "linear", "fr-CH")).toBe("12,3");
    expect(formatDerivateValue(1e14, "log", "fr-CH")).toBe("1,0 × 10¹⁴");
    expect(formatHoverValue(3.25, false, "fr-CH")).toBe("3,25");
    expect(formatHoverValue(4321, true, "fr-CH")).toBe("4 321");
  });
});

describe("derivateTickValues", () => {
  it("puts one tick on each decade of a whole-decade log range", () => {
    const ticks = derivateTickValues(100, 100000, "log");
    expect(ticks).toHaveLength(4);
    ticks.forEach((t, i) => {
      expect(t).toBeCloseTo(10 ** (i + 2), 6);
    });
  });

  it("uses 4 ticks for other log ranges", () => {
    expect(derivateTickValues(20, 1e14, "log")).toHaveLength(4);
    expect(derivateTickValues(1, 10, "log")).toHaveLength(4);
  });

  it("uses 3 evenly spaced ticks for a linear scale", () => {
    expect(derivateTickValues(0, 1, "linear")).toEqual([0, 0.5, 1]);
  });
});

describe("legendBarBackground", () => {
  it("is one colour for a mask", () => {
    expect(legendBarBackground("mask", null)).toBe("rgb(230,85,13)");
  });

  it("reverses viridis for viridis_r and falls back to viridis", () => {
    const forward = legendBarBackground("log", "viridis");
    expect(forward.startsWith("linear-gradient(to right, rgb(68,1,84)")).toBe(true);
    expect(
      legendBarBackground("log", "viridis_r").startsWith(
        "linear-gradient(to right, rgb(253,231,37)",
      ),
    ).toBe(true);
    expect(legendBarBackground("linear", "unknown")).toBe(forward);
  });
});
