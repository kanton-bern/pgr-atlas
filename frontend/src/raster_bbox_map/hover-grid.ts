// The per-pixel values under a Raster-Karten overlay, for the hover tooltip.
// derivate_bbox_server.py serves them at /job/<id>/<var>.f32: little-endian
// float32, row-major from the north-west corner, NaN for nodata.

import type { HoverGeometry, RasterOverlay } from "@/raster_bbox_map/args";

/** The grid index of the pixel holding LV95 (E, N), or null outside the grid. */
export function hoverIndex(geom: HoverGeometry, east: number, north: number): number | null {
  const col = Math.floor((east - geom.xmin) / geom.res);
  const row = Math.floor((geom.ymax - north) / geom.res);
  if (col < 0 || col >= geom.width || row < 0 || row >= geom.height) return null;
  return row * geom.width + col;
}

async function fetchGrid(url: string, geom: HoverGeometry): Promise<Float32Array> {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${url} answered ${String(resp.status)}`);
  const data = new Float32Array(await resp.arrayBuffer());
  if (data.length !== geom.width * geom.height) {
    throw new Error(
      `hover grid has ${String(data.length)} values, expected ${String(geom.width * geom.height)}`,
    );
  }
  return data;
}

/**
 * Fetches each variable's grid once per job, so switching back to a variable
 * reuses it. A failed fetch is forgotten, so the next switch back retries.
 */
export class HoverGrids {
  private readonly cache = new Map<string, Promise<Float32Array>>();

  constructor(private readonly urlOf: (overlay: RasterOverlay) => string) {}

  get(overlay: RasterOverlay & { hover: HoverGeometry }): Promise<Float32Array> {
    const key = `${overlay.job_id}/${overlay.var}`;
    let grid = this.cache.get(key);
    if (!grid) {
      grid = fetchGrid(this.urlOf(overlay), overlay.hover);
      grid.catch(() => this.cache.delete(key));
      this.cache.set(key, grid);
    }
    return grid;
  }

  /** Forgets every grid: a new job's grids replace them. */
  clear(): void {
    this.cache.clear();
  }
}
