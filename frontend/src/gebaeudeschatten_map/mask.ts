// The affected mask: derivate_bbox_server.py crops the canton mosaic of the
// chosen variant, reach and depth to the visible part of the map, coloured as
// a mask. One image source, replaced after each move.

import type { Map as MapLibreMap } from "maplibre-gl";

import type { MaskArgs } from "@/gebaeudeschatten_map/args";
import { type Corners, parseCorners } from "@/shared/image-corners";
import type { MapStatus } from "@/shared/map-controls";
import { rasterLayerStyle, type RasterStyle } from "@/shared/raster-opacity";
import { httpBase, type PageLocation } from "@/shared/urls";

export const MASK_LAYER = "mask-image";
/** The mask's opacity until the user moves the layer box's slider. */
export const MASK_OPACITY_PERCENT = 45;
// No request per frame while the user drags.
const DEBOUNCE_MS = 250;

/** Where a failed crop is reported, and with which text. */
export interface MaskErrors {
  status: MapStatus;
  text: () => string;
}

/** The crop URL of `mask` for a view; the server snaps it to its pixels. */
export function maskUrl(
  mask: MaskArgs,
  view: { west: number; south: number; east: number; north: number },
  size: { width: number; height: number },
  page?: PageLocation,
): string {
  const query = new URLSearchParams({
    metric: mask.metric,
    partition: mask.partition,
    band: "1",
    scale: "mask",
    mask_color: "purple",
    ramp: "viridis",
    vmin: "0",
    vmax: "1",
  });
  for (const [k, v] of Object.entries({ ...view, ...size })) query.set(k, String(v));
  const base = httpBase({ port: mask.server_port, pathPrefix: mask.path_prefix }, page);
  return `${base}/bbox.png?${query.toString()}`;
}

/** Tells two masks apart: a new variant, reach or depth fetches a new crop. */
export function maskKey(mask: MaskArgs | null): string | null {
  return mask ? JSON.stringify(mask) : null;
}

export class MaskLayer {
  private mask: MaskArgs | null = null;
  private blobUrl: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  // Drops answers that arrive after a newer request was sent.
  private seq = 0;
  // The status line shows this layer's error; the next crop clears it.
  private failed = false;

  /**
   * `drawBelow` is the layer the mask goes under; `style` is the layer box's
   * checkbox and slider. An unticked mask isn't fetched at all.
   */
  constructor(
    private readonly map: MapLibreMap,
    private readonly drawBelow: string,
    private readonly style: () => RasterStyle,
    private readonly errors: MaskErrors,
  ) {
    map.on("moveend", () => {
      this.refreshSoon();
    });
  }

  set(mask: MaskArgs | null): void {
    this.mask = mask;
    this.refreshSoon();
  }

  refreshSoon(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.refresh().catch((err: unknown) => {
        this.fail(err);
      });
    }, DEBOUNCE_MS);
  }

  private async refresh(): Promise<void> {
    const seq = ++this.seq;
    const mask = this.mask;
    if (!mask || !this.style().visible) {
      this.remove();
      return;
    }
    const resp = await this.fetchCrop(mask, seq);
    if (!resp) return;
    if (!resp.ok) {
      // 404: no data in this view. The image is placed by lat/lon, so an
      // old crop left in place would be wrong after a pan.
      this.remove();
      if (resp.status !== 404) throw new Error(`bbox.png answered ${String(resp.status)}`);
      return;
    }
    const corners = parseCorners(resp.headers.get("X-Corners"));
    if (!corners) throw new Error(`bad X-Corners header: ${String(resp.headers.get("X-Corners"))}`);
    const blob = await resp.blob();
    if (seq !== this.seq) return;
    this.place(URL.createObjectURL(blob), corners);
  }

  /** The crop's answer; null if a newer request was sent meanwhile, or the server is unreachable. */
  private async fetchCrop(mask: MaskArgs, seq: number): Promise<Response | null> {
    try {
      const resp = await fetch(this.cropUrl(mask));
      return seq === this.seq ? resp : null;
    } catch (err) {
      if (seq === this.seq) this.fail(err);
      return null;
    }
  }

  private cropUrl(mask: MaskArgs): string {
    const bounds = this.map.getBounds();
    const canvas = this.map.getCanvas();
    return maskUrl(
      mask,
      {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
      },
      { width: canvas.width, height: canvas.height },
    );
  }

  private place(url: string, corners: Corners): void {
    this.remove();
    this.blobUrl = url;
    this.map.addSource(MASK_LAYER, { type: "image", url, coordinates: corners });
    const { layout, paint } = rasterLayerStyle(this.style());
    this.map.addLayer(
      {
        id: MASK_LAYER,
        type: "raster",
        source: MASK_LAYER,
        layout,
        paint: { ...paint, "raster-resampling": "nearest" },
      },
      this.drawBelow,
    );
    if (this.failed) this.errors.status.clear();
    this.failed = false;
  }

  private remove(): void {
    if (this.map.getLayer(MASK_LAYER)) this.map.removeLayer(MASK_LAYER);
    if (this.map.getSource(MASK_LAYER)) this.map.removeSource(MASK_LAYER);
    if (this.blobUrl) URL.revokeObjectURL(this.blobUrl);
    this.blobUrl = null;
  }

  /** A failed crop removes the old one and says so; the next move tries again. */
  private fail(err: unknown): void {
    console.error("mask crop failed", err);
    this.remove();
    this.failed = true;
    this.errors.status.set("error", this.errors.text);
  }
}
