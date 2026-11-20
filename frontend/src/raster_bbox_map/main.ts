import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import "@/shared/map-controls.css";
import "@/shared/drawing.css";

import type { RasterArgs } from "@/raster_bbox_map/args";
import { initRasterMap } from "@/raster_bbox_map/map";
import { setupMapLibre } from "@/shared/maplibre-setup";
import { connectStreamlit } from "@/shared/streamlit-bridge";

setupMapLibre();

// The first render builds the map; every render, the first included, goes
// through the map's render step (map.ts).
let render: ((args: RasterArgs) => void) | null = null;
const bridge = connectStreamlit((raw) => {
  const args = raw as unknown as RasterArgs;
  render ??= initRasterMap(args, bridge);
  render(args);
});
