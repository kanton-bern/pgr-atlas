import { describe, expect, it } from "vitest";

import { formatNumber } from "@/shared/number-format";

describe("formatNumber", () => {
  it("prints a dash for no value", () => {
    expect(formatNumber(null, "de-CH")).toBe("-");
    expect(formatNumber(Number.NaN, "de-CH")).toBe("-");
    expect(formatNumber(Number.POSITIVE_INFINITY, "de-CH")).toBe("-");
    expect(formatNumber(Number.NEGATIVE_INFINITY, "de-CH", { digits: 2 })).toBe("-");
  });

  it("groups thousands with an apostrophe", () => {
    expect(formatNumber(0, "de-CH")).toBe("0");
    expect(formatNumber(999, "de-CH")).toBe("999");
    expect(formatNumber(1000, "de-CH")).toBe("1'000");
    expect(formatNumber(2584, "de-CH")).toBe("2'584");
    expect(formatNumber(257579577, "de-CH")).toBe("257'579'577");
    expect(formatNumber(-1234567.891, "de-CH", { digits: 2 })).toBe("-1'234'567.89");
  });

  it("rounds to the given decimals, without a sign on zero", () => {
    expect(formatNumber(999.5, "de-CH")).toBe("1'000");
    expect(formatNumber(0.004, "de-CH", { digits: 2 })).toBe("0.00");
    expect(formatNumber(-0.004, "de-CH", { digits: 2 })).toBe("0.00");
    expect(formatNumber(-0.4, "de-CH")).toBe("0");
    expect(formatNumber(0.001, "de-CH", { digits: 3 })).toBe("0.001");
  });

  it("writes values below 0.001 as a power of ten", () => {
    expect(formatNumber(8.4e-8, "de-CH")).toBe("8.4 × 10⁻⁸");
    expect(formatNumber(3.88e-9, "de-CH", { digits: 3 })).toBe("3.9 × 10⁻⁹");
    expect(formatNumber(-2e-7, "de-CH")).toBe("-2.0 × 10⁻⁷");
    expect(formatNumber(0.000999, "de-CH")).toBe("1.0 × 10⁻³");
    expect(formatNumber(1.5e-12, "de-CH")).toBe("1.5 × 10⁻¹²");
  });

  it("writes large values as a power of ten only from sciFrom", () => {
    expect(formatNumber(7.5e6, "de-CH")).toBe("7'500'000");
    expect(formatNumber(999_999, "de-CH", { sciFrom: 1e6 })).toBe("999'999");
    expect(formatNumber(1e6, "de-CH", { sciFrom: 1e6 })).toBe("1.0 × 10⁶");
    expect(formatNumber(2.2e10, "de-CH", { sciFrom: 1e6 })).toBe("2.2 × 10¹⁰");
    expect(formatNumber(-3e7, "de-CH", { sciFrom: 1e6 })).toBe("-3.0 × 10⁷");
  });

  it("leaves thousands ungrouped on request", () => {
    expect(formatNumber(2600002.5, "de-CH", { digits: 1, group: false })).toBe("2600002.5");
    expect(formatNumber(2600002.5, "fr-CH", { digits: 1, group: false })).toBe("2600002,5");
  });
});

describe("formatNumber in fr-CH", () => {
  // U+202F, the narrow no-break space Intl groups fr-CH with.
  const NNBSP = "\u202f";

  it("groups with a narrow no-break space and writes a decimal comma", () => {
    expect(formatNumber(999, "fr-CH")).toBe("999");
    expect(formatNumber(2584, "fr-CH")).toBe(`2${NNBSP}584`);
    expect(formatNumber(-1234567.891, "fr-CH", { digits: 2 })).toBe(`-1${NNBSP}234${NNBSP}567,89`);
    expect(formatNumber(-0.004, "fr-CH", { digits: 2 })).toBe("0,00");
  });

  it("writes a power of ten with a decimal comma", () => {
    expect(formatNumber(8.4e-8, "fr-CH")).toBe("8,4 × 10⁻⁸");
    expect(formatNumber(2.2e10, "fr-CH", { sciFrom: 1e6 })).toBe("2,2 × 10¹⁰");
  });
});
