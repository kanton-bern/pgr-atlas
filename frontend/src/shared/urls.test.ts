import { describe, expect, it } from "vitest";

import {
  coverageUrl,
  derivateSidecar,
  httpBase,
  pmtilesUrl,
  tileSidecar,
  type PageLocation,
} from "./urls";

const page: PageLocation = {
  protocol: "https:",
  host: "atlas.example.ch:8443",
  hostname: "atlas.example.ch",
};
const byPort = { port: 8505, pathPrefix: "" };
const byPrefix = { port: 8505, pathPrefix: "/tiles" };

describe("httpBase", () => {
  it("uses the page's hostname and the sidecar's port without a prefix", () => {
    expect(httpBase(byPort, page)).toBe("https://atlas.example.ch:8505");
  });

  it("uses the page's host and port and the prefix when one is set", () => {
    expect(httpBase(byPrefix, page)).toBe("https://atlas.example.ch:8443/tiles");
  });

  it("keeps the page's protocol", () => {
    expect(httpBase(byPort, { ...page, protocol: "http:" })).toBe("http://atlas.example.ch:8505");
  });
});

describe("sidecars from render args", () => {
  it("reads the tile sidecar", () => {
    expect(tileSidecar({ pmtiles_port: 18505, pmtiles_path_prefix: "/pm" })).toEqual({
      port: 18505,
      pathPrefix: "/pm",
    });
  });

  it("reads the derivate sidecar", () => {
    const args = { derivate_bbox_server_port: 18503, derivate_bbox_path_prefix: "" };
    expect(derivateSidecar(args)).toEqual({ port: 18503, pathPrefix: "" });
  });
});

describe("pmtilesUrl", () => {
  it("prefixes the HTTP URL with pmtiles://", () => {
    expect(pmtilesUrl(byPort, "prozessquelle.pmtiles", page)).toBe(
      "pmtiles://https://atlas.example.ch:8505/prozessquelle.pmtiles",
    );
    expect(pmtilesUrl(byPrefix, "a.pmtiles", page)).toBe(
      "pmtiles://https://atlas.example.ch:8443/tiles/a.pmtiles",
    );
  });
});

describe("coverageUrl", () => {
  it("adds the encoded version as the query", () => {
    expect(coverageUrl(byPrefix, { coverage_version: "ab12&x" }, page)).toBe(
      "https://atlas.example.ch:8443/tiles/coverage.geojson?v=ab12%26x",
    );
  });

  it("is null while no coverage is published", () => {
    expect(coverageUrl(byPort, { coverage_version: null }, page)).toBeNull();
    expect(coverageUrl(byPort, { coverage_version: "" }, page)).toBeNull();
  });
});
