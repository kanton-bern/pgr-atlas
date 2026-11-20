# App source

The code of the PGR-Atlas app as it is built into the image.

Everything the app shares with the pipeline — S3 access, the data-lake schema
and read layer, the derivate computations (IFK, rasters, event export) — comes
from the package `probe-core` in [`../packages/probe-core`](../packages/probe-core),
a uv workspace member of this repo.

## What's here

```
  app.py                       the app: cold start, sidebar, st.navigation with one page per view
  views/overview.py            the Simulierte Ereignisse view (views/__init__.py says how views are wired)
  views/ifk.py                 the IFK view: a pixel's curves
  views/ifk_area.py            ... and an area's (rectangle or polygon): sidebar, job, curves, outline, Rohdaten
  views/anriss.py              the Anriss view (one Anriss's scenarios)
  views/raster_karten.py       the Raster-Karten view (ad-hoc rasters for a drawn area)
  views/raster_derivate.py     the Raster-Derivate view (precomputed rasters and ZIPs)
  views/expert_mode.py         Experten-Modus: its sidebar panel and the overrides it
                                passes to IFK and Raster-Karten
  ui_common.py                 UI helpers used by more than one view
  texts.toml                   every UI text, German and French (docs/texts-guide.md)
  ui_text.py                   t(): looks a text up in texts.toml; number formatting
                                in the session's language
  map_labels.py                the map components' texts (labels) and number locale
  language.py                  the session's language: from ?lang=, kept in the URL, DE | FR
  state.py                     session-state defaults and the per-Anriss cache
  run_app.py                   container entrypoint (../docker/Dockerfile's CMD):
                                loads a local .env if present, starts
                                pmtiles_server/derivate_bbox_server eagerly, then
                                runs Streamlit in the same process (see its
                                docstring for the multi-replica bug it fixes)
  pmtiles_server.py            pmtiles Range-request proxy (Tornado, own port)
  derivate_bbox_server.py      raster bbox-crop server (Tornado, own port) for the
                                Raster-Derivate view -- reads the derivate lake's
                                canton mosaics via probe_core.derivate.derivate_lake
  cors.py                      allowed-origin CORS headers for both Tornado servers
                                (SIDECAR_ALLOWED_ORIGINS)
  polygon_upload.py            polygon upload parsing with name/size/ZIP limits
  area_upload.py               the sidebar's area upload (uploader, CRS picker), for the views that take an area
  area_job.py                  a long job over an area on a background thread: the job card, "Abbrechen", the run slot
  derivate_download.py         size estimate and cap for the derivate ZIP bundles
  overview_component.py        + overview/dist/        (built from frontend/src/overview/)
  ifk_map_component.py         + overview_ifk/dist/    (built from frontend/src/overview_ifk/)
  raster_bbox_component.py     + raster_bbox_map/dist/ (built from frontend/src/raster_bbox_map/)
  anriss_map_component.py      + anriss_map/dist/      (built from frontend/src/anriss_map/)
  gebaeudeschatten_map_component.py + gebaeudeschatten_map/dist/ (built from frontend/src/gebaeudeschatten_map/)
  gebaeudeschatten_view.py     the Gebäudeschatten view (sidebar + main area): a building's own,
                                ring and shadow pixels, the buildings reaching a pixel, and why each
                                pixel counts or not. Rules and reads come from probe_core.gebaeudeschatten;
                                the view only shows up where the gold bucket holds that data
                                (published there by the pipeline)
  anriss_export.py             the Anriss view's download names and Rohdaten CSV columns
  ifk_export.py                the same for the IFK view's downloads
  ifk_charts.py                the IFK charts (a pixel's or an area's) and their CSV/PNG downloads
  anriss_prefetch.py           reads an anriss's data while its map popup is open
  ifk_prefetch.py              computes a pixel's IFK while its map popup is open
  s3_target.py                 the S3 target the app reads, named in the environment
                                (Bedag stages: PGR_ATLAS_S3_TARGET=bedag, their own S3)
  work_dirs.py                 private, self-cleaning scratch folders for uploads and raster results
                                (~/probe_data/app_work; anything older than 7 days is swept)
  raster_utils.py
  styles/                      tokens.css (design tokens, shared with the map components) and app.css
  static/                      logos and the Roboto font, served by Streamlit (enableStaticServing)
  .streamlit/config.toml       the theme (Kanton Bern style guide) and static serving; read from
                                app/, so it applies to the image, local runs and the e2e tests
```

