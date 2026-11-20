import "maplibre-gl/dist/maplibre-gl.css";
import "@mapbox/mapbox-gl-draw/dist/mapbox-gl-draw.css";
import "@/shared/map-controls.css";
import "@/shared/drawing.css";

import type { IfkArgs } from "@/overview_ifk/args";
import { initIfkMap } from "@/overview_ifk/map";
import { setupMapLibre } from "@/shared/maplibre-setup";
import { connectStreamlit } from "@/shared/streamlit-bridge";

setupMapLibre();

// The first render builds the map. Later renders (reruns) update the anriss
// circles or outline, their legend, the pixel squares, the selected area and
// the texts; the view and the rest stay.
let onRerun: ((args: IfkArgs) => void) | null = null;
const bridge = connectStreamlit((raw) => {
  const args = raw as unknown as IfkArgs;
  if (onRerun) onRerun(args);
  else onRerun = initIfkMap(args, bridge);
});
