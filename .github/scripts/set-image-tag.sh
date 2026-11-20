#!/usr/bin/env bash
# Sets the app's image tag in a stage's values.yaml: the `tag:` line that
# follows `repository: .../pgr-atlas`. The proxy's image in the same file has
# its own `tag:` and stays as it is. Fails unless exactly one line changed.
#
#   set-image-tag.sh deploy/stages/test/pgr-atlas/values.yaml v0.8.8
set -euo pipefail

file=$1
tag=$2

[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "not a release tag: $tag" >&2; exit 1; }

before=$(mktemp)
cp "$file" "$before"
awk -v tag="$tag" '
  /repository: .*\/pgr-atlas$/ { armed = 1 }
  armed && /^[[:space:]]*tag: "/ { sub(/"[^"]*"/, "\"" tag "\""); armed = 0 }
  { print }
' "$before" > "$file"

changed=$(diff "$before" "$file" | grep -c '^>' || true)
rm -f "$before"
[ "$changed" -eq 1 ] || { echo "$file: expected 1 changed line, got $changed" >&2; exit 1; }
