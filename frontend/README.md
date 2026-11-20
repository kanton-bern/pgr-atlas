# frontend

TypeScript sources for the app's MapLibre map components.
Node is needed to build them, never at runtime: the app image serves the built
files only.

## Setup

```sh
nvm use          # Node from .nvmrc (the current LTS)
npm ci
```

## Scripts

| Script                 | What it does                                  |
| ---------------------- | --------------------------------------------- |
| `npm run lint`         | ESLint, type-aware                            |
| `npm run format:check` | Prettier check (`npm run format` fixes it)    |
| `npm run typecheck`    | `tsc --noEmit`, strict                        |
| `npm test`             | Vitest unit tests (`src/**/*.test.ts`)        |
| `npm run build`        | Builds each component into `app/<name>/dist/` |

CI runs all five in `.github/workflows/frontend.yml`. The E2E and AppTest workflows,
`build-and-push.yml` and `docker/build.sh` build before they use `app/`.

## Build

`build.js` runs one Vite build per component (`src/<name>/index.html` →
`app/<name>/dist/`), with the settings in `vite.config.ts`. Each build is
self-contained: Streamlit serves every component directory as its own root, so
components can't share chunks. `dist/` is git-ignored.

- MapLibre, pmtiles, proj4 and the CSS are bundled; the page loads nothing from a
  CDN. MapLibre's web worker is built into a file of its own
  (`src/shared/maplibre-setup.ts`).
- Browser targets: Vite's default, Chrome/Edge 111+, Firefox 114+, Safari 16.4+.
- Imports use the `@/` alias for `src/` (`tsconfig.json`), not `../` paths.

## Layout

`src/<component>/` holds one component: its `index.html`, `main.ts` and modules.

| Component              | Python wrapper                          | Built into                      |
| ---------------------- | --------------------------------------- | ------------------------------- |
| `overview`             | `app/overview_component.py`             | `app/overview/dist`             |
| `overview_ifk`         | `app/ifk_map_component.py`              | `app/overview_ifk/dist`         |
| `raster_bbox_map`      | `app/raster_bbox_component.py`          | `app/raster_bbox_map/dist`      |
| `anriss_map`           | `app/anriss_map_component.py`           | `app/anriss_map/dist`           |
| `gebaeudeschatten_map` | `app/gebaeudeschatten_map_component.py` | `app/gebaeudeschatten_map/dist` |
| `download_gate`        | `app/download_gate_component.py`        | `app/download_gate/dist`        |

`download_gate` is not a map: it is the dialog that holds back a browser tab's first download
until the user accepts the notes on the simulation data (a Streamlit Components v2 component).

`src/shared/` is the code every component uses:

