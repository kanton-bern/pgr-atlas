# probe-core

Shared code of PGR-Atlas and its simulation pipeline: S3 access, the data-lake
schema and read layer, and the derivate computations (IFK, rasters, event export).

Used by:

- the PGR-Atlas app in this repository (`app/`), as a uv workspace member: `uv sync`
  at the repo root installs it editable
- the ProBE simulation and data-lake pipeline, maintained separately. Pipeline-only
  helpers (Ray, DEM) stay there

The pipeline installs it from a release tag of this repository, without the app. Replace
`vX.Y.Z` with an existing release tag:

```toml
dependencies = ["probe-core @ git+https://github.com/kanton-bern/pgr-atlas@vX.Y.Z#subdirectory=packages/probe-core"]
```

Releases are this repository's tags, not the `version` field. Renaming a function or
changing its arguments breaks the pipeline at its next pin bump, so say so in the
release notes, published as the GitHub Release of the tag.

## Modules

| Module | Contents |
|---|---|
| `probe_core.s3` | S3 settings from the environment, boto3 clients, `configure_s3_for_duckdb` (incl. egress proxy), key helpers |
| `probe_core.resources` | DuckDB memory/thread/spill limits from the container's cgroup, else the host |
| `probe_core.campaign` | facts about the MAXI data: physics grid, events per batch, manifest key |
| `probe_core.data_lake.data_lake_schema` | lake layout, column names, constants (reads `data/cfgCom1DFA_template.ini`) |
| `probe_core.data_lake.data_interface` | read layer: gold, event catalog (per-anriss lookups + totals, on S3), hull fragments, stats |
| `probe_core.derivate.ifk_and_raster`, `event_export` | IFK and on-demand rasters, event export. A raster is built in two steps: `build_exceedance_curves` (per pixel and variable, the summed event rate at or above each intensity; the slow gold read) and `raster_from_curves` (seconds, any threshold or return period); a caller can keep the curves under `curves_cache_key`. Each job spills into a folder of its own under `/tmp/duckdb_raster_temp_maxi`, and anything there older than 7 days is swept. The gold x probability-lookup x p_Ablauf join is one function, `_events_sql` (the pipeline's producers use it too); its temp table is `events`, and the curves' columns are `intensity` and `exceedance_rate`. The IFK of an area (rectangle or polygon): a simulation counts once, with its largest intensity over the pixels whose centre lies inside, per variable. Two steps again: `build_area_event_maxima` (one row per simulation reaching the area; the slow gold read, same size limit as a raster) and `compute_ifk_for_area` (joins the probabilities, seconds; the same result shape as `compute_ifk_default`); `write_area_ereignisse` writes the events as CSV or Parquet. The maxima hold no probability, so a caller can keep them per selection (`area_maxima_cache_key`) |
| `probe_core.gebaeudeschatten` | Gebäudeschatten campaign (building footprints as release areas): the affected-mask rules per minimum depth (1 and 10 cm; one definition, used by the pipeline's rasters and the app's explanations), S3 layout, and the read layer of the app's Gebäudeschatten view (one building's rows, one pixel's rows, footprint pixels, building outlines) |
| `probe_core.derivate.derivate_lake` | read side of the derivate lake (`Data-Lake-Derivate/<metric>/…`, written by the pipeline's `derivate/run_derivate.py`): paths, band-name parsing, S3 discovery, cropping a canton mosaic to a selection |

## Configuration

Nothing is read from config files, and importing has no side effects. The
environment is read when a value is used:

| Variable | Default | Used for |
|---|---|---|
| `PROBE_S3_ENDPOINT_URL` | `https://f712.gos3.io` | S3 endpoint (Hosttech; Bedag's is `https://x7ba-s3-kakbfe.infra.be.ch:10443`) |
| `PROBE_S3_REGION` | client default | signing region; Bedag needs `ch-bern-1`, Hosttech accepts any |
| `PROBE_S3_ACCESS_KEY_ID` / `PROBE_S3_SECRET_ACCESS_KEY` | — | S3 credentials. `HOSTTECH_BERLIN_OBJECT_STORAGE_ACCESS_KEY` / `_KEY_SECRET` (the pipeline's names) work as a fallback (the new names win when both are set) |
| `PROBE_S3_BUCKET` | `maxi` | the one bucket everything is read from (gold, catalog, derivates, tilesets) |
| `PROBE_CACHE_DIR` | `~/.cache/probe-core` | per-event envelope GeoJSON cache (created on first write) |
| `PROBE_DUCKDB_MAX_TEMP_SIZE` | DuckDB's own | cap for DuckDB spill files |
| `PROBE_DUCKDB_MEMORY_FRACTION` | `0.25` | share of the container's (or host's) memory one DuckDB connection may use, above 0 and at most 1; the result stays within 512 MB and 4 GB |
| `PROBE_RASTER_MAX_ROWS` | `900000000` | largest on-demand raster, in gold rows read (estimated from the gold file sizes, ~15 min) |
| `https_proxy`, `http_proxy`, `no_proxy` | — | egress proxy, also applied to DuckDB |

S3 requests are path-style (`https://<endpoint>/<bucket>/<key>`) for boto3 and
DuckDB, and boto3 sends checksums only where the S3 API requires them. Both are
needed for Bedag's StorageGRID (its network policy allows only the endpoint's
host name) and work unchanged against Hosttech.

No local state: per-anriss lookups and the catalog totals come from the event
catalog at the gold bucket's root (`maxi_event_manifest_by_id_anriss.parquet`, sorted by
`id_anriss`, and `maxi_event_manifest_stats.json`, both built by the pipeline), and the finalized gold kacheln are listed
from S3 into memory (once, on first use or `refresh_gold_manifest()`).
`refresh_gold_manifest()` also returns `newest_modified`, when the newest gold file was
written, from the same listing.

Loading a `.env` file is the job of the entry point (`load_dotenv()` before the
first S3 call).

## Development

From the repository root, together with the app (`pyproject.toml` there has the tool
settings):

```bash
uv sync
.venv/bin/python -m pytest packages/probe-core/tests
.venv/bin/ruff check packages && .venv/bin/ruff format --check packages
```
