// Raster-Derivate's live layer. derivate_bbox_server.py crops and colours the
// canton mosaic for the visible part of the map, in LV95, and answers with
// the crop's pixel-snapped corners (X-Corners). One image source, replaced
// after each move; a click reads one pixel's value.

import type { LngLat, Map as MapLibreMap, PointLike } from "maplibre-gl";

import type { RasterArgs, RasterTexts } from "@/raster_bbox_map/args";
import { DRAW_BELOW } from "@/raster_bbox_map/overlays";
import {
  type DerivateStyle,
  hideLegend,
  hideTooltip,
  showDerivateLegend,
  showTooltip,
} from "@/raster_bbox_map/panels";
import { formatDerivateValue } from "@/raster_bbox_map/value-format";
import { type Corners, parseCorners } from "@/shared/image-corners";
import { fromWgs } from "@/shared/lv95";
import type { MapStatus } from "@/shared/map-controls";
import { rasterLayerStyle, type RasterStyle } from "@/shared/raster-opacity";
import { fill } from "@/shared/texts";
import { httpBase, type Sidecar } from "@/shared/urls";

const SOURCE = "derivate-bbox-src";
export const DERIVATE_LAYER = "derivate-bbox-layer";
/** The layer's opacity until the user moves the layer box's slider. */
export const DERIVATE_OPACITY_PERCENT = 85;
// No request per frame while the user drags.
const DEBOUNCE_MS = 200;

export interface DerivateParams extends DerivateStyle {
  metric: string;
  partition: string | null;
  band: number;
}

/** The layer's params from the render args; null (no layer) without a metric or band. */
export function derivateParams(args: RasterArgs): DerivateParams | null {
  const { derivate_bbox_metric: metric, derivate_bbox_band: band } = args;
  if (!metric || !band) return null;
  return {
    metric,
    band,
    partition: args.derivate_bbox_partition,
    label: args.derivate_bbox_label ?? "",
    unit: args.derivate_bbox_unit,
    scale: args.derivate_bbox_scale ?? "linear",
    ramp: args.derivate_bbox_ramp,
    vmin: args.derivate_bbox_vmin,
    vmax: args.derivate_bbox_vmax,
    note: args.derivate_bbox_note,
  };
}

/** The text of a pixel's value; a mask pixel is affected (1) or not. */
export function valueText(
  params: DerivateParams,
  value: number | null,
  texts: RasterTexts,
): string {
  const { labels } = texts;
  const { label, unit } = params;
  if (params.scale === "mask") {
    return fill(value === 1 ? labels.pixel_mask_yes : labels.pixel_mask_no, { label });
  }
  const shown = formatDerivateValue(value, params.scale, texts.locale);
  return unit
    ? fill(labels.pixel_value, { label, value: shown, unit })
    : fill(labels.pixel_value_unitless, { label, value: shown });
}

function mosaicQuery(params: DerivateParams): URLSearchParams {
  return new URLSearchParams({
    metric: params.metric,
    partition: params.partition ?? "",
    band: String(params.band),
  });
}

export class DerivateLayer {
  private params: DerivateParams | null = null;
  private blobUrl: string | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  // Each counter drops answers that arrive after a newer request was sent.
  private cropSeq = 0;
  private valueSeq = 0;

  constructor(
    private readonly map: MapLibreMap,
    private readonly server: Sidecar,
    private readonly texts: RasterTexts,
    private readonly status: MapStatus,
    /** The layer box's checkbox and slider; an unticked layer isn't fetched at all. */
    private readonly style: () => RasterStyle,
  ) {
    map.on("moveend", () => {
      this.refreshSoon();
    });
    // A language switch: the legend in the new texts; a shown value is hidden
    // rather than left in the old language.
    texts.bind(() => {
      if (!this.params || !this.style().visible) return;
      showDerivateLegend(this.params, texts);
      hideTooltip();
    });
  }

  get active(): boolean {
    return this.params !== null;
  }

  /** Shows the layer for `params`, or removes it for null. */
  set(params: DerivateParams | null): void {
    const wasActive = this.active;
    this.params = params;
    if (!params) {
      this.cropSeq++;
      this.remove();
      if (wasActive) this.status.clear();
      return;
    }
    this.visibilityChanged();
  }

  /**
   * Fetches a crop and shows the legend while the layer box's checkbox is
   * ticked; drops both, and any crop on its way, while it isn't.
   */
  visibilityChanged(): void {
    const params = this.params;
    if (!params) return;
    hideTooltip();
    if (this.style().visible) {
      showDerivateLegend(params, this.texts);
      this.refreshNow();
      return;
    }
    this.cropSeq++;
    this.remove();
    hideLegend();
    this.status.clear();
  }