| File                    | Contents                                                                       |
| ----------------------- | ------------------------------------------------------------------------------ |
| `streamlit-bridge.ts`   | The Streamlit component protocol, with the origin checks                       |
| `urls.ts`               | Sidecar URLs (tile and derivate server, by port or path prefix)                |
| `types.ts`              | Render args and component values shared by several components                  |
| `anriss-areas.ts`       | The six Anrissfläche classes and their legend filter                           |
| `prefetch.ts`           | Asks the tile sidecar to start an anriss read or an IFK early                  |
| `pixel-grid.ts`         | The 5 m pixel grid layer and a pixel's square                                  |
| `geojson-source.ts`     | Finding and updating the GeoJSON sources a component adds                      |
| `lv95.ts`               | LV95 <-> WGS84, the 5 m pixel lattice, the plausible-Switzerland check         |
| `map-controls.ts`       | Map chrome: basemaps, zoom readout, search, Berechnete Kacheln, Prozessquellen |
| `map-controls.css`      | Styles for that chrome                                                         |
| `escape.ts`             | `escapeHtml` for every value that goes into popup or legend HTML               |
| `search-input.ts`       | Validation of the coordinate search box                                        |
| `maplibre-setup.ts`     | The bundled MapLibre worker and the `pmtiles://` protocol                      |
| `image-corners.ts`      | The `X-Corners` header of a `/bbox.png` crop                                   |
| `layer-box.ts`          | Layer-box rows (the server's default until ticked), a raster's opacity slider  |
| `raster-opacity.ts`     | A raster layer's visibility and opacity, and the opacity the user chose        |
| `outline-overlays.ts`   | Outline layers from the render args, in list order (Anriss, Gebäudeschatten)   |
| `drawing.ts`            | The rectangle and polygon draw tools (mapbox-gl-draw), one on at a time        |
| `drawing.css`           | Styles of the draw control                                                     |
| `draw-theme.ts`         | mapbox-gl-draw's theme in the selection colour                                 |
| `selection.ts`          | The selection on the map: outline, size readout, "Löschen"                     |
| `selection-geometry.ts` | A drawn selection's ring, bounds, area and readout, in LV95                    |
| `pixel-footprint.ts`    | The 5 m pixels a selection takes, as drawn (the server's rule)                 |
| `selection-color.ts`    | The selection's colours                                                        |

Shared code goes into `src/shared/` and is bundled into each component. A
component directory can't reach a sibling at runtime: Streamlit's component
handler rejects any path, symlinks included, that resolves outside the
component's own directory (`400 Bad Request`).

## Tilesets

Two static PMTiles archives are not built here. The ProBE simulation pipeline
builds them offline and uploads them to the root of the app's bucket (`PROBE_S3_BUCKET`). `app/pmtiles_server.py` serves
only root-level `*.pmtiles` keys. The maps read their layers and properties by
name:

| Archive (S3 key)                | Layers                                                      | Properties the maps use | Read in                      |
| ------------------------------- | ----------------------------------------------------------- | ----------------------- | ---------------------------- |
| `overview_anrisse_maxi.pmtiles` | `anrisse` (points), `anrisse_circles` (polygons)            | `id_anriss`, `A`        | `src/overview/`              |
| `prozessquelle.pmtiles`         | `prozessquelle` (polygons), `prozessquelle_labels` (points) | `id_pq`                 | `src/shared/map-controls.ts` |

`A` is the Anrissfläche in m². The tiles also carry `id_prozessquelle`,
`radius_m` and `area_m2`, which the maps don't use. Colors are not in the
tiles: the area classes come from `src/shared/anriss-areas.ts`.

Renaming a layer or a used property means changing the maps here and the build
scripts in the pipeline repo together, then rebuilding and re-uploading the
tileset. While the overview archive is missing, the app shows
`ui_text.overview_pmtiles_missing`.

## Styles and tokens

The design tokens (colours, radii, the map chrome's sizes and font) are in
`app/styles/tokens.css`. The Streamlit side loads that file before `app.css`,
and `src/shared/map-controls.css` imports it, so Vite bundles the same values
into every component. Change a colour there, in one place.

Styles go into classes, in `map-controls.css` or the component's own
`index.html`. Elements are shown and hidden with the `hidden` attribute. An
inline style is only right where the value is data: a legend gradient, a
swatch colour, or the tooltip's position.

## Shared map chrome

`map-controls.ts` holds the chrome and pure utilities only. View-specific
interaction (pixel selection, bbox and polygon drawing, and the click priority
between overlapping layers) stays in each component: the rules differ per view,
and a wrong order has caused subtle bugs (see `wireMapClicks` in
`src/overview_ifk/map.ts`).

Every view built on `initChrome()` uses the same corner scheme, modelled on the
Kanton Bern geoportal:

| Corner       | Contents                                                             |
| ------------ | -------------------------------------------------------------------- |
| Top right    | Zoom control (+/−), with the coordinate search below it              |
| Top left     | Layer and legend box (content per view)                              |
| Bottom left  | Scale bar, with the zoom-level readout above it                      |
| Bottom right | Basemap switcher, with the view's data legend above it if it has one |

The basemap choice, the Berechnete Kacheln and Prozessquellen toggles and the
opacity chosen for each raster layer survive a view switch. Each view is its
own iframe, so the state lives on `window.top` (`__probeMapChromeState`,
`__probeRasterOpacityPercent`): every map iframe is a same-origin child of the
one Streamlit page. It resets on a page reload, like the rest of the app's
state, which is why it isn't in `localStorage`.

A raster layer (Raster-Karten's result, the Raster-Derivate preview, the
Gebäudeschatten mask) has a row in the layer box like any other layer, with an
opacity slider below it (`layer-box.ts`). Unticked, the layer, its legend and
its pixel values are hidden, and a crop isn't fetched. The row follows its
default (on) until the user ticks it. In the raster map, a new raster (a new
job, metric or band) shows itself again; an unticked Gebäudeschatten mask stays
off with new settings until the user ticks it. The opacity starts at the layer's own default
(75 %, 85 %, 45 %) and then keeps the user's choice, a new raster included.

Rules for a component:

- **Handshake through `streamlit-bridge.ts`.** It posts to
  `window.location.origin` and ignores messages that aren't from
  `window.parent` with the page's own origin.
- **Loading and error states.** Call `setMapStatus(kind, text)` (`"loading"`,
  `"error"`, or `null` to hide) instead of leaving a map blank.
- **Basemaps come from swisstopo WMTS** (the tile cache), not WMS GetMap, with
  a per-layer maximum zoom. A basemap can have several zoom bands, one raster
  layer each. "SwissTopo LK" is swisstopo's multi-scale national map series
  (`ch.swisstopo.pixelkarte-grau`, overview map through 1:1 Mio. … 1:50'000)
  below `LANDESKARTE_10_MIN_ZOOM` (zoom 14) and the 1:10'000 map
  (`ch.swisstopo.landeskarte-grau-10`) from there; the 1:10'000 map alone would
  be grey noise zoomed out.

  | Zoom (the map's "Zoomstufe") | Map shown                 |
  | ---------------------------- | ------------------------- |
  | below 8.5                    | overview map (simplified) |
  | 8.5–10.5                     | 1:1 Mio.                  |
  | 10.5–11.5                    | 1:500'000                 |
  | 11.5–12.5                    | 1:200'000                 |
  | 12.5–13.5                    | 1:100'000                 |
  | 13.5–14                      | 1:50'000                  |
  | from 14                      | 1:10'000                  |

  Measured at Bern. The national map series picks the scale per tile level;
  MapLibre loads tile level `round(zoom + 1)` for these 256 px tiles. The series
  itself would reach 1:25'000 at 14.5 and 1:10'000 at 15.5; the earlier
  1:10'000 band skips 1:25'000. map.geo.admin.ch, in the Swiss LV95 grid, shows
  each scale within about 0.4 zoom of these, except the 1:1 Mio. map (from about
  7.7 there) and 1:10'000 (from about 15.1).
