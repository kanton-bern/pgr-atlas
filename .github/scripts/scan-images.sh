#!/usr/bin/env bash
# Scans images with Trivy and writes a Markdown report. Used by
# scan-images.yml, on the output of running-images.sh:
#
#   scan-images.sh images.tsv     # lines "<image><TAB><stages>"
#
# Same Trivy as the build workflows (pinned image, same flags, .trivyignore of
# the current directory), with JSON output so the report can list findings.
# The report goes to $SCAN_REPORT (scan-images.yml then copies it into the job
# summary and the alert issue), else to $GITHUB_STEP_SUMMARY, else to stdout.
# TRIVY_CACHE_DIR (optional) keeps Trivy's per-layer results between runs;
# the vulnerability DB is downloaded fresh each run (it changes every 6 h).
# Exits 1 when any image has a finding or could not be scanned.
set -euo pipefail
shopt -s inherit_errexit

trivy=ghcr.io/aquasecurity/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa
list=$1
report=${SCAN_REPORT:-${GITHUB_STEP_SUMMARY:-/dev/stdout}}
[ -f .trivyignore ] || { echo "scan-images.sh: no .trivyignore here" >&2; exit 1; }
[ -s "$list" ] || { echo "scan-images.sh: $list lists no images" >&2; exit 1; }

work=$(mktemp -d)
# One vulnerability DB for all images, downloaded by the first scan only.
db="$work/db"
# Results per image layer (~1 MB): with them an unchanged image scans in a
# second instead of a minute, as its layers are not downloaded again.
layers="${TRIVY_CACHE_DIR:-$work/cache}/fanal"
mkdir -p "$db" "$layers"

# Trivy's JSON on stdout, its log on stderr (the job log). Runs as the
# calling user, so the cache it writes can be read back and saved.
scan() {
  docker run --rm --user "$(id -u):$(id -g)" \
    -v "$db:/trivy/db" \
    -v "$layers:/trivy/fanal" \
    -v "$PWD/.trivyignore:/.trivyignore:ro" \
    "$trivy" \
    image --cache-dir /trivy --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
    --ignorefile /.trivyignore --image-src remote --format json "$1"
}

# A Markdown row per finding, CRITICAL first.
finding_rows() {
  jq -r '
    [.Results[]?
      | (if .Class == "os-pkgs" then "OS (\(.Type))" else .Target end) as $where
      | .Vulnerabilities[]? | . + {Where: $where}]
    | sort_by(.Severity != "CRITICAL", .VulnerabilityID)
    | .[]
    | "| \(.Severity) | \(.VulnerabilityID) | \(.PkgName) | \(.InstalledVersion)"
      + " | \(.FixedVersion) | \(.Where) |"
  ' "$1"
}

failed=0
overview="$work/overview.md"
details="$work/details.md"
: >"$overview"
: >"$details"
n=0
while IFS=$'\t' read -r image stages; do
  n=$((n + 1))
  json="$work/$n.json"
  if ! scan "$image" >"$json"; then
    echo "| \`$image\` | $stages | scan failed, see the job log |" >>"$overview"
    failed=1
    continue
  fi
  count=$(jq '[.Results[]?.Vulnerabilities[]?] | length' "$json")
  echo "| \`$image\` | $stages | $count |" >>"$overview"
  echo "$image ($stages): $count findings"
  [ "$count" -eq 0 ] && continue
  failed=1
  {
    echo
    echo "### \`$image\`"
    echo
    echo "| Severity | CVE | Package | Installed | Fixed in | Where |"
    echo "|---|---|---|---|---|---|"
    finding_rows "$json"
  } >>"$details"
done <"$list"

{
  echo "## Trivy scan of the running images"
  echo
  echo "Fixable HIGH and CRITICAL findings, minus \`.trivyignore\`."
  echo "Fix one with a new release of that image, or accept it in \`.trivyignore\`."
  echo
  echo "| Image | Runs on | Findings |"
  echo "|---|---|---|"
  cat "$overview" "$details"
} >>"$report"

exit "$failed"
