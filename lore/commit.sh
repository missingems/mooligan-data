#!/usr/bin/env bash
# Commits lore/data with the message given and pushes, rebasing over anything pushed meanwhile.
set -u
git add data
git diff --cached --quiet && exit 0
git commit -q -m "$1"
for attempt in 1 2 3 4; do
  git pull -q --rebase origin "$GITHUB_REF_NAME" && git push -q origin "HEAD:$GITHUB_REF_NAME" && exit 0
  sleep $((attempt * 5))
done
exit 1
