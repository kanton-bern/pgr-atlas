#!/usr/bin/env bash
# Keeps one GitHub issue per alert in step with a check's result. Used by
# scan-images.yml after its check step:
#
#   alert-issue.sh <label> <title> <report.md> <outcome>
#
# <outcome> is the check's outcome (success or failure). The issue is found by
# its label, so each alert has its own label and at most one open issue:
#   - failure, no open issue: opens one with the report, assigned to
#     $ALERT_ASSIGNEE. GitHub mails the assignee and the repo's watchers.
#   - failure, open issue: when the report differs from the last one, puts the
#     new report into the issue and comments (one mail). An unchanged report
#     stays silent, so a finding that waits for a release does not mail every
#     run.
#   - success, open issue: closes it with a comment.
# The issue body ends with a hash of its report, which is what "differs" means.
# Each update names where it came from: the workflow run when GITHUB_RUN_ID is
# set, else this host and the time.
# Needs GH_TOKEN with issues: write and GH_REPO or GITHUB_REPOSITORY.
set -euo pipefail
shopt -s inherit_errexit

label=$1
title=$2
report=$3
outcome=$4
case "$outcome" in success | failure) ;; *)
  echo "alert-issue.sh: outcome '$outcome', nothing to do" >&2
  exit 0
  ;;
esac
if [ -n "${GITHUB_RUN_ID:-}" ]; then
  source="[this run](${GITHUB_SERVER_URL:-https://github.com}/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID)"
else
  source="the check on \`$(hostname)\` at $(date -u '+%F %T UTC')"
fi

gh label create "$label" --color B60205 --description "Opened and closed by a check" --force >/dev/null
issue=$(gh issue list --label "$label" --state open --limit 1 --json number --jq '.[0].number // empty')

if [ "$outcome" = success ]; then
  [ -z "$issue" ] && exit 0
  gh issue close "$issue" --comment "Clean again in $source."
  exit 0
fi

[ -s "$report" ] || echo "No report, see $source." >"$report"
hash=$(sha256sum "$report" | cut -c1-16)
body=$(mktemp)
trap 'rm -f "$body"' EXIT
{
  cat "$report"
  echo
  echo "Updated by $source. The check closes this issue when it is clean again."
  echo
  echo "<!-- report-hash: $hash -->"
} >"$body"

if [ -z "$issue" ]; then
  gh issue create --title "$title" --label "$label" --assignee "$ALERT_ASSIGNEE" --body-file "$body"
  exit 0
fi

old=$(gh issue view "$issue" --json body --jq .body | sed -n 's/^<!-- report-hash: \([0-9a-f]*\) -->$/\1/p')
if [ "$old" = "$hash" ]; then
  echo "Issue #$issue already has this report"
  exit 0
fi
gh issue edit "$issue" --body-file "$body"
gh issue comment "$issue" --body "The result changed in $source; the issue now shows the new report."
