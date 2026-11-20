import "maplibre-gl/dist/maplibre-gl.css";
import "@/shared/map-controls.css";

import type { AnrissArgs } from "@/anriss_map/args";
import { initAnrissMap } from "@/anriss_map/map";
import { setupMapLibre } from "@/shared/maplibre-setup";
import { connectStreamlit } from "@/shared/streamlit-bridge";

const FRAME_HEIGHT = 780;

setupMapLibre();

// The first render builds the map; every render, the first included, goes
// through the map's render step (map.ts).
let render: ((args: AnrissArgs) => void) | null = null;
const bridge = connectStreamlit((raw) => {
  const args = raw as unknown as AnrissArgs;
  render ??= initAnrissMap(args, bridge);
  render(args);
}, FRAME_HEIGHT);
