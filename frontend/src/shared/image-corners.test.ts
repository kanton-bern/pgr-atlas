import { describe, expect, it } from "vitest";

import { parseCorners } from "@/shared/image-corners";

const CORNERS = [
  [7.4, 46.9],
  [7.5, 46.9],
  [7.5, 46.8],
  [7.4, 46.8],
];

describe("parseCorners", () => {
  it("reads 4 [lon, lat] points", () => {
    expect(parseCorners(JSON.stringify(CORNERS))).toEqual(CORNERS);
  });

  it.each([
    ["no header", null],
    ["not JSON", "[7.4, 46.9"],
    ["3 points", JSON.stringify(CORNERS.slice(0, 3))],
    ["a point with 3 numbers", JSON.stringify([[7.4, 46.9, 0], ...CORNERS.slice(1)])],
    ["a string coordinate", JSON.stringify([["7.4", 46.9], ...CORNERS.slice(1)])],
    ["an object", JSON.stringify({ corners: CORNERS })],
  ])("is null for %s", (_name, header) => {
    expect(parseCorners(header)).toBeNull();
  });
});
