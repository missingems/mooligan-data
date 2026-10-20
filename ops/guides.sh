#!/bin/bash
# Commander guides for the top commanders of edh/top.json: asks Claude for each guide whose input changed, within a
# budget, adds Commander Spellbook's combos to every guide, checks each one against what the app decodes, and
# uploads the ones that pass to R2 with wrangler.
#
#   export ANTHROPIC_API_KEY=...
#   ops/guides.sh
#
# TOP (100) is how many commanders; BUDGET (12) is the most the run may spend on Claude, in dollars, and the guides
# past it are left for the next run. DIR (scraper/work) keeps state/guides.json, so a guide is asked for once and a
# rerun asks only for what is missing. UPLOAD=0 checks without uploading. WRANGLER_DIR
# (~/Developer/GitHub/playgraph/api) is where wrangler is logged in to the account that owns the bucket.
set -uo pipefail

. "$(dirname "$0")/lib.sh"
load_env
ensure_venv || exit 1

TOP=${TOP:-100}
BUDGET=${BUDGET:-12}
DIR=${DIR:-$REPO/scraper/work}
UPLOAD=${UPLOAD:-1}
WRANGLER_DIR=${WRANGLER_DIR:-$HOME/Developer/GitHub/playgraph/api}

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: export ANTHROPIC_API_KEY first" >&2
  exit 2
fi
mkdir -p "$DIR"
DIR=$(cd "$DIR" && pwd -P)
cd "$REPO/scraper" || exit 1

log "Guides for the top $TOP, at most \$$BUDGET"
python -m mtgmeta guides "$DIR" --top "$TOP" --budget "$BUDGET"
log "Combos from Commander Spellbook"
python -m mtgmeta guide-combos "$DIR" --top "$TOP"
passed=$(python -m mtgmeta guide-check "$DIR" --top "$TOP")
log "$(printf '%s\n' "$passed" | grep -c .) guides pass the check"

if [ "$UPLOAD" != 1 ]; then
  log "UPLOAD=$UPLOAD: nothing uploaded"
  exit 0
fi
uploaded=0
failed=0
for slug in $passed; do
  if (cd "$WRANGLER_DIR" && npx wrangler r2 object put "$R2_BUCKET/edh/commanders/$slug/guide.json" \
    --file "$DIR/edh/commanders/$slug/guide.json" --content-type application/json --cache-control "public, max-age=300" --remote >/dev/null); then
    uploaded=$((uploaded + 1))
  else
    warn "upload of $slug failed"
    failed=$((failed + 1))
  fi
done
log "$uploaded uploaded, $failed failed"
[ "$failed" = 0 ]