  /** Shows the value of the pixel at `lngLat` next to the pointer. */
  async showValueAt(lngLat: LngLat, point: PointLike): Promise<void> {
    const params = this.params;
    if (!params || !this.style().visible) return;
    const { E, N } = fromWgs(lngLat.lat, lngLat.lng);
    const query = mosaicQuery(params);
    query.set("e", String(E));
    query.set("n", String(N));
    const seq = ++this.valueSeq;
    const response = await fetch(`${httpBase(this.server)}/value.json?${query.toString()}`);
    if (seq !== this.valueSeq) return;
    if (!response.ok) {
      hideTooltip();
      // 404: outside the mosaic, or a nodata pixel.
      if (response.status !== 404) {
        throw new Error(`value.json answered ${String(response.status)}`);
      }
      return;
    }
    const { value } = (await response.json()) as { value: number | null };
    if (seq !== this.valueSeq) return;
    showTooltip(valueText(params, value, this.texts), point);
  }

  private refreshNow(): void {
    this.refresh().catch((err: unknown) => {
      this.fail(err);
    });
  }

  private refreshSoon(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.refreshNow();
    }, DEBOUNCE_MS);
  }

  private cropUrl(params: DerivateParams): string {
    const bounds = this.map.getBounds();
    const canvas = this.map.getCanvas();
    const query = mosaicQuery(params);
    const values: Record<string, string | number> = {
      scale: params.scale,
      ramp: params.ramp ?? "viridis",
      vmin: params.vmin ?? 0,
      vmax: params.vmax ?? 1,
      west: bounds.getWest(),
      south: bounds.getSouth(),
      east: bounds.getEast(),
      north: bounds.getNorth(),
      width: canvas.width,
      height: canvas.height,
    };
    for (const [name, value] of Object.entries(values)) query.set(name, String(value));
    return `${httpBase(this.server)}/bbox.png?${query.toString()}`;
  }

  private async refresh(): Promise<void> {
    const params = this.params;
    if (!params || !this.style().visible) return;
    const seq = ++this.cropSeq;
    this.status.set("loading", () => this.texts.labels.crop_loading);
    const response = await this.fetchCrop(params, seq);
    if (!response) return;
    if (!response.ok) {
      // The image is placed by lat/lon, so an old crop left in place would
      // be wrong after a pan. 404 is "no data here", anything else a failure.
      if (response.status !== 404) {
        throw new Error(`bbox.png answered ${String(response.status)}`);
      }
      this.remove();
      this.status.clear();
      return;
    }
    const cornersHeader = response.headers.get("X-Corners");
    const corners = parseCorners(cornersHeader);
    if (!corners) throw new Error(`bad X-Corners header: ${String(cornersHeader)}`);
    const blob = await response.blob();
    if (seq !== this.cropSeq) return;
    this.status.clear();
    this.place(URL.createObjectURL(blob), corners);
  }

  /** The crop's answer; null if a newer request was sent meanwhile, or the server is unreachable. */
  private async fetchCrop(params: DerivateParams, seq: number): Promise<Response | null> {
    try {
      const response = await fetch(this.cropUrl(params));
      return seq === this.cropSeq ? response : null;
    } catch (err) {
      // The next move tries again.
      if (seq === this.cropSeq) this.fail(err);
      return null;
    }
  }

  private place(url: string, corners: Corners): void {
    this.remove();
    this.blobUrl = url;
    this.map.addSource(SOURCE, { type: "image", url, coordinates: corners });
    const { layout, paint } = rasterLayerStyle(this.style());
    this.map.addLayer(
      {
        id: DERIVATE_LAYER,
        type: "raster",
        source: SOURCE,
        layout,
        paint: { ...paint, "raster-resampling": "nearest" },
      },
      this.map.getLayer(DRAW_BELOW) ? DRAW_BELOW : undefined,
    );
  }

  private remove(): void {
    if (this.map.getLayer(DERIVATE_LAYER)) this.map.removeLayer(DERIVATE_LAYER);
    if (this.map.getSource(SOURCE)) this.map.removeSource(SOURCE);
    if (this.blobUrl) URL.revokeObjectURL(this.blobUrl);
    this.blobUrl = null;
  }

  /** A failed crop removes the old one and says so, instead of a blank map. */
  private fail(err: unknown): void {
    console.error("Raster-Derivate crop failed", err);
    this.remove();
    this.status.set("error", () => this.texts.labels.crop_error);
  }
}

/** Tells two layer settings apart: any change of metric or style fetches a new crop. */
export function derivateKey(params: DerivateParams | null): string | null {
  return params ? JSON.stringify(params) : null;
}
