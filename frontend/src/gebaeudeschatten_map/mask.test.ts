import { describe, expect, it } from "vitest";

import type { MaskArgs } from "@/gebaeudeschatten_map/args";
import { maskKey, maskUrl } from "@/gebaeudeschatten_map/mask";
import type { PageLocation } from "@/shared/urls";

const MASK: MaskArgs = {
  metric: "gebaeudeschatten",
  partition: "strict_100_10",
  label: "Im Schatten",
  server_port: 8503,
  path_prefix: "",
};
const VIEW = { west: 7.4, south: 46.9, east: 7.5, north: 47 };
const SIZE = { width: 800, height: 600 };
const PAGE: PageLocation = {
  protocol: "https:",
  host: "atlas.example.ch:8443",
  hostname: "atlas.example.ch",
};

describe("maskUrl", () => {
  it("asks the derivate server for a purple mask crop of the view", () => {
    const url = new URL(maskUrl(MASK, VIEW, SIZE, PAGE));
    expect(url.origin).toBe("https://atlas.example.ch:8503");
    expect(url.pathname).toBe("/bbox.png");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      metric: "gebaeudeschatten",
      partition: "strict_100_10",
      band: "1",
      scale: "mask",
      mask_color: "purple",
      ramp: "viridis",
      vmin: "0",
      vmax: "1",
      west: "7.4",
      south: "46.9",
      east: "7.5",
      north: "47",
      width: "800",
      height: "600",
    });
  });

  it("uses the path prefix on the page's host", () => {
    const url = new URL(maskUrl({ ...MASK, path_prefix: "/bbox" }, VIEW, SIZE, PAGE));
    expect(url.host).toBe("atlas.example.ch:8443");
    expect(url.pathname).toBe("/bbox/bbox.png");
  });

  it("encodes the partition", () => {
    const url = new URL(maskUrl({ ...MASK, partition: "a&b=c" }, VIEW, SIZE, PAGE));
    expect(url.searchParams.get("partition")).toBe("a&b=c");
  });
});

describe("maskKey", () => {
  it("is null without a mask", () => {
    expect(maskKey(null)).toBeNull();
  });

  it("changes with the partition only when it changes", () => {
    expect(maskKey({ ...MASK })).toBe(maskKey(MASK));
    expect(maskKey({ ...MASK, partition: "strict_50_10" })).not.toBe(maskKey(MASK));
  });
});
