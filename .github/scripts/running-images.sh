#!/usr/bin/env bash
# Lists the images the stages run, as Git says: one line per distinct image,
# "<ghcr.io image>:<tag><TAB><stages that run it>". Used by scan-images.yml.
#
#   running-images.sh [deploy/stages]
#
# Reads, per stage (test, prod):
#   pgr-atlas/values.yaml        image of the app and proxy containers
#   s3-toolbox/deployment.yaml   image of the toolbox container
# The stages pull through Bedag's mirror artifacts.bedag.cloud/ghcr/<path>,
# which serves the public ghcr.io/<path>; this prints the ghcr.io name.
# Fails if any of the six images is missing, empty or not on that mirror.
# Needs mikefarah yq v4 (preinstalled on GitHub's ubuntu runners).
set -euo pipefail
shopt -s inherit_errexit  # a failure inside "$(...)" stops the script too

root=${1:-deploy/stages}
mirror=artifacts.bedag.cloud/ghcr/
containers=.components.app.controller.containers
toolbox='select(.kind == "Deployment") | .spec.template.spec.containers[]
  | select(.name == "toolbox") | .image'

fail() { echo "running-images.sh: $*" >&2; exit 1; }

# Prints "<repository>:<tag>" of one container in a stage's values.yaml.
chart_image() {
  local file=$1 container=$2 repo tag
  repo=$(yq "${containers}.${container}.image.repository" "$file")
  tag=$(yq "${containers}.${container}.image.tag" "$file")
  [ -n "$repo" ] && [ "$repo" != null ] || fail "$file: no image.repository for $container"
  [ -n "$tag" ] && [ "$tag" != null ] || fail "$file: no image.tag for $container"
  echo "${repo}:${tag}"
}

# Turns a mirror reference into its ghcr.io one; fails for anything else.
to_ghcr() {
  local ref=$1 where=$2
  [[ "$ref" == "$mirror"*:* ]] || fail "$where: $ref is not <image>:<tag> on $mirror"
  echo "ghcr.io/${ref#"$mirror"}"
}

list() {
  local stage values deployment ref image
  for stage in test prod; do
    values="$root/$stage/pgr-atlas/values.yaml"
    deployment="$root/$stage/s3-toolbox/deployment.yaml"
    [ -f "$values" ] || fail "$values not found"
    [ -f "$deployment" ] || fail "$deployment not found"
    for container in app proxy; do
      ref=$(chart_image "$values" "$container")
      image=$(to_ghcr "$ref" "$values")
      printf '%s\t%s\n' "$image" "$stage"
    done
    ref=$(yq "$toolbox" "$deployment")
    [ -n "$ref" ] && [ "$(wc -l <<<"$ref")" -eq 1 ] \
      || fail "$deployment: expected one toolbox image, got '${ref}'"
    image=$(to_ghcr "$ref" "$deployment")
    printf '%s\t%s\n' "$image" "$stage"
  done
}

lines=$(list)
# One line per image, its stages joined: "…:v0.1.0<TAB>test, prod".
awk -F'\t' '
  !($1 in stages) { order[++n] = $1; stages[$1] = $2; next }
  { stages[$1] = stages[$1] ", " $2 }
  END { for (i = 1; i <= n; i++) printf "%s\t%s\n", order[i], stages[order[i]] }
' <<<"$lines"
