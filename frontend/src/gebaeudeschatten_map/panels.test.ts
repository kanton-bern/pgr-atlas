import { describe, expect, it } from "vitest";

import { stripes } from "@/gebaeudeschatten_map/panels";

describe("stripes", () => {
  it("shows the first three key colours as equal stripes", () => {
    const key = ["#111", "#222", "#333", "#444"].map((color) => ({ color, label: color }));
    expect(stripes(key)).toBe("linear-gradient(to right,#111 0% 33%,#222 33% 66%,#333 66% 99%)");
  });
});
