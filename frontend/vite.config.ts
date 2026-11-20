// Settings every component build and Vitest share. build.js sets the root and
// output directory per component.
//
// Browser targets (Q4): Vite's default, "baseline-widely-available" (Chrome and
// Edge 111+, Firefox 114+, Safari 16.4+), covers the last two versions of each.
import { defineConfig } from "vite";

export default defineConfig({
  // Streamlit serves a component under /component/<module>.<name>/, so the
  // page references its assets relative to itself.
  base: "./",
  resolve: { tsconfigPaths: true },
  build: {
    // MapLibre alone is about 1 MB minified and every component needs it on
    // load, so splitting the bundle would not load less. Above this, something
    // else got big.
    chunkSizeWarningLimit: 1300,
  },
});
