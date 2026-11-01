#!/bin/bash
# The archetype primers job: Claude writes the primers that are missing or changed (or old, with their deck moved), each
# is checked, and with PUBLISH=1 they go up to api.mooligan.com. GitHub Actions calls this (.github/workflows/guides.yml),
# and so can anyone on a laptop. The rules for what is due are in scraper/mtgmeta/primers.py; see the README, "Archetype
# primers".
#
# MODE is what it does:
#   write  write the due primers, within BUDGET dollars (needs ANTHROPIC_API_KEY), as one Message Batch at half price:
#          the run waits for it up to MINUTES. With PUBLISH=1 each passing primer is published (needs
#          PRIMERS_ADMIN_TOKEN), and state/primers.json and state/primer-batch.json (a batch still running, which the
#          next run collects) come down from R2 first and go up to it after, from a trap, so a cancelled or timed-out
#          run keeps them too, and both are tried even if the first upload fails (needs the R2 keys)
#   plan   list the due primers and why; needs no key
#   check  validate the published primers; needs no key
# FORMATS (the six main ones), COUNT (16 archetypes a format), BUDGET (5 dollars) and MINUTES (how long the run waits
# for its batch; 0, the default, for 60) narrow it. The drafts land in DIR (scraper/work-primers/primers).
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

# A publishing run reads what the primers were written from, and the batch an earlier run left running, out of the
# bucket itself; any other run reads them from DATA_URL, as the data. It is fine for either file not to exist yet.
if [ "$publishing" = 1 ]; then
  if ! aws s3 sync "$R2/state" "$DIR/state" --exclude "*" --include "primers.json" --include "primer-batch.json" \
    --endpoint-url "$R2_ENDPOINT"; then
    echo "ERROR: state/primers.json and state/primer-batch.json could not be read from R2, so no primer was written" >&2
    exit 3
  fi
fi

args=(--format "$FORMATS" --count "$COUNT" --budget "$BUDGET" --minutes "$MINUTES")
case $MODE in
  plan) args+=(--plan) ;;
  check) args+=(--check) ;;
  write) if [ "$publishing" = 1 ]; then args+=(--publish); fi ;;
esac

# The state goes up from a trap, so a run that is cancelled or stopped by the job's timeout (the batch id would be lost
# otherwise: the next run would send the primers again and pay twice) still keeps it. Both files are tried, even when
# the first upload fails, and the script then exits 4. A batch file left behind in R2 would be collected and counted
# again. The state goes first, so a failed upload of the batch leaves it listed, and the next run finds the primers it
# holds no longer due. The batch file is written even with no batch left, as {"batches": []}: nothing here deletes a file
# in R2, so a deleted one would leave the old one up there to be collected again.
python_pid=
uploading=0
upload_state() {
  local name failed=0
  for name in primers.json primer-batch.json; do
    if [ -f "$DIR/state/$name" ]; then
      if ! aws s3 cp "$DIR/state/$name" "$R2/state/$name" --endpoint-url "$R2_ENDPOINT" \
        --content-type application/json --cache-control "no-cache" --only-show-errors; then
        echo "ERROR: the upload of state/$name to R2 failed" >&2
        failed=1
      fi
    fi
  done
  return $failed
}
finish() {
  local status=$?
  trap - EXIT INT TERM
  if [ -n "$python_pid" ] && kill -0 "$python_pid" 2>/dev/null; then
    kill -TERM "$python_pid" 2>/dev/null
    wait "$python_pid" 2>/dev/null
  fi
  if [ "$uploading" = 1 ] && ! upload_state; then
    status=4
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cd "$REPO/scraper" || exit 1
# In the background, so a signal reaches the trap at once instead of after the run.
if [ "$publishing" = 1 ]; then uploading=1; fi
PYTHONUNBUFFERED=1 "$VENV/bin/python" -m mtgmeta primers "$DIR" "${args[@]}" &
python_pid=$!
wait "$python_pid"
rc=$?
python_pid=

if [ "$MODE" = write ] && [ "$publishing" != 1 ]; then
  echo "PUBLISH=0: nothing was published. The drafts are in $DIR/primers"
fi
exit $rc
