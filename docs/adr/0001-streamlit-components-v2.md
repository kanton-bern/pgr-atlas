# ADR 0001: Streamlit Components v2 for the map components

Date: 2026-10-01 · Status: Accepted, not implemented yet · Streamlit 1.64.0

Decides how the map components are to be built, after a spike: a throwaway prototype whose
code and probe scripts are not part of this repository. The five map components are still v1
components (`declare_component`, one iframe each) until the migration described here
(steps C-1 to C-6) is done.

## Context

The five map components are v1 components: one iframe each, a nonce round trip per event, a
fixed frame height (700 or 780 px), and their own MapLibre bundle, so every view downloads
MapLibre again. Streamlit 1.64 has
`st.components.v2`, which mounts a JS module in the page (optionally in a shadow root), sends
events with `setTriggerValue`/`setStateValue`, and sizes the element to its content.

The spike moved the overview and the IFK map to v2 in the real app, and added two small
checks: a `smoke` view (one button, one event) and a `draw-check` view (mapbox-gl-draw in the
shadow root). The pass rule: all six criteria hold, or the migration does not start.

## Decision

**Go ahead with C-1..C-6 on v2.** All six criteria pass. For criterion 3's cache headers, the
app adds a small `st.App` middleware, which C-1 ships with the package. The points the spike
left open, and where each one closes, are listed under [Open points](#open-points).

## Results

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Rendering and styles | **Pass** |
| 2 | Events without a nonce | **Pass** |
| 3 | Packaging | **Pass**, cache headers with a middleware |
| 4 | Shared chunks | **Pass** |
| 5 | Memory over 20 view switches | **Pass** |
| 6 | Height follows content | **Pass** |

### 1. Rendering and styles — pass

Setup: `isolate_styles=True` (the default), so the map lives in a shadow root.

- The overview and IFK maps render their chrome (legend, search, basemap box, layer toggles)
  in the shadow root and handle popup clicks there.
- **No leak into the map:** the computed styles of all 57 chrome elements (legend, search,
  basemap box, status line, popups) are equal in v1 and v2. Screenshots of the chrome differ
  only by sub-pixel offsets.
- **No leak out of the map:** no MapLibre or chrome rule is added to the document
  (`document.adoptedStyleSheets` gets 0 map rules). Every stylesheet is adopted by the shadow
  root.
- **Sidebar unchanged:** on the overview with the map loaded (1500×1000 viewport), the sidebar
  screenshots of v1 (`main`) and v2 (spike) are the same size (300×1000) and differ only in the
  version line's commit hash (1018 of 300000 pixels, all in that line). The computed styles of
  all 95 sidebar elements are equal.
- **mapbox-gl-draw:** a polygon drawn in the shadow root gives one `drawn` event, and no second
  one after a rerun.

Two changes were needed and apply to every component:
- Streamlit's theme still reaches the shadow root through inherited properties (`color`,
  `font-family`), which made the chrome text white in Source Sans. The mount wrapper sets
  `all: initial`.
- `:root { --mc-* }` and `html, body { … }` match nothing in a shadow root. The mount code
  rewrites them to `:host` and a wrapper class (the CSS is minified, so the match is a regex).

### 2. Events — pass

`setTriggerValue` replaces the nonce. A trigger value is set for one rerun, then is `None`.

| Check | Events |
|-------|--------|
| smoke: one click | 1 |
| smoke: click, `st.switch_page` to page B, back, rerun | 1 (no duplicate) |
| overview: popup "Anriss öffnen" | opens the Anriss once; "Anriss abwählen" returns to the overview with the ring moved, no reopen |
| IFK: "IFK berechnen" on a pixel | selects 1 pixel (`/ifk?x=2613877.5&y=1169882.5`); after "Pixel abwählen" and another rerun, 0 selected |

The views' nonce checks are gone (`_overview_anriss_nonce`, `_ifk_anriss_nonce`,
`_ifk_pixel_nonce`). A trigger needs an `on_<name>_change` callback (a no-op is enough) to
show up in the result.

### 3. Packaging — pass

`frontend/` is the Python package `pgr-atlas-maps` (module `pgr_atlas_maps`, build backend
`uv_build`), a path dependency of the app (`[tool.uv.sources]`, editable).

