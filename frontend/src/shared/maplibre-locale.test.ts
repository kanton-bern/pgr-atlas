import { describe, expect, it } from "vitest";

import { MAPLIBRE_LABELS, maplibreLocale } from "@/shared/maplibre-locale";

describe("maplibreLocale", () => {
  it("gives every MapLibre UI string the text of its own label", () => {
    const labels = Object.fromEntries(MAPLIBRE_LABELS.map((k) => [k, `text of ${k}`]));
    const locale = maplibreLocale(labels as Parameters<typeof maplibreLocale>[0]);
    expect(Object.keys(locale)).toHaveLength(MAPLIBRE_LABELS.length);
    expect(new Set(MAPLIBRE_LABELS).size).toBe(MAPLIBRE_LABELS.length);
    expect(locale["NavigationControl.ZoomIn"]).toBe("text of maplibre_zoom_in");
    expect(locale["Popup.Close"]).toBe("text of maplibre_popup_close");
    expect(locale["Map.Title"]).toBe("text of maplibre_map");
  });
});
