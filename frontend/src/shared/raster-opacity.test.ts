import { afterEach, describe, expect, it, vi } from "vitest";

import {
  opacityPercent,
  pageOpacityMemory,
  rasterLayerStyle,
  type StyledMap,
  styleLayers,
} from "./raster-opacity";

/** A map with the layers `present`, recording every style change. */
function fakeMap(present: readonly string[]) {
  const layout = new Map<string, unknown>();
  const paint = new Map<string, unknown>();
  const map = {
    getLayer: (id: string) => (present.includes(id) ? { id } : undefined),
    setLayoutProperty: vi.fn((id: string, name: string, value: unknown) => {
      layout.set(`${id}.${name}`, value);
    }),
    setPaintProperty: vi.fn((id: string, name: string, value: unknown) => {
      paint.set(`${id}.${name}`, value);
    }),
  };
  return { map: map as unknown as StyledMap, layout, paint, calls: map };
}

describe("styleLayers", () => {
  it("hides the layer when the checkbox is unticked and shows it again", () => {
    const { map, layout } = fakeMap(["raster"]);
    styleLayers(map, ["raster"], false, 0.75);
    expect(layout.get("raster.visibility")).toBe("none");
    styleLayers(map, ["raster"], true, 0.75);
    expect(layout.get("raster.visibility")).toBe("visible");
  });

  it("sets the slider's opacity as raster-opacity", () => {
    const { map, paint } = fakeMap(["raster"]);
    styleLayers(map, ["raster"], true, 0.4);
    expect(paint.get("raster.raster-opacity")).toBe(0.4);
    styleLayers(map, ["raster"], true, 0);
    expect(paint.get("raster.raster-opacity")).toBe(0);
  });

  it("leaves the paint of a layer without a slider alone", () => {
    const { map, calls } = fakeMap(["outline"]);
    styleLayers(map, ["outline"], false);
    expect(calls.setLayoutProperty).toHaveBeenCalledWith("outline", "visibility", "none");
    expect(calls.setPaintProperty).not.toHaveBeenCalled();
  });

  it("skips a layer that isn't on the map yet", () => {
    const { map, calls } = fakeMap([]);
    styleLayers(map, ["raster"], true, 0.5);
    expect(calls.setLayoutProperty).not.toHaveBeenCalled();
    expect(calls.setPaintProperty).not.toHaveBeenCalled();
  });
});

describe("rasterLayerStyle", () => {
  it("adds a layer the way the checkbox and slider stand", () => {
    expect(rasterLayerStyle({ visible: true, opacity: 0.85 })).toEqual({
      layout: { visibility: "visible" },
      paint: { "raster-opacity": 0.85 },
    });
    expect(rasterLayerStyle({ visible: false, opacity: 0.3 }).layout.visibility).toBe("none");
  });
});

describe("opacityPercent", () => {
  it("reads the slider's value as a whole percent on its steps", () => {
    expect(opacityPercent("40", 75)).toBe(40);
    expect(opacityPercent("42", 75)).toBe(40);
    expect(opacityPercent(83, 75)).toBe(85);
  });

  it("keeps the value from 0 to 100", () => {
    expect(opacityPercent("-10", 75)).toBe(0);
    expect(opacityPercent("130", 75)).toBe(100);
  });

  it("falls back for a value that isn't a number", () => {
    expect(opacityPercent("", 75)).toBe(75);
    expect(opacityPercent("abc", 45)).toBe(45);
  });
});

describe("pageOpacityMemory", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the choice on the top window, so a remounted map finds it", () => {
    const top: Record<string, unknown> = {};
    vi.stubGlobal("window", { top });
    pageOpacityMemory().set("derivate", 30);
    expect(pageOpacityMemory().get("derivate")).toBe(30);
    expect(pageOpacityMemory().get("raster-overlay")).toBeUndefined();
    expect(top.__probeRasterOpacityPercent).toEqual({ derivate: 30 });
  });
});
