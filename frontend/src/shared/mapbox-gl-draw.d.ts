// The part of @mapbox/mapbox-gl-draw this component uses. Its @types package
// depends on mapbox-gl, which the frontend doesn't otherwise need.

declare module "@mapbox/mapbox-gl-draw" {
  import type { IControl, LayerSpecification, Map as MapLibreMap } from "maplibre-gl";

  /** A style layer of the draw theme, without its source (the tool adds that). */
  export type DrawStyle = Omit<LayerSpecification, "source">;

  export interface DrawOptions {
    displayControlsDefault?: boolean;
    controls?: Record<string, boolean>;
    styles?: DrawStyle[];
  }

  export default class MapboxDraw implements IControl {
    constructor(options?: DrawOptions);
    static lib: { theme: DrawStyle[] };
    onAdd(map: MapLibreMap): HTMLElement;
    onRemove(map: MapLibreMap): void;
    changeMode(mode: "simple_select" | "draw_polygon"): this;
    deleteAll(): this;
  }
}
