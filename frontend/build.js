// Builds each map component into app/<component>/dist/, which the component's
// Python wrapper declares as its path.
//
// One build per component, not one multi-page build: Streamlit serves each
// component's directory as its own root, so a chunk shared by two components
// could not be loaded by either.
//
// `--watch` (npm run dev:watch) keeps every build running and rebuilds a
// component when one of its files changes.
import { resolve } from "node:path";
import { build } from "vite";

const COMPONENTS = [
  "overview",
  "overview_ifk",
  "raster_bbox_map",
  "anriss_map",
  "gebaeudeschatten_map",
];

const watch = process.argv.includes("--watch");

for (const name of COMPONENTS) {
  await build({
    configFile: resolve(import.meta.dirname, "vite.config.ts"),
    root: resolve(import.meta.dirname, "src", name),
    // Files every component ships as they are (the label glyphs).
    publicDir: resolve(import.meta.dirname, "public"),
    build: {
      outDir: resolve(import.meta.dirname, "..", "app", name, "dist"),
      emptyOutDir: true,
      watch: watch ? {} : null,
    },
  });
}

// download_gate is an inline Components v2 component: one ES module that
// app/download_gate_component.py reads and hands to Streamlit as its script.
await build({
  configFile: resolve(import.meta.dirname, "vite.config.ts"),
  root: resolve(import.meta.dirname, "src", "download_gate"),
  publicDir: false,
  build: {
    outDir: resolve(import.meta.dirname, "..", "app", "download_gate", "dist"),
    emptyOutDir: true,
    lib: { entry: "index.ts", formats: ["es"], fileName: () => "download_gate.js" },
    watch: watch ? {} : null,
  },
});
