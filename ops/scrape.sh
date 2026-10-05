#!/bin/bash
# The whole scrape job: get the previous snapshots and state, scrape what is new, and upload it (only
# with PUBLISH=1). GitHub Actions calls this, and so can anyone on a laptop, so what runs in CI is
# what was tested locally. See the README for the variables.
#
# PUBLISH=0 (the default) uploads nothing. The previous snapshots and state come from SYNC:
#   r2     the bucket, with the R2 keys (what publishing needs)
#   https  the live files at DATA_URL (default https://data.mooligan.com), with no keys
#   none   nothing: the run starts from an empty work/
#   auto   r2 when the keys are set, else https
# QUICK=1 presets a small, fast run for development. Every preset can be set by hand.
set -uo pipefail

. "$(dirname "$0")/lib.sh"
load_env

SYNC=${SYNC:-auto}
case $SYNC in
  auto) if have_credentials; then SYNC=r2; else SYNC=https; fi ;;
  r2 | https | none) ;;
  *) echo "ERROR: SYNC must be auto, r2, https or none, not '$SYNC'" >&2; exit 2 ;;
esac
if [ "$SYNC" = r2 ] && ! have_credentials; then
  echo "ERROR: SYNC=r2 needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY" >&2
  exit 2
fi
require_credentials_to_publish
if [ "$PUBLISH" = 1 ] && [ "$SYNC" != r2 ]; then
  echo "ERROR: PUBLISH=1 must start from the bucket itself, so SYNC has to be r2 (or auto with the R2 keys set), not $SYNC" >&2
  exit 2
fi
if [ "$PUBLISH" = 1 ] && [ "${QUICK:-0}" = 1 ]; then
  echo "ERROR: QUICK=1 scrapes a fraction of the data and must not be published" >&2
  exit 2
fi

ensure_venv || exit 1

# Each lifted step is a function whose body is a subshell, so it runs under `set -e` like an Actions
# step (bash -e -o pipefail). Call them as plain statements, never in an `if` or after `||`: bash
# ignores -e inside anything called that way.

# sync succeeds on an empty bucket, so the first run starts from nothing.
step_download() (
    set -e
    sync() {
      for attempt in 1 2 3; do
        aws s3 sync "$1" "$2" --endpoint-url "$R2_ENDPOINT" && return 0
        echo "::warning::sync of $1 failed (attempt $attempt of 3)"
        sleep 15
      done
      return 1
    }
    sync "$R2/snapshots" work/snapshots
    sync "$R2/state" work/state
)

# finish() writes index.json last, so its presence means the run got as far as publishing.
step_upload() (
    set -e
    cp() { aws s3 cp "$@" --endpoint-url "$R2_ENDPOINT" --content-type application/json --only-show-errors; }
    # Decks first and the index last, so nothing published points at a file not yet uploaded.
    if [ -d work/decks ]; then
      cp work/decks "$R2/decks" --recursive --cache-control "public, max-age=31536000, immutable"
    fi
    if [ -d work/cards ]; then
      cp work/cards "$R2/cards" --recursive --cache-control "public, max-age=300"
    fi
    if [ -d work/edh ]; then
      cp work/edh "$R2/edh" --recursive --cache-control "public, max-age=300"
    fi
    if [ -d work/locator ]; then
      cp work/locator "$R2/locator" --recursive --cache-control "public, max-age=300"
    fi
    if [ -d work/premier ]; then
      cp work/premier "$R2/premier" --recursive --cache-control "public, max-age=300"
    fi
    # Written from the snapshots with the same max-age, and uploaded before them and explore.json,
    # which link to them. Like the other prefixes these are only overwritten, never pruned.
    if [ -d work/archetypes ]; then
      cp work/archetypes "$R2/archetypes" --recursive --cache-control "public, max-age=300"
    fi
    if [ -d work/events ]; then
      cp work/events "$R2/events" --recursive --cache-control "public, max-age=300"
    fi
    # Built from the same snapshots and the stored decklists, with the same max-age and the same rule: only overwritten.
    if [ -d work/popular-cards ]; then
      cp work/popular-cards "$R2/popular-cards" --recursive --cache-control "public, max-age=300"
    fi
    if [ -d work/breakouts ]; then
      cp work/breakouts "$R2/breakouts" --recursive --cache-control "public, max-age=300"
    fi
    # From the catalog's price history and Scryfall's printings, with nothing pointing at them.
    if [ -d work/movers ]; then
      cp work/movers "$R2/movers" --recursive --cache-control "public, max-age=300"
    fi
    # Composed from the breakouts and movers above and the EDHREC commander pages (the uprising commander's counts
    # are carried over in state/today-commanders.json, which goes up with the state below) for Explore's Today widgets.
    if [ -f work/today.json ]; then
      cp work/today.json "$R2/today.json" --cache-control "public, max-age=300"
    fi
    cp work/snapshots "$R2/snapshots" --recursive --cache-control "public, max-age=300"
    # Built from the snapshots above, so it goes up after them.
    if [ -f work/explore.json ]; then
      cp work/explore.json "$R2/explore.json" --cache-control "public, max-age=300"
    fi
    cp work/state "$R2/state" --recursive --cache-control "no-cache"
    # Lists the Explore files above by hash, so it goes up after them and the state it is carried over from.
    if [ -f work/explore-manifest.json ]; then
      cp work/explore-manifest.json "$R2/explore-manifest.json" --cache-control "public, max-age=60"
    fi
    cp work/index.json "$R2/index.json" --cache-control "public, max-age=60"
    echo "Published: $(ls work/decks 2>/dev/null | wc -l) new decks, $(ls work/cards 2>/dev/null | wc -l) card pages, $(ls work/archetypes 2>/dev/null | wc -l) archetype pages, $(ls work/events 2>/dev/null | wc -l) event pages"
    cat work/index.json
)

