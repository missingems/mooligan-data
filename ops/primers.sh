#!/bin/bash
# The archetype primers job: Claude writes the primers that are missing or stale, each is checked, and with PUBLISH=1
# they go up to api.mooligan.com. GitHub Actions calls this (.github/workflows/guides.yml), and so can anyone on a
# laptop. The rules for what is due are in scraper/mtgmeta/primers.py; see the README, "Archetype primers".
#
# MODE is what it does:
#   write  write the due primers, within BUDGET dollars (needs ANTHROPIC_API_KEY). With PUBLISH=1 each passing primer
#          is published (needs PRIMERS_ADMIN_TOKEN) and state/primers.json goes up to R2 (needs the R2 keys)
#   plan   list the due primers and why; needs no key
#   check  validate the published primers; needs no key
# FORMATS (the six main ones), COUNT (16 archetypes a format), BUDGET (5 dollars) and MINUTES (no primer is started
# after them; 0, the default, for no limit) narrow it. The drafts land in DIR (scraper/work-primers/primers).
set -uo pipefail

. "$(dirname "$0")/lib.sh"
load_env

MODE=${MODE:-write}
# The workflow passes its inputs through empty, so these fall back when empty too.
: "${FORMATS:=standard,pioneer,modern,legacy,pauper,vintage}"
: "${COUNT:=16}"
: "${BUDGET:=5}"
: "${MINUTES:=0}"
DIR=${DIR:-$REPO/scraper/work-primers}

case $MODE in
  write | plan | check) ;;
  *) echo "ERROR: MODE must be write, plan or check, not '$MODE'" >&2; exit 2 ;;
esac
publishing=0
if [ "$MODE" = write ]; then
  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: MODE=write needs ANTHROPIC_API_KEY (MODE=plan and MODE=check need no key)" >&2
    exit 2
  fi
  if [ "$PUBLISH" = 1 ]; then
    require_credentials_to_publish
    if [ -z "${PRIMERS_ADMIN_TOKEN:-}" ]; then
      echo "ERROR: PUBLISH=1 needs PRIMERS_ADMIN_TOKEN, the API's admin token" >&2
      exit 2
    fi
    publishing=1
  fi
fi

ensure_venv || exit 1

# A fresh start, as on Actions: the drafts of an earlier run must not be mistaken for this one's.
rm -rf "$DIR"
mkdir -p "$DIR/state"
R2=s3://$R2_BUCKET

# A publishing run reads what the primers were written from out of the bucket itself; any other run reads it from
# DATA_URL, as the data. It is fine for the file not to exist yet.
if [ "$publishing" = 1 ]; then
  if ! aws s3 sync "$R2/state" "$DIR/state" --exclude "*" --include "primers.json" --endpoint-url "$R2_ENDPOINT"; then
    echo "ERROR: state/primers.json could not be read from R2, so no primer was written" >&2
    exit 3
  fi
fi

args=(--format "$FORMATS" --count "$COUNT" --budget "$BUDGET" --minutes "$MINUTES")
case $MODE in
  plan) args+=(--plan) ;;
  check) args+=(--check) ;;
  write) if [ "$publishing" = 1 ]; then args+=(--publish); fi ;;
esac

cd "$REPO/scraper" || exit 1
PYTHONUNBUFFERED=1 "$VENV/bin/python" -m mtgmeta primers "$DIR" "${args[@]}"
rc=$?

# Up even when some primers failed: the state of the ones published has to be kept.
if [ "$publishing" = 1 ] && [ -f "$DIR/state/primers.json" ]; then
  if ! aws s3 cp "$DIR/state/primers.json" "$R2/state/primers.json" --endpoint-url "$R2_ENDPOINT" \
    --content-type application/json --cache-control "no-cache" --only-show-errors; then
    echo "ERROR: the upload of state/primers.json to R2 failed" >&2
    exit 4
  fi
fi
if [ "$MODE" = write ] && [ "$publishing" != 1 ]; then
  echo "PUBLISH=0: nothing was published. The drafts are in $DIR/primers"
fi
exit $rc
