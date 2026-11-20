// Outline layers sent in the render args (the Anriss view's Umhüllende and
// circles, Gebäudeschatten's footprints), each with a row in the layer box.
//
// They are drawn in list order, bottom first. An overlay whose data only shows
// up on a later render (the ad-hoc Umhüllende) is slotted in below the
// overlays listed after it, so the order never depends on arrival time.

import type { FeatureCollection } from "geojson";
import type { LineLayerSpecification, Map as MapLibreMap } from "maplibre-gl";

import { EMPTY, geojsonSource, replaceData } from "@/shared/geojson-source";
import type { LayerBox } from "@/shared/layer-box";

export interface OutlineOverlay {
  id: string;
  label: string;
  /** Null: no data (yet); the overlay keeps no row. */
  geojson: FeatureCollection | null;
  color: string;
  width: number;
  dash: number[] | null;
  opacity?: number;
  /** A fill colour under the outline (Gebäudeschatten), or none. */
  fill?: string | null;
  visible: boolean;
}

const FILL_OPACITY = 0.35;

function lineId(id: string): string {
  return `ov-${id}`;
}

function fillId(id: string): string {
  return `ov-${id}-fill`;
}

function linePaint(overlay: OutlineOverlay): NonNullable<LineLayerSpecification["paint"]> {
  return {
    "line-color": overlay.color,
    "line-width": overlay.width,
    "line-opacity": overlay.opacity ?? 1,
    ...(overlay.dash ? { "line-dasharray": overlay.dash } : {}),
  };
}

export class OutlineOverlays {
  private readonly known = new Set<string>();

  constructor(
    private readonly map: MapLibreMap,
    private readonly box: LayerBox,
    private readonly swatchOf: (overlay: OutlineOverlay) => HTMLElement,
  ) {}

  /** Shows `overlays`; an overlay the last render sent but this one doesn't is emptied. */
  show(overlays: readonly OutlineOverlay[]): void {
    overlays.forEach((overlay, index) => {
      this.showOne(overlay, overlays.slice(index + 1));
    });
    const sent = new Set(overlays.map((overlay) => overlay.id));
    for (const id of this.known) {
      if (sent.has(id)) continue;
      this.setData(id, EMPTY);
      this.box.hide(id);
    }
  }

  private showOne(overlay: OutlineOverlay, above: readonly OutlineOverlay[]): void {
    this.known.add(overlay.id);
    const source = lineId(overlay.id);
    // An overlay's layers are added with its first data.
    if (this.map.getSource(source)) this.setData(overlay.id, overlay.geojson ?? EMPTY);
    else if (overlay.geojson) this.add(overlay, overlay.geojson, above);
    this.box.set(overlay.id, {
      label: overlay.label,
      swatch: this.swatchOf(overlay),
      layers: overlay.fill ? [source, fillId(overlay.id)] : [source],
      visible: overlay.visible,
      shown: overlay.geojson !== null,
    });
  }

  private add(
    overlay: OutlineOverlay,
    data: FeatureCollection,
    above: readonly OutlineOverlay[],
  ): void {
    const source = lineId(overlay.id);
    this.map.addSource(source, { type: "geojson", data });
    const before = above
      .map((higher) => lineId(higher.id))
      .find((layerId) => this.map.getLayer(layerId));
    this.map.addLayer({ id: source, type: "line", source, paint: linePaint(overlay) }, before);
    if (overlay.fill) {
      this.map.addLayer(
        {
          id: fillId(overlay.id),
          type: "fill",
          source,
          paint: { "fill-color": overlay.fill, "fill-opacity": FILL_OPACITY },
        },
        source,
      );
    }
  }

  private setData(id: string, data: FeatureCollection): void {
    if (this.map.getSource(lineId(id))) replaceData(geojsonSource(this.map, lineId(id)), data);
  }
}