| Where | Result |
|-------|--------|
| Local dev (editable) | Works. A frontend rebuild is picked up without restarting the app |
| Wheel install | Works, after the change below |
| Docker image | Works in a simulation of the image's install step (`uv export` into a fresh venv, then `streamlit run`). No real image built yet (O1) |
| `tests/components` | Works: a plain harness page mounts the built module in a shadow root (3 tests) |
| AppTest | Works. `map_args` reads `bidi_component` instead of `component_instance`; the 42 overview, IFK and navigation AppTests pass |
| v1 component suite with the shared changes | 102 passed, 1 expected XFAIL (a known bug, fixed since) |

Required changes, found by the spike:
- Streamlit finds a component's `asset_dir` in a `pyproject.toml` **next to the installed
  module**. The repo's `frontend/pyproject.toml` isn't installed by a wheel, so the package
  also needs `frontend/pgr_atlas_maps/pyproject.toml` with `[tool.streamlit.component]`.
- The image install uses `uv export`, which writes `-e ./frontend` for an editable source. The
  image needs `uv export --no-editable`, and `docker/build.sh` plus `build-and-push.yml` need
  to stage `frontend/pyproject.toml` and `frontend/pgr_atlas_maps/` (with `dist/`) into
  `project/`.
- The component registers only under `streamlit run` or AppTest. Importing the wrapper from
  plain Python raises "must be declared in pyproject.toml with asset_dir".
- `app/asgi_app.py` with the cache header middleware, started by `run_app.py` (below).

**Cache headers — pass with a middleware.** Streamlit sends
`Cache-Control: public` for `/_stcore/bidi-components/<component>/<path>`, with no `max-age`,
no `ETag` and no `Last-Modified`, and has no option to change it (hard-coded in
`streamlit/web/server/starlette/starlette_routes.py`). v1's `/component/` route sends the same.
The file names are content-hashed (`map-[hash].js`, `assets/*-[hash].js`), so they can be
cached for a year.

Streamlit 1.64's public `st.App(script_path, middleware=[...])` runs the app's middleware before its
own. The spike's `app/asgi_app.py` (35 lines) sets
`Cache-Control: public, max-age=31536000, immutable` on 200 responses under
`/_stcore/bidi-components/pgr-atlas-maps.map/` that aren't HTML. `run_app.py` starts
`asgi_app.py` instead of `app.py`. `streamlit run` finds the `st.App` and serves it with
uvicorn, the same server it uses for a plain script. The sidecars still start, and `/readyz`
answers 200.

Map assets transferred on the overview (`probe_cache_reload.py`, Resource Timing
`transferSize`; 0 means the browser used its cache without asking the server):

| Load | Streamlit's header | With the middleware |
|------|--------------------|---------------------|
| First load | 484.4 KB | 484.4 KB |
| Reload | 484.4 KB | 0 KB |
| Same URL again | 484.4 KB | 0 KB |
| New tab | 484.4 KB | 0 KB |

With the middleware, `probe_app.py` (overview → Anriss → back → IFK) gives the same result as
without it: no errors, one Anriss open, the ring follows the selection, IFK adds only `ifk`.

### 4. Shared chunks — pass

One Vite (rolldown) multi-entry build: a 1.2 KB entry `map-[hash].js` that loads the view
module on demand, and shared chunks. Static assets are served per component
(`/_stcore/bidi-components/<component>/…`), so chunks can only be shared within one
component. That is why there is **one** v2 component, `pgr-atlas-maps.map`, with a `view`
field, not one component per map.

Bundle sizes (gzip -9 of the built files):

| File | Raw | Gzip |
|------|-----|------|
| `map-[hash].js` (entry) | 2.4 KB | 1.2 KB |
| `maplibre-setup` (MapLibre, pmtiles, proj4) | 1107.7 KB | 285.2 KB |
| `maplibre-gl-worker` | 497.8 KB | 140.8 KB |
| `mount` (shared chrome and CSS) | 141.3 KB | 46.8 KB |
| `overview` | 6.5 KB | 2.9 KB |
| `ifk` | 10.0 KB | 4.1 KB |

| Download | v1 | v2 |
|----------|----|----|
| Overview | 473.7 KB | 476.9 KB |
| Overview, then IFK | 948.3 KB | 481.0 KB |
| All five views | ~2.4 MB | ~0.5 MB (estimate: shared chunks + ~5 KB per view) |

Measured in the browser: on overview → Anriss → overview → IFK, `maplibre-setup`, the worker
and `mount` are each fetched once; the IFK visit adds only `ifk` (4.2 KB). This removes the
repeated MapLibre download.

