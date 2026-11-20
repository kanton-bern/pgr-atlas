# PGR-Atlas -- standalone, S3-backed image.
#
# This image ships CODE ONLY and reads everything else (gold pixel data,
# event-level gold, rasters, hulls, overview pmtiles) from S3 at runtime.
# The bucket is env-driven (PROBE_S3_BUCKET, default "maxi") -- see
# packages/probe-core/src/probe_core/data_lake/data_interface.py and ../docs/s3.md.
# Credentials (PROBE_S3_ACCESS_KEY_ID/_SECRET_ACCESS_KEY) and endpoint
# (PROBE_S3_ENDPOINT_URL) come from the stage's values/secrets, not baked in here.
#
# Build via ./build.sh (stages the build context first); see README.md.
#
# Layout: the app (the repo's app/) in /app, run as user `app` (UID 10001,
# HOME /home/app). Everything it writes at runtime goes to /data (below) or /tmp:
# /app and /home/app belong to root, so nothing the app starts (the upload
# parser, polygon_upload.py) can change the code it runs. The stages can
# therefore run the container with a read-only root filesystem.

# Base images are pinned by version and digest; Dependabot (.github/dependabot.yml)
# proposes updates. Keep the uv version in line with setup-uv in the workflows.
FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# uv's own static binary (astral's recommended Docker pattern), installing the
# exact versions of the repo's uv.lock into the system Python.
COPY --from=ghcr.io/astral-sh/uv:0.12.19@sha256:04d046b13e60d6bcec73cbc5e1cad25d680dea90c8573340950a0ac2d1aef424 /uv /usr/local/bin/uv

# libexpat1: required by rasterio's bundled GDAL (not in python-slim)
# apt-get upgrade: Debian's security fixes since the base image was built
# (the image scan in the build workflow fails on a package with a known fix).
# So the OS packages are those of the build day, not only of the digest above.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash --uid 10001 --user-group app

# The repo's pyproject.toml + uv.lock and packages/, staged into project/ like
# context/ below. Everything installed comes from the lockfile, with hashes; dev
# tools are left out. probe-core is built from packages/probe-core and installed
# as a regular package (--no-editable), so /tmp/pgr-atlas can go afterwards.
COPY project/ /tmp/pgr-atlas/
RUN cd /tmp/pgr-atlas \
    && uv export --frozen --no-dev --no-emit-project --no-editable -o requirements.lock.txt \
    && uv pip install --system --no-cache -r requirements.lock.txt \
    && rm -rf /tmp/pgr-atlas

# Writable runtime folders, pod-ephemeral on the stages (their emptyDir mounts
# at these exact paths):
#   /data/cache  probe-core's envelope export cache (PROBE_CACHE_DIR)
#   /data/work   uploads and raster jobs, swept after 7 days (PROBE_WORK_DIR,
#                app/work_dirs.py)
RUN mkdir -p /data/cache /data/work && chown -R app:app /data
# matplotlib keeps its font cache in its config folder, which must be writable.
ENV PROBE_CACHE_DIR=/data/cache \
    PROBE_WORK_DIR=/data/work \
    MPLCONFIGDIR=/tmp/matplotlib

# Code only -- no baked gold/raster data. Staged by build.sh into context/:
# the repo's app/ is the whole context.
# Owned by root and compiled here: `app` can read and run it, not write to it.
COPY context/                     /app
COPY streamlit_config.toml         /home/app/.streamlit/config.toml
RUN python3 -m compileall -q /app

ENV HOME=/home/app
WORKDIR /app

# DuckDB extensions, baked in at build time rather than downloaded on first use.
# probe-core's data_interface runs `INSTALL spatial; LOAD spatial;` on the
# app's very first screen (app.py's startup reads), and ifk_and_raster
# does the same for httpfs -- neither is statically linked into the duckdb wheel (only icu,
# json and parquet are), so DuckDB otherwise fetches ~108MB from
# http://extensions.duckdb.org (plain HTTP, port 80) on EVERY fresh pod.
# That only works where egress is unrestricted. Behind Bedag's network policies
# it fails with "IO Error: Failed to download extension" and the app never
# starts; the message gives no hint that a firewall is the cause.
# Allowing egress to extensions.duckdb.org instead was rejected: it needs port
# 80 to changing CDN addresses and would download again on every pod start.
# Must stay AFTER `ENV HOME`: the runtime looks for extensions under
# $HOME/.duckdb. Installed as root, like the code; then /home/app itself goes
# to root too (useradd made it for `app`).
RUN python3 -c "import duckdb; c = duckdb.connect(); c.execute('INSTALL httpfs'); c.execute('INSTALL spatial')" \
    && chown -R root:root /home/app && chmod -R a+rX /home/app

# Drop root for everything from here on.
USER 10001

# 8501 streamlit (app.py itself, incl. its websocket)
# 8503 derivate_bbox_server.py -- raster bbox-crop server (Raster-Karten view)
# 8505 pmtiles_server.py -- Range-request proxy for the overview PMTiles archive
EXPOSE 8501 8503 8505

# Shown in the app's sidebar footer (app.py _app_version). Set by CI: the
# release tag (v0.3.1) or <branch>-<short sha>; build.sh passes local-<sha>.
# Declared this late so a new version doesn't invalidate the cached layers above.
ARG PGR_ATLAS_VERSION
ENV PGR_ATLAS_VERSION=${PGR_ATLAS_VERSION}

# The tile proxy's /readyz is 200 only while Streamlit, the tile proxy and the
# crop server all answer (run_app.py passes it the other two).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8505/readyz', timeout=4)"

# run_app.py (not a plain `streamlit run app.py`) -- starts pmtiles_server/
# derivate_bbox_server eagerly, before Streamlit accepts any connection, so
# every replica is ready regardless of which pod k8s session affinity ends
# up routing a given request to. See run_app.py's docstring.
CMD ["python", "run_app.py"]
