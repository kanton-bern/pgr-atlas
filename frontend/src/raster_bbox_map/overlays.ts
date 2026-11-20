// Raster-Karten's finished rasters: the image layer, its legend, the variable
// switch and the hover values. Mode B computes depth, velocity and pressure
// in one job, so the switch changes variable without a rerun.

import type { LngLat, Map as MapLibreMap, PointLike } from "maplibre-gl";

import type { HoverGeometry, RasterOverlay, RasterTexts } from "@/raster_bbox_map/args";
import { HoverGrids, hoverIndex } from "@/raster_bbox_map/hover-grid";
import { hideLegend, hideTooltip, showOverlayLegend, showTooltip } from "@/raster_bbox_map/panels";
import { formatHoverValue } from "@/raster_bbox_map/value-format";
import { fromWgs } from "@/shared/lv95";
import type { MapStatus } from "@/shared/map-controls";
import { setPressed } from "@/shared/pressed";
import { rasterLayerStyle, type RasterStyle } from "@/shared/raster-opacity";
import { fill } from "@/shared/texts";
import { httpBase, type Sidecar } from "@/shared/urls";

const SOURCE = "raster-overlay";
export const OVERLAY_LAYER = "raster-overlay-layer";
/** The overlay's opacity until the user moves the layer box's slider. */
export const OVERLAY_OPACITY_PERCENT = 75;
/** Rasters draw below this layer (the selection), so the outline stays visible. */
export const DRAW_BELOW = "draw-bbox-fill";

/** Tells two jobs apart: each finished file has its own job id and variable. */
export function overlaysKey(overlays: Record<string, RasterOverlay> | null): string | null {
  if (!overlays) return null;
  return Object.keys(overlays)
    .sort()
    .map((k) => `${overlays[k]?.job_id ?? ""}/${k}`)
    .join("|");
}

interface ShownGrid {
  overlay: RasterOverlay & { hover: HoverGeometry };
  data: Float32Array;
}

export class RasterOverlays {
  private overlays: Record<string, RasterOverlay> | null = null;
  private shown: ShownGrid | null = null;
  // The raster on the map, whose legend a language switch rewrites.
  private current: RasterOverlay | null = null;
  private readonly switchTitle = document.createElement("div");
  // Counts overlay changes, so a grid that arrives for an older one is dropped.
  private generation = 0;
  private readonly grids: HoverGrids;
  private readonly jobUrl: (overlay: RasterOverlay, ext: "png" | "f32") => string;

  constructor(
    private readonly map: MapLibreMap,
    jobServer: Sidecar,
    private readonly texts: RasterTexts,
    private readonly status: MapStatus,
    /** The layer box's checkbox and slider for the overlay. */
    private readonly style: () => RasterStyle,
  ) {
    const base = httpBase(jobServer);
    this.jobUrl = (o, ext) => `${base}/job/${encodeURIComponent(o.job_id)}/${o.var}.${ext}`;
    this.grids = new HoverGrids((o) => this.jobUrl(o, "f32"));
    this.switchTitle.className = "var-switch-title";
    // MapLibre fetches the PNG; an unknown or expired job answers 404
    // (derivate_bbox_server.py's _JobFileHandler).
    map.on("error", (e) => {
      if ((e as { sourceId?: string }).sourceId !== SOURCE) return;
      status.set("error", () => texts.labels.image_error);
    });
    // A language switch: the legend and the switch title in the new texts; a
    // shown value is hidden rather than left in the old language.
    texts.bind(() => {
      this.switchTitle.textContent = texts.labels.var_switch_title;
      if (!this.current) return;
      this.showLegend();
      hideTooltip();
    });
  }

  /**
   * The layer box ticked or unticked the overlay: the layer box shows and
   * hides the layer itself, this the legend; a shown value goes.
   */
  visibilityChanged(): void {
    hideTooltip();
    this.showLegend();
  }

  get active(): boolean {
    return this.overlays !== null;
  }

