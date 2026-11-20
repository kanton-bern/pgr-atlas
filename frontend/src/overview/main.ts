import "maplibre-gl/dist/maplibre-gl.css";
import "@/shared/map-controls.css";

import type { OverviewArgs } from "@/overview/args";
import { initOverviewMap } from "@/overview/map";
import { setupMapLibre } from "@/shared/maplibre-setup";
import { connectStreamlit } from "@/shared/streamlit-bridge";

setupMapLibre();

// The first render builds the map. Later renders (reruns) update the
// highlight ring and the texts; the view and the rest stay.
let onRerun: ((args: OverviewArgs) => void) | null = null;
const bridge = connectStreamlit((raw) => {
  const args = raw as unknown as OverviewArgs;
  if (onRerun) onRerun(args);
  else onRerun = initOverviewMap(args, bridge);
});
