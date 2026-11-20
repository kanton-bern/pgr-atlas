import { describe, expect, it } from "vitest";

import { AREA_COLOR_EXPR } from "@/overview/areas";

describe("AREA_COLOR_EXPR", () => {
  it("steps at each class value to that class's colour", () => {
    expect(AREA_COLOR_EXPR).toEqual([
      "step",
      ["get", "A"],
      "#228B22",
      125,
      "#9ACD32",
      250,
      "#FFD700",
      400,
      "#FFA500",
      700,
      "#FF4500",
      1100,
      "#8B0000",
    ]);
  });
});
