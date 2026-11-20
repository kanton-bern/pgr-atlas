// The one copy of the sidecar URL logic. pmtiles_server.py and
// derivate_bbox_server.py are reached in one of two ways:
// - no path prefix: same host as the page, the sidecar's own port;
// - a path prefix: same host and port as the page, under that path (an
//   ingress or nginx routes it), so no extra port has to be open.

import type { CoverageArgs, DerivateSidecarArgs, TileSidecarArgs } from "./types";

export interface Sidecar {
  port: number;
  pathPrefix: string;
}

/** The parts of `window.location` the URLs are built from. */
export type PageLocation = Pick<Location, "protocol" | "host" | "hostname">;

export function tileSidecar(args: TileSidecarArgs): Sidecar {
  return { port: args.pmtiles_port, pathPrefix: args.pmtiles_path_prefix };
}

export function derivateSidecar(args: DerivateSidecarArgs): Sidecar {
  return { port: args.derivate_bbox_server_port, pathPrefix: args.derivate_bbox_path_prefix };
}

/** Base URL of a sidecar, without a trailing slash. */
export function httpBase(sidecar: Sidecar, page: PageLocation = window.location): string {
  return sidecar.pathPrefix
    ? `${page.protocol}//${page.host}${sidecar.pathPrefix}`
    : `${page.protocol}//${page.hostname}:${String(sidecar.port)}`;
}

/** A PMTiles archive on the tile sidecar, for MapLibre's pmtiles:// protocol. */
export function pmtilesUrl(sidecar: Sidecar, filename: string, page?: PageLocation): string {
  return `pmtiles://${httpBase(sidecar, page)}/${filename}`;
}

/**
 * The gold coverage on the tile sidecar. The URL carries the version, so the
 * browser caches it for good and a new coverage gets a new URL. Null when
 * Python has no coverage published yet.
 */
export function coverageUrl(
  sidecar: Sidecar,
  { coverage_version: version }: CoverageArgs,
  page?: PageLocation,
): string | null {
  if (!version) return null;
  return `${httpBase(sidecar, page)}/coverage.geojson?v=${encodeURIComponent(version)}`;
}