cd "$REPO/scraper" || exit 1
# Actions starts from an empty checkout. A work/ left from the last run would upload yesterday's
# decks and cards again.
rm -rf work
mkdir -p work
R2=s3://$R2_BUCKET

case $SYNC in
  r2)
    step_download
    rc=$?
    ;;
  https)
    log "Downloading the live snapshots and state from ${DATA_URL:-https://data.mooligan.com}"
    "$VENV/bin/python" "$REPO/ops/fetch_live.py" work
    rc=$?
    ;;
  none)
    warn "SYNC=none: starting from an empty work/, so this run reads a month of history from MTGGoldfish"
    rc=0
    ;;
esac
if [ "$rc" -ne 0 ]; then
  # Like the workflow, the later steps do not run. Nothing is uploaded: work/index.json does not exist.
  echo "ERROR: getting the previous snapshots and state failed, so the scrape did not run" >&2
  exit 3
fi

# A small, fast run: one format, a few decks, no EDHREC, locator, premier schedule or movers.
if [ "${QUICK:-0}" = 1 ]; then
  : "${FORMATS:=modern}"
  : "${MAX_NEW_DECKS:=20}"
  : "${MAX_NEW_EVENTS=10}"
  : "${MAX_SEARCH_PAGES=2}"
  : "${EDHREC_CARDS_PER_RUN=0}"
  : "${EDHREC_COMMANDERS_PER_RUN=0}"
  : "${LOCATOR_PLACES=}"
  : "${PREMIER_SCHEDULE=0}"
  : "${MOVERS=0}"
  export MAX_NEW_EVENTS MAX_SEARCH_PAGES PREMIER_SCHEDULE MOVERS
fi

# The defaults are the workflow's. FORMATS and MAX_NEW_DECKS also fall back when empty, because the
# workflow passes its inputs through empty; the rest only when unset, so LOCATOR_PLACES= switches the
# locator off.
: "${FORMATS:=modern,standard,pioneer,legacy,pauper,vintage,premodern,penny_dreadful,duel_commander}"
: "${MAX_NEW_DECKS:=1500}"
: "${META_DAYS=30,14,7}"
: "${REQUEST_DELAY=1}"
: "${CONCURRENCY=6}"
# EDHREC is read with their permission: a slice of the cards each run.
: "${EDHREC_CARDS_PER_RUN=1600}"
: "${EDHREC_COMMANDERS_PER_RUN=300}"
# Upcoming events near these places, from Wizards' locator; semicolon-separated.
: "${LOCATOR_PLACES=Singapore}"
: "${LOCATOR_DISTANCE_MILES=15}"
: "${LOCATOR_DAYS=14}"
: "${EDHREC_DELAY=0.4}"
# The scraper defaults to a headless browser on macOS, which MTGGoldfish's bot check does not let
# through. UC mode runs headed (on Linux, SeleniumBase starts Xvfb itself).
: "${HEADLESS=0}"
export FORMATS MAX_NEW_DECKS META_DAYS REQUEST_DELAY CONCURRENCY EDHREC_CARDS_PER_RUN EDHREC_COMMANDERS_PER_RUN \
  LOCATOR_PLACES LOCATOR_DISTANCE_MILES LOCATOR_DAYS EDHREC_DELAY HEADLESS

# continue-on-error: whatever the scrape collected is still published.
PYTHONUNBUFFERED=1 "$VENV/bin/python" -m mtgmeta work
scrape_rc=$?

published=0
if [ "$PUBLISH" = 1 ] && [ -f work/index.json ]; then
  step_upload
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "ERROR: the upload to R2 failed" >&2
    exit 4
  fi
  published=1
elif [ "$PUBLISH" != 1 ]; then
  echo
  echo "PUBLISH=0: nothing was uploaded. The output is in $REPO/scraper/work:"
  for dir in decks cards edh locator premier archetypes events popular-cards breakouts movers snapshots state; do
    if [ -d "work/$dir" ]; then echo "  $dir/: $(find "work/$dir" -type f | wc -l | tr -d ' ') files"; fi
  done
  for file in index.json explore.json today.json explore-manifest.json; do
    if [ -f "work/$file" ]; then echo "  $file"; fi
  done
  if [ ! -f work/index.json ]; then echo "  (no index.json: the run did not finish)"; fi
else
  echo "No work/index.json, so nothing was uploaded"
fi

if [ "$scrape_rc" -ne 0 ]; then
  if [ "$published" = 1 ]; then
    echo "The scrape logged errors; what it did collect was published. See the log above."
  else
    echo "The scrape logged errors. See the log above."
  fi
  exit 1
fi
exit 0
