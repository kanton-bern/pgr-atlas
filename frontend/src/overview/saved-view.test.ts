import { describe, expect, it } from "vitest";

import { readSavedView, saveView, type ViewStorage } from "@/overview/saved-view";

function fakeStorage(): ViewStorage & { items: Map<string, string> } {
  const items = new Map<string, string>();
  return {
    items,
    getItem: (key) => items.get(key) ?? null,
    setItem: (key, value) => {
      items.set(key, value);
    },
  };
}

const blocked = (): ViewStorage => {
  throw new DOMException("The operation is insecure.", "SecurityError");
};

describe("saved view", () => {
  it("round-trips a view", () => {
    const storage = fakeStorage();
    saveView({ lat: 46.6, lon: 7.6, zoom: 12.5 }, () => storage);
    expect(readSavedView(() => storage)).toEqual({ lat: 46.6, lon: 7.6, zoom: 12.5 });
  });

  it("uses the key the old page used, so a saved view survives the port", () => {
    const storage = fakeStorage();
    saveView({ lat: 1, lon: 2, zoom: 3 }, () => storage);
    expect([...storage.items.keys()]).toEqual(["pgr_atlas_overview_last_view"]);
  });

  it("is null without a saved view", () => {
    expect(readSavedView(() => fakeStorage())).toBeNull();
  });

  it.each([
    ["not JSON", "{"],
    ["JSON null", "null"],
    ["a missing field", '{"lat": 46.6, "lon": 7.6}'],
    ["a string number", '{"lat": "46.6", "lon": 7.6, "zoom": 8}'],
  ])("is null for %s", (_, raw) => {
    const storage = fakeStorage();
    storage.items.set("pgr_atlas_overview_last_view", raw);
    expect(readSavedView(() => storage)).toBeNull();
  });

  it("is null and saves nothing when storage is blocked", () => {
    expect(readSavedView(blocked)).toBeNull();
    expect(() => {
      saveView({ lat: 1, lon: 2, zoom: 3 }, blocked);
    }).not.toThrow();
  });
});
