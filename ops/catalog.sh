#!/bin/bash
# The whole card catalog job: image feature prints (Vision, so macOS only), pull odds and the price
# catalog, in generators/work/catalog, and uploaded under catalog/ on R2 only with PUBLISH=1.
# GitHub Actions calls this, and so can anyone on a Mac, so what runs in CI is what was tested
# locally. See the README for the variables.
#
# PUBLISH=0 (the default) uploads nothing and needs no keys: the generators read the previous state
# from data.mooligan.com themselves. MTG_LIMIT (read by the indexer) limits the cards for a quick run;
# FULL_REBUILD=1 recomputes every vector.
set -uo pipefail

. "$(dirname "$0")/lib.sh"
load_env
require_credentials_to_publish
# The upload block needs the pinned aws and a python3 on PATH.
if [ "$PUBLISH" = 1 ]; then ensure_venv || exit 1; fi

# Each lifted step is a function whose body is a subshell, so it runs under `set -e` like an Actions
# step (bash -e -o pipefail). Call them as plain statements, never in an `if` or after `||`: bash
# ignores -e inside anything called that way.

step_indexer() (
  set -e
  export OUTPUT_DIR=work/catalog STATE_BASE_URL=https://data.mooligan.com/catalog FULL_REBUILD="${FULL_REBUILD:-0}"
  .build/release/ImageHashIndexer
  cp visualizer.html work/catalog/index.html
)

step_pull_odds() (
  set -e
  export OUTPUT_DIR=work/catalog
  .build/release/PullOdds
)

step_prices() (
  set -e
  export OUTPUT_DIR=work/catalog
  .build/release/Prices
)

# Everything but the metas first, so nothing points at a file not yet uploaded. Not
# `--size-only`: a flat part or the projection changes content without changing size, and
# the phones downloaded parts of patch 6 under a manifest that said 9. The master chunks
# are matched by size, since they only change with a rebase and are 200 MB.
step_upload() (
    set -e
    previous=$(aws s3 cp "$R2/index.json" - --endpoint-url "$R2_ENDPOINT" 2>/dev/null || echo '{}')
    aws s3 sync work/catalog "$R2" --endpoint-url "$R2_ENDPOINT" --size-only --only-show-errors \
      --exclude "*" --include "MTG_Hashes_Master_*.lzfse" --cache-control "public, max-age=3600"
    aws s3 sync work/catalog "$R2" --endpoint-url "$R2_ENDPOINT" --only-show-errors \
      --exclude "MTG_Hashes_Master_*.lzfse" \
      --exclude "index.json" --exclude "manifest.json" --exclude "prices-meta.json" --exclude "pull-odds-meta.json" \
      --cache-control "public, max-age=3600"
    for meta in index.json manifest.json prices-meta.json pull-odds-meta.json; do
      [ -f "work/catalog/$meta" ] && aws s3 cp "work/catalog/$meta" "$R2/$meta" --endpoint-url "$R2_ENDPOINT" \
        --content-type application/json --cache-control "public, max-age=300" --only-show-errors
    done
    cat work/catalog/manifest.json
    # Parts neither this manifest nor the one before it lists: a phone that started
    # downloading before this publish still finds the previous set.
    keep=$(python3 -c "import json,sys; print('\n'.join(json.load(open('work/catalog/index.json'))['parts'] + json.loads(sys.argv[1]).get('parts', [])))" "$previous")
    aws s3 ls "$R2/" --endpoint-url "$R2_ENDPOINT" | awk '{print $4}' | grep -E '^index_.*\.bin$' | while read -r part; do
      echo "$keep" | grep -qx "$part" || aws s3 rm "$R2/$part" --endpoint-url "$R2_ENDPOINT" --only-show-errors
    done
)

cd "$REPO/generators" || exit 1
# Not .build: an incremental build is fine. A work/catalog left from the last run would make the
# sync upload index parts the prune had deleted.
rm -rf work
R2=s3://$R2_BUCKET/catalog
failed=0
published=0
indexer_ok=0

swift build -c release
rc=$?
if [ "$rc" -ne 0 ]; then
  echo "ERROR: the build failed" >&2
  exit 1
fi

step_indexer
rc=$?
if [ "$rc" -eq 0 ]; then
  indexer_ok=1
else
  failed=$(( failed + 1 ))
  echo "ERROR: the image feature prints failed (exit $rc)" >&2
fi

if [ "$indexer_ok" = 1 ]; then
  step_pull_odds
  rc=$?
  if [ "$rc" -ne 0 ]; then
    failed=$(( failed + 1 ))
    echo "ERROR: the pull odds failed (exit $rc)" >&2
  fi
fi

# Runs after the build whatever happened to the two above: they share nothing but MTGJSON. The
# workflow marked this step continue-on-error, so a failure left the job green, although its own
# comment says a failure of either "still fails the job". Here it counts, like the other two.
step_prices
rc=$?
if [ "$rc" -ne 0 ]; then
  failed=$(( failed + 1 ))
  echo "ERROR: the price catalog failed (exit $rc)" >&2
fi

if [ "$PUBLISH" = 1 ] && [ -f work/catalog/index.json ]; then
  step_upload
  rc=$?
  if [ "$rc" -eq 0 ]; then
    published=1
  else
    failed=$(( failed + 1 ))
    echo "ERROR: the upload to R2 failed (exit $rc)" >&2
  fi
elif [ "$PUBLISH" != 1 ]; then
  echo
  echo "PUBLISH=0: nothing was uploaded. The output is in $REPO/generators/work/catalog:"
  if [ -d work/catalog ]; then
    ls -l work/catalog
    echo "  $(find work/catalog -type f | wc -l | tr -d ' ') files"
  else
    echo "  (nothing was written)"
  fi
else
  echo "No work/catalog/index.json, so nothing was uploaded"
fi

if [ "$failed" -ne 0 ]; then
  echo "$failed step(s) failed. See the log above." >&2
  exit 1
fi
exit 0
