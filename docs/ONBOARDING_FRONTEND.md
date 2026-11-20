# Onboarding: PGR-Atlas frontend

## Who this is for

For developers new to the map components. Part 1 explains how the app and its maps fit
together, Part 2 gets the app running locally with a live frontend build, and Part 3 says how a
change is shipped.

You're joining `pgr-atlas` to work on the frontend. The app is **PGR-Atlas** —
Kanton Bern's process-source / hazard-simulation explorer. It is a Streamlit app with five
custom MapLibre map frontends written in TypeScript, and it reads all its data from S3 at
runtime. The repo is the single source for code, image, CI and deployment.

The map UIs are embedded into Streamlit as bidirectional custom components. All five
(**Simulierte Ereignisse**, **IFK**, the **raster map** for Raster-Karten and Raster-Derivate, the
**Anriss** map and **Gebäudeschatten**) are built from `frontend/src/<component>/` with Vite
into `app/<component>/dist/` (`npm ci && npm run build` in `frontend/`, see
`frontend/README.md`). The libraries are bundled; nothing loads from a CDN. The edit loop is
"save → build → reload browser".

The container needs to see your build output, which is what the run setup below arranges.

To see anything render you need the app running against real S3 data, so this guide's first
half is getting the container up, and the second half is the architecture you'll be editing.

Prerequisite: you have the S3 credentials. You'll run the **prebuilt public image** under
Docker (no local image build needed).

---

## Part 1 — The mental model (read this before running anything)

### One container, three processes

`run_app.py` is the entrypoint. It starts two Tornado servers as daemon threads, *then* runs
Streamlit in the same process. Before that it loads a `.env` from
the working directory if one exists (`load_dotenv()`); in the container there
is none and the environment is used as is.