The overview and Prozessquellen tilesets are built offline by the pipeline. What
the maps expect from them:
[frontend/README.md, "Tilesets"](../frontend/README.md#tilesets).

## Changing shared code

A change to anything imported from `probe_core` is made in
`../packages/probe-core/src/probe_core/`, in the same PR as the app code that
needs it. `uv sync` installs the package editable, so the app sees the change
at once. Its tests are in `../packages/probe-core/tests` and run with the
app's (`pytest` from the repo root).

The ProBE simulation pipeline, maintained separately, uses the same package and
pins a release tag of this repo; see [`../packages/probe-core/README.md`](../packages/probe-core/README.md).
Renaming a function or changing its arguments breaks the pipeline at its next
pin bump, so say so in the release notes (the GitHub Release of the tag).

## Configuration

Deployment settings are environment variables; there is no config file.
probe-core's README has the full list of its own. What the stages set:

| Variable | Where it's set in the clusters |
|---|---|
| `PROBE_S3_ENDPOINT_URL`, `PROBE_S3_REGION`, `PROBE_S3_BUCKET` (the one bucket the app reads everything from; default `maxi`), `PROBE_S3_ACCESS_KEY_ID` / `PROBE_S3_SECRET_ACCESS_KEY` | set at startup from the picked S3 target (next row); not set directly in the Bedag stages |
| `PGR_ATLAS_S3_TARGET` + `PGR_ATLAS_S3_BEDAG_*` | both Bedag stages: one S3 target, `bedag` (Bedag's own S3; endpoint, region, bucket and a read-only key from the operator's Secret `s3-pgr-atlas-ro`, [docs/s3.md](../docs/s3.md)). `PGR_ATLAS_S3_TARGET=bedag` at the top of the env in the stage `values.yaml` picks it. The app in the stages has no Hosttech key and no proxy variables. The sidebar footer shows version, S3 source and bucket |
| (none) | `deploy/stages/<stage>/pgr-atlas/secrets/secret-values.yaml` — SOPS-encrypted Helm values setting the container's `envSecret`; empty, so the chart renders no Secret for the app. The s3-toolbox's Hosttech key is its own SOPS-encrypted Secret, `deploy/stages/<stage>/s3-toolbox/hosttech-key-secret.yaml` |
| `PMTILES_*`, `DERIVATE_BBOX_*` | stage `values.yaml` |
| `PROBE_DUCKDB_MAX_TEMP_SIZE` | stage `values.yaml` — caps DuckDB's on-disk spill; must stay below the spill volume |
| `PROBE_DUCKDB_MEMORY_FRACTION` | not set, so probe-core's default applies: one DuckDB connection may use 25 % of the container's memory, at most 4 GB (2 GiB of 8Gi on test, 4 GiB of 16Gi on prod). A higher value means less spilling on large rasters on test; on prod the 4 GB ceiling already applies. Check the app's peak memory first |
| `http_proxy`, `https_proxy`, `no_proxy` | not set in the app's stages; honoured when set, e.g. for a local run behind a proxy. boto3 reads them; DuckDB only through `probe_core.s3.configure_s3_for_duckdb` |

**Encrypting secrets**: `.sops.yaml` holds Bedag's original rules (their PGP key,
`aw3-gitops-sops.asc`). The private key is in Bedag's cluster (the Secret
`sops-gpg` in the project's namespaces), where Flux decrypts with it
([docs/deployment-process.md](../docs/deployment-process.md), "Secrets"). To
change a credential there is no need to decrypt: write the complete plaintext
file again and encrypt it.

```bash
sops --encrypt --in-place deploy/stages/<stage>/pgr-atlas/secrets/secret-values.yaml
```

Run it from the repo root: sops picks the key by matching the path as typed.

**The S3 target (Bedag stages):** a stage names its S3 as a target,
`PGR_ATLAS_S3_<NAME>_{ENDPOINT_URL,REGION,BUCKET,ACCESS_KEY_ID,SECRET_ACCESS_KEY}`,
and picks it with `PGR_ATLAS_S3_TARGET=<name>`; `run_app.py` copies it onto
probe-core's `PROBE_S3_*` before anything reads S3. Both stages have one
target, `bedag`. The app cannot switch targets while it runs. Without
`PGR_ATLAS_S3_TARGET` (local work) nothing changes. The sidebar
footer always shows the version, the S3 source (derived from the endpoint in
use, not the target's name) and the bucket probe-core actually bound.

## Path convention

The repo keeps the app directly in `app/`. In the image it lives at `/app`
(user `app`, UID 10001, `HOME=/home/app`). It writes only to two folders, both set
by environment variable in `../docker/Dockerfile`:

| Variable | In the image | Holds |
|---|---|---|
| `PROBE_CACHE_DIR` | `/data/cache` | probe-core's per-event envelope cache |
| `PROBE_WORK_DIR` | `/data/work` | uploads, raster jobs, and the maxima and Rohdaten of an area's IFK, swept after 7 days (`work_dirs.py`) |

The Bedag stages mount an emptyDir at each and set the same variables
(`../deploy/stages/*/pgr-atlas/values.yaml`), so a stage keeps working whichever
image it runs. Outside the image the defaults apply (`~/probe_data/app_work` and
probe-core's own). The app keeps no local state:
the event catalog and the gold manifest come from S3.

## Verifying a change

`/_stcore/health` and `curl /` return before Streamlit runs the script body
(that happens when a session opens), so they miss script-level bugs. Use `AppTest`, which runs
`app.py` in-process and reports exceptions, in a **fresh** container (a
separate process, so it also catches import-time problems the running app has
long since passed):

```bash
docker run --rm <S3 env as in ../README.md> pgr-atlas:local \
  python3 -c "from streamlit.testing.v1 import AppTest; at = AppTest.from_file('app.py', default_timeout=240); at.run(); print(at.exception)"
```

An empty `ElementList()` means no exception.

In a running container, `curl localhost:8505/readyz` returns `ok` once Streamlit,
the tile proxy and the crop server all answer (`503 not ready` otherwise).
`/readyz` does not touch S3. `curl localhost:8505/readyz-s3` does: it returns
`ok` when the tile proxy's last S3 check (one `HeadBucket` a minute, with the
app's key) reached the bucket, and `503 s3 not reachable` otherwise.
`/metrics` gives the same result to Prometheus
([docs/monitoring.md](../docs/monitoring.md), section 9).

The unit tests and lint need no credentials (S3 is mocked) and run in CI on
every pull request that changes what they check
([tests/README.md](../tests/README.md#test-scope)). The commands are in
[AGENTS.md](../AGENTS.md#commands).

## The image is public

Everything in this folder (except what `../docker/.dockerignore` excludes) is
copied into the image on ghcr.io, which
anyone can pull. Never add credentials, `.env` files or infrastructure config
here.
