import { afterEach, describe, expect, it, vi } from "vitest";

import type { HoverGeometry, RasterOverlay } from "@/raster_bbox_map/args";
import { HoverGrids, hoverIndex } from "@/raster_bbox_map/hover-grid";

const GEOM: HoverGeometry = { width: 3, height: 2, xmin: 1000, ymax: 2000, res: 5 };

describe("hoverIndex", () => {
  it("counts rows from the north edge", () => {
    expect(hoverIndex(GEOM, 1000, 2000)).toBe(0);
    expect(hoverIndex(GEOM, 1014.9, 1995.1)).toBe(2);
    expect(hoverIndex(GEOM, 1000, 1995)).toBe(3);
    expect(hoverIndex(GEOM, 1014.9, 1990.1)).toBe(5);
  });

  it("is null outside the grid, edges included", () => {
    expect(hoverIndex(GEOM, 999.9, 1999)).toBeNull();
    expect(hoverIndex(GEOM, 1015, 1999)).toBeNull();
    expect(hoverIndex(GEOM, 1001, 2000.1)).toBeNull();
    expect(hoverIndex(GEOM, 1001, 1990)).toBeNull();
  });
});

function overlay(job_id: string, variable: string): RasterOverlay & { hover: HoverGeometry } {
  return {
    job_id,
    var: variable,
    corners: [
      [0, 0],
      [0, 0],
      [0, 0],
      [0, 0],
    ],
    gradient: "",
    label: "",
    unit: "",
    log_scale: false,
    vmin_label: "",
    vmid_label: "",
    vmax_label: "",
    hover: { ...GEOM, width: 2, height: 1 },
  };
}

function answer(values: number[], status = 200): Response {
  return new Response(new Float32Array(values).buffer, { status });
}

describe("HoverGrids", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches each job's variable once", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(answer([1.5, Number.NaN])));
    vi.stubGlobal("fetch", fetchMock);
    const grids = new HoverGrids((o) => `/job/${o.job_id}/${o.var}.f32`);

    const first = await grids.get(overlay("a", "depth"));
    await grids.get(overlay("a", "depth"));
    await grids.get(overlay("a", "velocity"));
    expect(first[0]).toBe(1.5);
    expect(Number.isNaN(first[1])).toBe(true);
    expect(fetchMock.mock.calls.map((c: unknown[]) => c[0])).toEqual([
      "/job/a/depth.f32",
      "/job/a/velocity.f32",
    ]);
  });

  it("rejects an error answer or a grid of the wrong size, and retries after it", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(answer([], 404))
      .mockResolvedValueOnce(answer([1, 2, 3]))
      .mockResolvedValueOnce(answer([1, 2]));
    vi.stubGlobal("fetch", fetchMock);
    const grids = new HoverGrids(() => "/job/a/depth.f32");

    await expect(grids.get(overlay("a", "depth"))).rejects.toThrow("answered 404");
    await expect(grids.get(overlay("a", "depth"))).rejects.toThrow("3 values, expected 2");
    await expect(grids.get(overlay("a", "depth"))).resolves.toHaveLength(2);
  });
});
