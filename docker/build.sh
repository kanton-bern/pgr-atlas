#!/usr/bin/env bash
# Build the map components, stage the build context from ../app/ (the Streamlit
# app) and build the image.
# Dependencies come from the repo's pyproject.toml + uv.lock, and probe-core from
# packages/ (all staged into project/).
# No data baked in -- everything comes from S3 at runtime, so building needs
# no credentials.
set -euo pipefail
cd "$(dirname "$0")"

APP_DIR="$(cd .. && pwd)/app"
CTX=context

# The map components built from ../frontend/ (into app/<component>/dist/).
# Node is needed here only; the image serves the built files.
echo "── Building the map components (../frontend) ─────────────────────────"
command -v npm >/dev/null || {
  echo "npm not found: install Node (version in frontend/.nvmrc)" >&2
  exit 1
}
(cd ../frontend && npm ci && npm run build)

echo "── Staging build context from ../app ──────────────────────────────────"
rm -rf "$CTX"
cp -r "$APP_DIR" "$CTX"
find "$CTX" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf project && mkdir project && cp ../pyproject.toml ../uv.lock project/
# probe-core, the workspace package the lockfile installs from its own folder
cp -r ../packages project/
find project -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

echo "Context size: $(du -sh "$CTX" | cut -f1)"   # plain -sh: macOS du has no --apparent-size

echo "── Building image ───────────────────────────────────────────────────"
IMAGE="${IMAGE:-pgr-atlas:local}"   # local tag, never shadows a registry tag (CI builds the real ones)
VERSION="local-$(git -C .. rev-parse --short HEAD)"   # sidebar footer, see Dockerfile
docker build -t "$IMAGE" --build-arg PGR_ATLAS_VERSION="$VERSION" .

echo
echo "Done. Image: $IMAGE"
echo "Push with:   docker push $IMAGE   (needs ghcr.io auth first)"
echo "Optional cleanup: rm -rf $CTX"
