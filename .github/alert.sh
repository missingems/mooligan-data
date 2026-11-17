#!/usr/bin/env bash
# Comments on the open "pipeline-alert" issue, or opens one, so the repository's owner is notified. Used by alerts.yml.
set -euo pipefail

message="$1"
label="pipeline-alert"

gh label create "$label" --color B60205 --description "A scheduled job failed or a feed is stale" --force >/dev/null

open=$(gh issue list --label "$label" --state open --limit 1 --json number --jq '.[0].number // empty')
if [ -n "$open" ]; then
  gh issue comment "$open" --body "$message"
else
  gh issue create --label "$label" --title "Pipeline alert" --body "$(printf '%s\n\n@missingems, close this once it is fixed; the next alert opens a new issue.' "$message")"
fi
