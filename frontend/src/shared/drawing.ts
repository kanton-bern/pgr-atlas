// The two drawing tools, one active at a time: "Rechteck zeichnen" (drag a
// rectangle) and "Polygon zeichnen" (click vertices, mapbox-gl-draw). Both are
// toggles, so the map pans normally otherwise. A finished shape goes to the
// selection layer, so both look the same, and to Python.

import MapboxDraw from "@mapbox/mapbox-gl-draw";
import type { Feature, Polygon } from "geojson";
import type { Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";

import type { Lv95Point, Selection } from "@/shared/types";
import { drawTheme } from "@/shared/draw-theme";
import { dragBounds, snappedRect } from "@/shared/selection-geometry";
import type { SelectionLayer } from "@/shared/selection";
import { fromWgs } from "@/shared/lv95";
import { setPressed } from "@/shared/pressed";

function element(id: string): HTMLElement {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from index.html`);
  return el;
}

function lv95(e: MapMouseEvent): Lv95Point {
  const { E, N } = fromWgs(e.lngLat.lat, e.lngLat.lng);
  return [E, N];
}

/** The events mapbox-gl-draw fires on the map, which MapLibre's types don't list. */
interface DrawEvents {
  "draw.create": { features: Feature<Polygon>[] };
  "draw.modechange": { mode: string };
}

function onDraw<K extends keyof DrawEvents>(
  map: MapLibreMap,
  type: K,
  listener: (e: DrawEvents[K]) => void,
): void {
  (map as unknown as { on(type: K, listener: (e: DrawEvents[K]) => void): void }).on(
    type,
    listener,
  );
}

export interface Drawing {
  /** True while either tool is on: a click then belongs to the drawing. */
  readonly active: boolean;
}

interface DrawingContext {
  map: MapLibreMap;
  selection: SelectionLayer;
  send: (selection: Selection | null) => void;
  draw: MapboxDraw;
}

/** The rectangle tool. dragPan is off while it is on, so a drag draws instead of panning. */
class BboxTool {
  on = false;
  private start: Lv95Point | null = null;
  private readonly button = element("draw-btn");

  constructor(private readonly context: DrawingContext) {
    const { map } = context;
    map.on("mousedown", (e) => {
      if (!this.on) return;
      this.start = lv95(e);
      e.preventDefault();
    });
    map.on("mousemove", (e) => {
      if (this.start) context.selection.preview(dragBounds(this.start, lv95(e)));
    });
    map.on("mouseup", (e) => {
      if (!this.start) return;
      const drawn = snappedRect(this.start, lv95(e));
      this.start = null;
      if (!drawn) {
        // A click, not a rectangle: nothing is sent, and the tool stays on
        // for another try.
        context.selection.dropPreview();
        return;
      }
      context.selection.show(drawn, false);
      this.set(false);
      context.send(drawn);
    });
  }

  set(on: boolean): void {
    this.on = on;
    setPressed(this.button, on);
    element("map").classList.toggle("drawing", on);
    if (on) {
      this.context.map.dragPan.disable();
    } else {
      this.context.map.dragPan.enable();
    }
  }
}

/** The polygon tool. Its own toolbar is hidden; the button drives it. */
class PolygonTool {
  private readonly button = element("draw-poly-btn");

  constructor(private readonly context: DrawingContext) {
    const { map, draw } = context;
    // Also fires when the mode ends another way: Escape, or a finished polygon.
    onDraw(map, "draw.modechange", (e) => {
      setPressed(this.button, e.mode === "draw_polygon");
    });
    onDraw(map, "draw.create", (e) => {
      const lonLats = e.features[0]?.geometry.coordinates[0] ?? [];
      draw.deleteAll();
      // A closed ring with fewer than 3 distinct vertices has no area.
      if (lonLats.length < 4) return;
      const ring = lonLats.map(([lon = 0, lat = 0]) => {
        const { E, N } = fromWgs(lat, lon);
        return [E, N] as Lv95Point;
      });
      const drawn: Selection = { type: "polygon", ring };
      context.selection.show(drawn, false);
      context.send(drawn);
    });
  }

  get on(): boolean {
    return this.button.classList.contains("active");
  }

  set(on: boolean): void {
    if (on) {
      this.context.draw.changeMode("draw_polygon");
    } else {
      this.context.draw.changeMode("simple_select");
      this.context.draw.deleteAll();
    }
    // mapbox-gl-draw fires no draw.modechange for changeMode calls.
    setPressed(this.button, on);
    element("map").classList.toggle("drawing", on);
  }
}

export function wireDrawing(
  map: MapLibreMap,
  selection: SelectionLayer,
  send: (selection: Selection | null) => void,
): Drawing {
  const draw = new MapboxDraw({ displayControlsDefault: false, controls: {}, styles: drawTheme() });
  map.addControl(draw);
  const context = { map, selection, send, draw };
  const bbox = new BboxTool(context);
  const polygon = new PolygonTool(context);

  element("draw-btn").addEventListener("click", () => {
    const on = !bbox.on;
    if (on && polygon.on) polygon.set(false);
    bbox.set(on);
  });
  element("draw-poly-btn").addEventListener("click", () => {
    const on = !polygon.on;
    // First: the bbox tool resets the map's "drawing" cursor, which the
    // polygon tool then sets again.
    if (on) bbox.set(false);
    polygon.set(on);
  });
  element("clear-btn").addEventListener("click", () => {
    selection.show(null, false);
    draw.deleteAll();
    send(null);
  });
  return {
    get active() {
      return bbox.on || polygon.on;
    },
  };
}