| Port | Process | Role |
|---|---|---|
| 8501 | `streamlit run app.py` | the app + its websocket `/_stcore/stream` |
| 8505 | `pmtiles_server.py` | proxies the overview PMTiles archive from S3 **with real HTTP Range support** (Streamlit's static handler ignores `Range`, which breaks PMTiles); also serves the gold and Raster-Derivate coverages as `/coverage.geojson?v=<version>` (the components get only the version as an arg) |
| 8503 | `derivate_bbox_server.py` | crops precomputed hazard rasters to a bbox on the fly, serves `/bbox.png` and `/value.json`; also serves finished Raster-Karten jobs as `/job/<id>/<var>.png`, `.f32` (hover grid) and `.tif`, the Raster-Derivate ZIPs as `/download/<id>.zip`, streamed, and the Rohdaten of an area's IFK as `/file/<id>` (see `raster_jobs.py`) |

**The browser talks to all three directly.** This is the single most important thing for
frontend work: the Simulierte Ereignisse code (`frontend/src/overview/`) fetches tiles from port 8505 and the raster
map (`frontend/src/raster_bbox_map/`) fetches PNGs from port 8503. Publishing only 8501 gives you a
silently blank map with no error anywhere.

### How the maps are embedded

All five are **Streamlit bidirectional components** via `declare_component(path=...)`, not
`components.html`. Streamlit serves each asset directory as its own static root and mounts
`index.html` in an iframe.

| Python wrapper | Component name | Asset dir |
|---|---|---|
| `app/overview_component.py` | `maplibre_overview` | `overview/dist/` (built) |
| `app/ifk_map_component.py` | `ifk_pixel_map` | `overview_ifk/dist/` (built) |
| `app/raster_bbox_component.py` | `raster_bbox_map` | `raster_bbox_map/dist/` (built) |
| `app/anriss_map_component.py` | `anriss_result_map` | `anriss_map/dist/` (built) |
| `app/gebaeudeschatten_map_component.py` | `gebaeudeschatten_map` | `gebaeudeschatten_map/dist/` (built) |

There is **no template substitution**. Every piece of config (ports, path prefixes, filenames,
overlays, initial viewport) reaches the JS as *render arguments* over `postMessage`. Each HTML
waits for a `streamlit:render` event and reads `event.data.args`.

A subtle difference worth knowing before you debug: `frontend/src/overview/main.ts` initialises
the map **once** and ignores later renders, `frontend/src/overview_ifk/main.ts` applies later
renders to the anriss circles, their legend and the pixel squares only, while
`frontend/src/raster_bbox_map/map.ts` applies **every** render, comparing each part by a key,
so Python can push new overlays and selections into an already-mounted map. The Anriss and
Gebäudeschatten maps (`frontend/src/anriss_map/map.ts`, `frontend/src/gebaeudeschatten_map/map.ts`)
do the same.

### JS → Python

Raw `window.parent.postMessage` implementing the component protocol inline — no
`streamlit-component-lib` (`frontend/src/shared/streamlit-bridge.ts`):

```js
function setComponentValue(value) {
  toStreamlit('streamlit:setComponentValue', { value, dataType: 'json' });
}
```

Every payload carries a **`nonce`**, and Python compares the nonce, not the payload
(e.g. the Simulierte Ereignisse handler, `_handle_click` in `views/overview.py`) — Streamlit echoes the last component value back on every rerun, so
without a nonce a single click would re-fire forever.

### URL building: local vs. cluster

The components build URLs for the two Tornado backends in one place, with one ternary:

```ts
// frontend/src/shared/urls.ts (httpBase)
return sidecar.pathPrefix
  ? `${page.protocol}//${page.host}${sidecar.pathPrefix}`            // cluster
  : `${page.protocol}//${page.hostname}:${String(sidecar.port)}`;   // local
```

- **In the clusters**, `PMTILES_PATH_PREFIX=/pmtiles-data` and
  `DERIVATE_BBOX_PATH_PREFIX=/derivate-bbox` are set, so everything goes through one host and
  the Ingress strips the prefix (`deploy/stages/test/pgr-atlas/values.yaml`).
- **Locally** leave both prefixes empty (the default) and the browser hits `localhost:8505` /
  `localhost:8503` directly.

Shared code (`frontend/src/shared/`) is bundled into each component's build. A component can't
load files from a sibling directory at runtime: Streamlit's component handler rejects any path,
symlinks included, that resolves outside the component's own directory.

### Backend / data model in brief

- **All data is in S3** (for local work Hosttech, `https://f712.gos3.io`). The image holds code
  only; even the event manifest is read from S3 at runtime. The one bucket is set by
  `PROBE_S3_BUCKET`: `adelboden-test` (a region-scoped copy of the data lake) for local work and
  CI; `maxi` holds the full canton. The Bedag stages read Bedag's copies of the two.
- **The data layer is the `probe-core` package** in `packages/probe-core`. S3 access, the
  data-lake schema and DuckDB read layer, and the derivate computations are imported from
  `probe_core.*` (in `app.py`, the views and the sidecars). The pipeline uses the same package,
  so changes there need care (`app/README.md`, "Changing shared code").
- **Credentials** are `PROBE_S3_ACCESS_KEY_ID` / `PROBE_S3_SECRET_ACCESS_KEY`, read from the
  environment by probe-core and used by both boto3 and DuckDB.
- **Local state**: none. The event catalog (per-anriss lookups, totals) and the
  finalized gold kacheln come from S3. Only `/data/cache` (envelope cache,
  `PROBE_CACHE_DIR`) and `/data/work` (uploads, rasters, `PROBE_WORK_DIR`) are written. Ephemeral.
- **S3 is first touched when a session runs `app.py`.** With bad or missing credentials the
  container starts fine and the app fails on the first browser session.
- **Paths in the image:** the repo's `app/` is `/app` (user `app`, UID 10001); see
  `app/README.md`, "Path convention".

### Where to edit, per view

`app.py` is the entrypoint: page config, the stylesheet, the cold-start status, the sidebar
shell, `st.navigation` and the version footer. Each view is its own module. Navigation is
`st.navigation` with one `st.Page` per view (hidden), driven by the sidebar buttons in
`app.py`; each page function in `app.py` calls its view's `render()` with the servers it needs.

| View | URL | Python entry | Frontend file you'd edit |
|---|---|---|---|
| Simulierte Ereignisse (overview) | `/`, `/?z=&lat=&lon=` | `views/overview.py` | `frontend/src/overview/` + `frontend/src/shared/` |
| Anriss (opens from the map) | `/anriss?id=<id>` | `views/anriss.py` | `frontend/src/anriss_map/` + `frontend/src/shared/` |
| Raster-Karten (ad hoc) | `/raster-karten` | `views/raster_karten.py` | `frontend/src/raster_bbox_map/` + `frontend/src/shared/` |
| Raster-Derivate | `/raster-derivate` | `views/raster_derivate.py` | `frontend/src/raster_bbox_map/` + `derivate_bbox_server.py` |
| IFK-Berechnung | `/ifk`, `/ifk?x=&y=` | `views/ifk.py` | `frontend/src/overview_ifk/` + `frontend/src/shared/` |
| Gebäudeschatten | `/gebaeudeschatten` (where the bucket has its data) | `gebaeudeschatten_view.py` | `frontend/src/gebaeudeschatten_map/` + `frontend/src/shared/` |

Shared Python modules, all in `app/`:

- `state.py`: session defaults (`init_session_state`) and the per-Anriss cache, which keeps
  the last 5 Anrisse (`AnrissCache`).
- `texts.toml` and `ui_text.py`: every UI text is an entry in `texts.toml` (German and
  French); `ui_text.t("key", **values)` looks it up in the session's language. A failure
  message has no exception text; the view logs the details with `logger.exception`.
- `ui_common.py`: helpers used by two or more views (coverage load, the Anriss lookup form,
  the Anriss link).
- `views/expert_mode.py`: the Experten-Modus sidebar, drawn by the IFK and Raster-Karten
  pages.
- `styles/app.css`: the global stylesheet, with the colours as `:root` tokens.

Ruff enforces complexity ≤ 8, ≤ 5 arguments and a statement limit per function
(`pyproject.toml`). The view modules and `app.py` have no ignores.

**Adding a view:**

1. Write `app/views/<view>.py` with a `VIEW_MODE` key and a `render(...)` that takes the
   servers it needs. Its texts go into `texts.toml`, its session keys into `state.py`.
2. In `app.py`, add a page function and an
   `st.Page(..., title=ui_text.t("nav.<view>"), url_path=...)`
   to `_PAGES`. The sidebar buttons are drawn from `_PAGES`.
3. Tests: an AppTest module in `tests/apptest/` (`conftest.current_view` tells which view is
   shown), the view in `VIEWS` in `tests/e2e/conftest.py`, and its flows in
   `docs/frontend-app/behavior-inventory.md`.

**Fragment rules.** A widget change inside an `@st.fragment` reruns only that function, not
the page.

- No `st.sidebar` inside a fragment; Streamlit raises. A view whose sidebar shows something
  about the map selection keeps the map outside a fragment (Raster-Karten and
  Raster-Derivate show the drawn area's size).
- To leave the view from a fragment, call `st.switch_page` (IFK's Anriss popup does).
  `st.rerun(scope="fragment")` works only in a fragment run; a click handled during a full
  run needs `scope="app"` (`views/ifk.py`, `_rerun`).
- Background work runs on a thread with its `Future` in session state. An
  `@st.fragment(run_every=0.5)` polls it and calls `st.rerun()` once when it's done (the
  Raster-Karten job, the Anriss hull read).
- Keep the nonce check of a component click outside any `@st.cache_*` function.

**Links.** A view reads its link with a pure function (`viewport_from_query`,
`pixel_from_query`, `id_from_query`), which raises `ValueError` for a bad one; the view then
shows a `ui_text` message. It writes the link with `st.query_params` or
`st.switch_page(page, query_params=...)`. Those functions have unit tests in
`tests/test_<view>_view.py`.

Cross-cutting chrome — basemap switcher, zoom readout, coordinate search, LV95 transform,
Prozessquellen layer — lives once in `frontend/src/shared/map-controls.ts`. View-specific
interaction (click priority, draw modes) stays in each component's `frontend/src/<name>/`.

---

## Part 2 — Step-by-step local run

### Step 0 — Prerequisites

- **Docker**, installed and running.
- **The image is amd64-only** (rasterio has no linux/arm64 wheel). On an arm64 machine
  (Apple Silicon) it runs under emulation: expect a slow start, and keep
  `--platform linux/amd64` on both `pull` and `run` as below.
- **S3 credentials**: `PROBE_S3_ACCESS_KEY_ID` and
  `PROBE_S3_SECRET_ACCESS_KEY` for the test bucket, issued by the project owner.
  Keep them in the repo's `.env` file, which is git-ignored
  ([README](../README.md#running-locally)); Step 1 loads it into your shell.

### Step 1 — Load credentials into your shell

```bash
cd /path/to/pgr-atlas
set -a; source .env; set +a
echo "${PROBE_S3_ACCESS_KEY_ID:?not set}" >/dev/null && echo "creds loaded"
```

### Step 2 — Pull the image

The GHCR package is public; no `docker login` needed.

```bash
docker pull --platform linux/amd64 ghcr.io/skerlakanalytics/pgr-atlas:<tag>
```

Use the release Bedag test runs rather than `:main`, so what you see locally matches test. The
current value is `image.tag` in `deploy/stages/test/pgr-atlas/values.yaml` (for example
`v0.12.1`); substitute it for `<tag>` here and in the `docker run` commands below.
Always use `ghcr.io` directly — `artifacts.bedag.cloud/ghcr/...` in the stage values is
Bedag's mirror and is not reachable outside their network.

### Step 3 — Run with a live frontend mount

Build the frontend first (`cd frontend && npm ci && npm run build`): the mounts below
need each component's `app/<component>/dist/`. Node is only needed on your machine, never in
the container.

The `-e VAR` form (no `=value`) passes the secret through from your shell without typing it
into the command. The five `-v` mounts make frontend builds live: Streamlit reads component
files from disk on every request, so a browser reload picks up a new build with no container
restart.

Each `-v` flag is `"host_path:container_path"`. The left side uses `$PWD` (your machine,
relative to the repo root — hence the `cd` first). The right side (`/app/...`)
is the path **inside the container**: the image copies `app/` there (see "Paths in the image"
in the data model section above).

```bash
cd /path/to/pgr-atlas

docker run --rm -d --name pgr-atlas --platform linux/amd64 \
  -p 8501:8501 -p 8505:8505 -p 8503:8503 \
  -e PROBE_S3_ENDPOINT_URL=https://f712.gos3.io \
  -e PROBE_S3_BUCKET=adelboden-test \
  -e PMTILES_PORT=8505 -e PMTILES_BIND=0.0.0.0 \
  -e DERIVATE_BBOX_PORT=8503 -e DERIVATE_BBOX_BIND=0.0.0.0 \
  -e PROBE_S3_ACCESS_KEY_ID \
  -e PROBE_S3_SECRET_ACCESS_KEY \
  -v "$PWD/app/overview/dist":/app/overview/dist:ro \
  -v "$PWD/app/overview_ifk/dist":/app/overview_ifk/dist:ro \
  -v "$PWD/app/raster_bbox_map/dist":/app/raster_bbox_map/dist:ro \
  -v "$PWD/app/anriss_map/dist":/app/anriss_map/dist:ro \
  -v "$PWD/app/gebaeudeschatten_map/dist":/app/gebaeudeschatten_map/dist:ro \
  ghcr.io/skerlakanalytics/pgr-atlas:<tag>
```

**`PMTILES_PORT` defaults to 8505** in `run_app.py`, `app.py` and the component wrappers,
so it is set above only for clarity.

**`SIDECAR_ALLOWED_ORIGINS`** (optional): the tile proxy and the crop server send CORS headers
only to these origins. The default, `http://localhost:8501,http://127.0.0.1:8501`, covers
this local setup, where the page on 8501 fetches from 8505 and 8503. Set it (comma-separated)
only if you open the app under another origin. Deployments need no value: behind the ingress
everything is on one origin.

Mount only these five directories, not all of `app/`: the Python files are baked into the
image anyway.

### Step 4 — Verify it actually works

Health alone proves nothing: Streamlit only executes `app.py`'s body on websocket/session
init, so `/_stcore/health` returns OK for an app that crashes on every page load. Check in
this order:

```bash
docker logs -f pgr-atlas          # wait for "You can now view your Streamlit app"

# all three servers answer?
curl -s http://localhost:8505/readyz                                                       # expect "ok"

# each sidecar on its own
curl -s http://localhost:8505/healthz; curl -s http://localhost:8503/healthz               # expect "ok" twice
```

`/coverage.geojson` has no version-free check: without `?v=<version>`, or with a version the
app hasn't published yet, it answers `404`. The maps request it with the version from their
args, so check it in the browser's network tab once a map view has rendered.

`/readyz` returns `503 not ready` while Streamlit or the crop server doesn't answer. The
image's Docker `HEALTHCHECK` uses it too. If a sidecar thread dies, a watchdog exits the
process, so Docker or Kubernetes restarts the container.

Then the real checks:

1. **Open http://localhost:8501** in a browser and let a session start. First load is slow
   (S3 + DuckDB initialisation).
2. **Simulierte Ereignisse must render tiles** — exercises the pmtiles path end to end.
3. **Raster-Karten (ad hoc): pan/zoom** — exercises the derivate-bbox path (`/bbox.png` fires
   on a 200 ms debounce as you move the map).
4. **Script-level check** — simulates a real browser session and reports any exception
   `app.py` would throw on load. Must run in a **separate, temporary container** — not
   `docker exec` into the running one, so it starts from a clean process and also catches
   import-time problems the running app has already passed.

```bash
docker run --rm --platform linux/amd64 \
  -e PROBE_S3_ENDPOINT_URL=https://f712.gos3.io \
  -e PROBE_S3_BUCKET=adelboden-test \
  -e PMTILES_PORT=8505 \
  -e PROBE_S3_ACCESS_KEY_ID \
  -e PROBE_S3_SECRET_ACCESS_KEY \
    ghcr.io/skerlakanalytics/pgr-atlas:<tag> \
  python3 -c \
    "from streamlit.testing.v1 import AppTest; \
     at = AppTest.from_file('app.py', default_timeout=240); at.run(); print(at.exception)"
```

`ElementList(_list=[])` means no exception — the app is healthy. Anything else is a real bug.

This check is a **one-time setup verification**, not part of the regular edit loop. It catches
Python-level crashes (bad credentials, import errors, missing S3 manifest). It does not catch
JS bugs — those only show up in the browser. Once the app is confirmed healthy, you don't need
to re-run it unless you change Python files (`app.py`, `app/views/`, the component wrappers,
or the Tornado servers).

### Step 5 — Your edit loop

- **HTML / TS / CSS** (`frontend/src/`): keep `npm run dev:watch` running in `frontend/`. It
  rebuilds a component's `dist/` when a file the component imports changes. Save, wait for the
  watcher's `built in` line, then hard-reload the browser (⌘⇧R — the component iframe caches
  aggressively). No restart needed.
- **Python** (`app.py`, `app/views/`, the `*_component.py` wrappers, the Tornado servers):
  not mounted, so `docker restart pgr-atlas`. To iterate on Python heavily, mount the files
  you change, e.g. `-v "$PWD/app/views":/app/views:ro` — but treat
  restart as the reliable path since Streamlit's file watcher behaviour through bind mounts
  varies by editor.
- **Debugging the JS**: open devtools on the *iframe* (right-click inside the map → Inspect).
  Filter the Network tab to `8505` / `8503` to see exactly what the component is asking for.
  A failed tile or crop request shows a status box on the map
  (`setMapStatus` in `map-controls.ts`) and an entry in the console, not a blank map.
- **Tests and lint** (no credentials needed; the S3 calls are mocked): the commands in
  [`AGENTS.md`](../AGENTS.md#commands), the tiers in [`tests/README.md`](../tests/README.md).

### Step 5a — A worked example: restyling the zoom readout

This walks the frontend loop once. The change is small and revertible: show the
bottom-left zoom pill with one decimal (`Zoomstufe = 12.3` instead of `Zoomstufe = 12.34`)
and give it the Anthrazit brand background instead of translucent black.

**Find the code before touching it.** Search for it rather than guessing a path:

```bash
rg -n "zoom-debug" frontend/src/
```

The hits are `initZoomDebug` in `frontend/src/shared/map-controls.ts` and the `#zoom-debug`
rule in `frontend/src/shared/map-controls.css`. Both are in `src/shared/`, so the change
reaches every map that imports them. That search *is* the blast-radius check. The words
themselves ("Zoomstufe = {zoom}") are not in the frontend: they are the entry
`[map.chrome.zoom_level]` in `app/texts.toml`, which reaches the maps as a render arg.

**Start the watcher** in a second terminal and leave it running:

```bash
cd frontend && npm run dev:watch
```

**Edit the TS.** In `initZoomDebug`, change the number of digits:

```ts
// before
const zoom = formatNumber(map.getZoom(), texts.locale, { digits: 2, group: false });
// after
const zoom = formatNumber(map.getZoom(), texts.locale, { digits: 1, group: false });
```

**Edit the CSS.** In the `#zoom-debug` rule of `map-controls.css`, swap the `background`
value for a token:

```css
/* before */  background: rgba(0, 0, 0, 0.65);
/* after  */  background: var(--pgr-brand);
```

`--pgr-brand` is defined in `app/styles/tokens.css`, which `map-controls.css` imports, and
also colours the active map buttons — using the token keeps the chrome consistent. Don't
hard-code its hex value: a later colour change in `tokens.css` would miss it.

**Hard-reload IFK-Berechnung.** Wait for the watcher's `built in` lines, then ⌘⇧R on
http://localhost:8501. No restart is needed: the watcher rewrote `app/overview_ifk/dist/`,
the bind mount from Step 3 shows it to the container, and Streamlit reads it from disk.

The readout should now be an Anthrazit pill reading `Zoomstufe = 12.3`.

**If the readout is unchanged**, look at the watcher's output for a build error first. Then
right-click inside the map → Inspect → Network tab, hard-reload, and check that the
component's `index.html` loads a new `assets/index-<hash>.js` (the hash changes with every
build). If it loads the old one, re-check the five `-v` flags from Step 3.

**Check the blast radius.** Switch to **Simulierte Ereignisse**, **Raster-Karten (ad hoc)** and
**Anriss**: all show the new pill, because every map calls `initChrome` from
`map-controls.ts`. The scoping rule:

| Edit here | Affects |
|---|---|
| `frontend/src/shared/*` | every component that imports the file |
| `frontend/src/<component>/*` | that component only |

`frontend/src/overview/index.html`'s entire inline `<style>` block is one rule —
`#tl-stack { top: 70px; }` — which is what a view-only override looks like.
Anything that only Simulierte Ereignisse needs goes there, not in `map-controls.css`.

**Revert when done.** This example is a throwaway:

```bash
git checkout -- frontend/src/shared
```

The watcher rebuilds; hard-reload IFK-Berechnung and the black pill reading
`Zoomstufe = 12.34` is back. Stop the watcher with Ctrl-C.

If you are keeping the change instead: branch off `main` and follow Part 3.

**What this example exercised:**

| Mechanism | Where it appeared |
|---|---|
| `npm run dev:watch` rebuilds `dist/` on save | Edit TS/CSS → hard-reload |
| Bind mount of `dist/`, no container restart | "Hard-reload IFK-Berechnung" |
| Shared-vs-component blast radius | "Check the blast radius" |

---

## Part 3 — Shipping a frontend change

Open a pull request into `main` as [`CONTRIBUTING.md`](../CONTRIBUTING.md) describes; never
push to `main`, Bedag's Flux deploys from it. A merge builds `:main` but **changes nothing that
runs on the clusters**: a stage moves only when a release tag is set in its `values.yaml`.
Releasing, deploying to test and prod, and rolling back:
[deployment-process.md, section 5](deployment-process.md#5-releasing-a-version).

---

## Gotchas

- **All three ports**: the browser talks to 8501, 8505, and 8503 directly — publish all three.
- **`--platform linux/amd64`** on both `pull` and `run` (arm64 machine, amd64-only image).
- **`/_stcore/health` passing ≠ the app works.** Use a real browser session + `AppTest`.
- **Nonce, not payload**, drives component round-trips (`_handle_click` in
  `views/overview.py`).
- **Data-layer code is shared with the pipeline.** Anything imported from `probe_core` lives
  in `packages/probe-core` and is used by the pipeline too (`app/README.md`, "Changing shared
  code").
