import { describe, expect, it } from "vitest";

import {
  formatLength,
  ringArea,
  ringBounds,
  selectionKey,
  sizeReadout,
  snappedRect,
  type ReadoutTexts,
} from "@/shared/selection-geometry";

// The German texts app/texts.toml holds for the readout.
const LABELS: ReadoutTexts["labels"] = {
  length_m: "{value} m",
  length_km: "{value} km",
  selection_size_rect: "{width} × {height} · {area} m²",
  selection_size_polygon: "Polygon ({vertices} Eckpunkte) · {width} × {height} · {area} m²",
};
const DE: ReadoutTexts = { labels: LABELS, locale: "de-CH" };
const FR: ReadoutTexts = { labels: LABELS, locale: "fr-CH" };

describe("snappedRect", () => {
  it("snaps the corners to pixel centres and closes the ring", () => {
    const selection = snappedRect([2600013, 1200021], [2600001, 1200004]);
    expect(selection).toEqual({
      type: "bbox",
      ring: [
        [2600002.5, 1200002.5],
        [2600012.5, 1200002.5],
        [2600012.5, 1200022.5],
        [2600002.5, 1200022.5],
        [2600002.5, 1200002.5],
      ],
    });
  });

  it("is null for a drag that snaps to a line", () => {
    expect(snappedRect([2600001, 1200001], [2600003, 1200030])).toBeNull();
    expect(snappedRect([2600001, 1200001], [2600001, 1200001])).toBeNull();
  });
});

describe("ringArea and ringBounds", () => {
  const triangle: [number, number][] = [
    [0, 0],
    [10, 0],
    [0, 20],
    [0, 0],
  ];

  it("measures a closed or open ring alike", () => {
    expect(ringArea(triangle)).toBe(100);
    expect(ringArea(triangle.slice(0, 3))).toBe(100);
  });

  it("bounds every point", () => {
    expect(ringBounds(triangle)).toEqual({ xmin: 0, ymin: 0, xmax: 10, ymax: 20 });
  });
});

describe("readouts", () => {
  it("prints metres below 1 km and km from there", () => {
    expect(formatLength(999.4, DE)).toBe("999 m");
    expect(formatLength(999.6, DE)).toBe("1000 m");
    expect(formatLength(16730, DE)).toBe("16.73 km");
    expect(formatLength(1234567, DE)).toBe("1234.57 km");
  });

  it("shows a rectangle's size and area", () => {
    const text = sizeReadout({ xmin: 0, ymin: 0, xmax: 1500, ymax: 400 }, DE);
    expect(text).toBe("1.50 km × 400 m · 600'000 m²");
  });

  it("writes fr-CH numbers: a decimal comma, a narrow no-break space grouping the area", () => {
    expect(formatLength(16730, FR)).toBe("16,73 km");
    const text = sizeReadout({ xmin: 0, ymin: 0, xmax: 1500, ymax: 400 }, FR);
    expect(text).toBe("1,50 km × 400 m · 600 000 m²");
  });

  it("names a polygon's vertices", () => {
    const bounds = { xmin: 0, ymin: 0, xmax: 95, ymax: 45 };
    expect(sizeReadout(bounds, DE, { vertices: 4, area: 4275 })).toBe(
      "Polygon (4 Eckpunkte) · 95 m × 45 m · 4'275 m²",
    );
  });
});

describe("selectionKey", () => {
  it("is the same for the same ring and null for none", () => {
    const ring: [number, number][] = [
      [1, 2],
      [3, 4],
    ];
    expect(selectionKey({ type: "bbox", ring })).toBe(
      selectionKey({ type: "bbox", ring: [...ring] }),
    );
    expect(selectionKey(null)).toBeNull();
  });
});