  /** Shows a job's rasters, `activeVar` first; null removes them. */
  show(overlays: Record<string, RasterOverlay> | null, activeVar: string | null): void {
    this.grids.clear();
    const entries = Object.entries(overlays ?? {});
    this.overlays = entries.length ? overlays : null;
    const [active, overlay] = entries.find(([v]) => v === activeVar) ?? entries[0] ?? [];
    this.buildSwitch(active);
    this.apply(overlay ?? null);
  }

  /** The hover text for the pixel at `lngLat`, or null where there is none. */
  valueAt(lngLat: LngLat): string | null {
    if (!this.shown || !this.style().visible) return null;
    const { overlay, data } = this.shown;
    const { E, N } = fromWgs(lngLat.lat, lngLat.lng);
    const i = hoverIndex(overlay.hover, E, N);
    const v = i === null ? Number.NaN : (data[i] ?? Number.NaN);
    const value = formatHoverValue(v, overlay.log_scale, this.texts.locale);
    if (value === null) return null;
    return fill(this.texts.labels.pixel_value, { label: overlay.label, value, unit: overlay.unit });
  }

  showValueAt(lngLat: LngLat, point: PointLike): void {
    const text = this.valueAt(lngLat);
    if (text) showTooltip(text, point);
    else hideTooltip();
  }

  private apply(overlay: RasterOverlay | null): void {
    const { map } = this;
    if (map.getLayer(OVERLAY_LAYER)) map.removeLayer(OVERLAY_LAYER);
    if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    this.shown = null;
    this.current = overlay;
    this.generation++;
    hideTooltip();
    this.showLegend();
    if (!overlay) return;
    map.addSource(SOURCE, {
      type: "image",
      url: this.jobUrl(overlay, "png"),
      coordinates: overlay.corners,
    });
    // 'nearest': each pixel is one 5 m gold cell; blending neighbours would
    // show values that were never computed.
    const { layout, paint } = rasterLayerStyle(this.style());
    map.addLayer(
      {
        id: OVERLAY_LAYER,
        type: "raster",
        source: SOURCE,
        layout,
        paint: { ...paint, "raster-resampling": "nearest" },
      },
      map.getLayer(DRAW_BELOW) ? DRAW_BELOW : undefined,
    );
    // Without a hover section the raster is too big for a grid: the image and
    // legend show, the hover doesn't.
    const { hover } = overlay;
    if (hover) void this.loadGrid({ ...overlay, hover });
  }

  /** The legend of the raster on the map; none while the layer is off. */
  private showLegend(): void {
    if (this.current && this.style().visible) showOverlayLegend(this.current, this.texts);
    else hideLegend();
  }

  private async loadGrid(overlay: RasterOverlay & { hover: HoverGeometry }): Promise<void> {
    const generation = this.generation;
    try {
      const data = await this.grids.get(overlay);
      if (generation === this.generation) this.shown = { overlay, data };
    } catch (err) {
      if (generation !== this.generation) return;
      console.error("Hover grid failed", err);
      this.status.set("error", () => this.texts.labels.values_error);
    }
  }

  /** One button per variable; only shown when the job has more than one. */
  private buildSwitch(activeVar: string | undefined): void {
    const box = document.getElementById("var-switch");
    if (!box) throw new Error("raster_bbox_map: #var-switch is missing from index.html");
    const entries = Object.entries(this.overlays ?? {});
    if (entries.length < 2) {
      box.hidden = true;
      box.replaceChildren();
      return;
    }
    const buttons = entries.map(([variable, overlay]) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "var-btn";
      setPressed(btn, variable === activeVar);
      btn.dataset.var = variable;
      btn.textContent = overlay.label;
      btn.addEventListener("click", () => {
        for (const b of buttons) setPressed(b, b === btn);
        this.apply(overlay);
      });
      return btn;
    });
    box.replaceChildren(this.switchTitle, ...buttons);
    box.hidden = false;
  }
}
