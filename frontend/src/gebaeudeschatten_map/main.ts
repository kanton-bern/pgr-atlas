import "maplibre-gl/dist/maplibre-gl.css";
import "@/shared/map-controls.css";

import type { GebaeudeschattenArgs } from "@/gebaeudeschatten_map/args";
import { initGebaeudeschattenMap } from "@/gebaeudeschatten_map/map";
import { setupMapLibre } from "@/shared/maplibre-setup";
import { connectStreamlit } from "@/shared/streamlit-bridge";

const FRAME_HEIGHT = 780;

setupMapLibre();

// The first render builds the map; every render, the first included, goes
// through the map's render step (map.ts).
let render: ((args: GebaeudeschattenArgs) => void) | null = null;
const bridge = connectStreamlit((raw) => {
  const args = raw as unknown as GebaeudeschattenArgs;
  render ??= initGebaeudeschattenMap(args, bridge);
  render(args);
}, FRAME_HEIGHT);