### 5. Memory — pass

Real app, 20 switches between Übersicht and IFK, forced GC before each sample, exactly one live
map canvas after each switch:

| After switch | 0 | 1 | 2 | 10 | 20 |
|--------------|---|---|---|----|----|
| JS heap (MB) | 19.9 | 25.3 | 26.2 | 28.1 | 28.7 |
| DOM nodes | 668 | 728 | 863 | 1007 | 1187 |
| Listeners | 386 | 418 | 423 | 439 | 459 |

The heap levels off: +0.6 MB from switch 10 to 20. The remaining growth (~18 nodes and 2
listeners per switch) is Streamlit's: a heap snapshot finds 170 detached nodes after 10
switches and 290 after 20, all sidebar buttons and markdown containers, and none from the
map. The map's cleanup runs on every unmount (`map.remove()`, wrapper removed).

### 6. Layout — pass

The element is mounted with `height="content"` and sizes to the wrapper, whose height comes
from CSS: `max(480px, calc(100dvh - 260px))`, 740 px at a 1000 px viewport. No
`setFrameHeight`, no fixed 700/780 px.

## Open points

What the spike did not fully cover, with the recommended way to close each one.

| # | Open point | Recommendation |
|---|------------|----------------|
| O1 | **Real Docker image (criterion 3).** Only the image's install step was simulated (`uv export` into a fresh venv, then `streamlit run`). `docker/build.sh` and `build-and-push.yml` don't stage `frontend/` yet, and no image was built. | Close it in **C-1**, the first PR that ships the package. C-1 adds the staging and `uv export --no-editable`, builds the image locally, and doesn't merge until the pod on Bedag test serves `/_stcore/bidi-components/pgr-atlas-maps.map/…`. Doing it earlier would stage a package that `main` doesn't have. |
| O2 | **Cache headers behind the ingress (criterion 3).** The middleware was measured locally, not behind Bedag's ingress-nginx, which passes `Cache-Control` through unless configured otherwise. | **C-1** ships `asgi_app.py` with the package. Its Bedag test check (O1) also confirms that a map asset returns `max-age=31536000, immutable` there. |
| O3 | **Sidebar screenshot diff (criterion 1).** Closed: the sidebar is unchanged apart from the commit hash in the version line, and all 95 elements have the same computed styles (see criterion 1). | None. |
| O4 | **v1 download size measured from files, not the network.** The v1 numbers in criterion 4 are the built file sizes; the v2 numbers were also checked in the browser. The v1 network probe (`probe_switch_bytes.py`) didn't complete. | No further action. v1 serves each component from its own root, so every view loads its full bundle by construction; the file sizes are what the browser downloads. Re-measure only if before/after network numbers are needed. |
| O5 | **Polygon, not bbox (criterion 1).** The draw check drew a polygon. | No action. `raster_bbox_map` draws with `draw_polygon` too (`frontend/src/raster_bbox_map/drawing.ts`), so this is the mode it needs. |
| O6 | **The pass rule.** The migration stops if any criterion fails. | Closed: all six criteria pass. |

## Consequences for C-1..C-6

- **One component, one dispatcher.** `pgr_atlas_maps.mount_map(view, data, key, events)`
  mounts `pgr-atlas-maps.map`. The JS entry keeps one instance per shadow root: the first
  render creates the view, later renders (reruns) call its `update(data)`, and the cleanup
  (on unmount only, not between reruns) destroys it. Each C PR adds one view module.
- **Reruns are updates.** Streamlit calls the module on every rerun with the same root, so
  each view needs an `update`. The overview applies `highlight_id_anriss` (as v1 does);
  IFK does the same.
- **Shared code takes a root.** Code that used `document.getElementById` takes a
  `Document | ShadowRoot` (`MapDom`); overlays attach to the map container's parent, not
  `document.body`. v1 keeps working with `document` as the default until C-6.
- **Tests.** Component tests mount the built module in a harness page. e2e selects
  `data-testid="pgr-map-<view>"` instead of iframe titles. AppTest reads `bidi_component`.
- **Image build and cache headers.** The packaging changes in criterion 3 and `asgi_app.py`
  land with C-1 (O1, O2).
- **Not covered by the spike:** the `gebaeudeschatten`, `anriss` and `raster_bbox_map` views
  (only mapbox-gl-draw was checked for the last one).
