import { describe, expect, it } from "vitest";

import { AREA_CLASSES, areaFilter, initialAreas } from "@/shared/anriss-areas";

const ALL = AREA_CLASSES.map((c) => c.area);

describe("areaFilter", () => {
  it("has no filter when every class is ticked", () => {
    expect(areaFilter(new Set(ALL), "A")).toBeNull();
  });

  it("matches nothing when no class is ticked", () => {
    expect(areaFilter(new Set(), "A")).toEqual(["==", ["get", "A"], -1]);
  });

  it("keeps only the ticked classes", () => {
    expect(areaFilter(new Set([125, 1100]), "anrissflaeche")).toEqual([
      "in",
      ["get", "anrissflaeche"],
      ["literal", [125, 1100]],
    ]);
  });

  it("filters when a value outside the classes replaces one of them", () => {
    const set = new Set([...ALL.slice(1), 999]);
    expect(areaFilter(set, "A")).toEqual(["in", ["get", "A"], ["literal", [...set]]]);
  });
});

describe("initialAreas", () => {
  it("ticks every class when Python sends null", () => {
    expect([...initialAreas(null)]).toEqual(ALL);
    expect([...initialAreas(undefined)]).toEqual(ALL);
  });

  it("ticks no class for an empty list, so 'Keine' survives a remount", () => {
    expect(initialAreas([]).size).toBe(0);
  });

  it("ticks only the classes Python sends", () => {
    expect([...initialAreas([55, 700])]).toEqual([55, 700]);
  });
});
