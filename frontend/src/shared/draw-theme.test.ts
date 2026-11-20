import MapboxDraw from "@mapbox/mapbox-gl-draw";
import { describe, expect, it } from "vitest";

import { DRAW_ACTIVE_COLOR, drawTheme, recolorTheme } from "@/shared/draw-theme";

describe("drawTheme", () => {
  it("draws in light blue, not the default orange", () => {
    const text = JSON.stringify(drawTheme());
    expect(text).not.toContain("#fbb03b");
    expect(text).toContain(DRAW_ACTIVE_COLOR);
  });

  it("keeps every layer of the default theme", () => {
    expect(drawTheme().map((s) => s.id)).toEqual(MapboxDraw.lib.theme.map((s) => s.id));
  });

  it("leaves the default theme unchanged", () => {
    const before = JSON.stringify(MapboxDraw.lib.theme);
    drawTheme();
    expect(JSON.stringify(MapboxDraw.lib.theme)).toBe(before);
  });
});

describe("recolorTheme", () => {
  it("replaces the colour inside expressions", () => {
    const [style] = recolorTheme(
      [
        {
          id: "x",
          type: "fill",
          paint: { "fill-color": ["case", ["==", ["get", "active"], "true"], "#f00", "#00f"] },
        },
      ],
      "#f00",
      "#0f0",
    );
    expect(style).toEqual({
      id: "x",
      type: "fill",
      paint: { "fill-color": ["case", ["==", ["get", "active"], "true"], "#0f0", "#00f"] },
    });
  });
});
