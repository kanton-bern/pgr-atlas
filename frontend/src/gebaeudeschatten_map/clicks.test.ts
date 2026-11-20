import { describe, expect, it } from "vitest";

import { clickValue } from "@/gebaeudeschatten_map/clicks";
import { toWgs } from "@/shared/lv95";

// A point inside a 5 m pixel whose centre is (2600002.5, 1200002.5).
const INSIDE = toWgs(2600001.2, 1200004.1);

describe("clickValue", () => {
  it("selects the building under the click", () => {
    expect(clickValue({ ...INSIDE, shift: false, building: 42 }, 7)).toEqual({
      type: "building",
      id_start: 42,
      nonce: 7,
    });
  });

  it.each([
    ["no building", false, null],
    ["Shift over a building", true, 42],
  ])("selects the pixel centre for %s", (_name, shift, building) => {
    const value = clickValue({ ...INSIDE, shift, building }, 7);
    expect(value).toMatchObject({ type: "pixel", nonce: 7 });
    expect(value).toHaveProperty("e", 2600002.5);
    expect(value).toHaveProperty("n", 1200002.5);
  });

  it("ignores a click outside Switzerland", () => {
    expect(clickValue({ lat: 52.5, lon: 13.4, shift: false, building: null }, 7)).toBeNull();
  });
});
