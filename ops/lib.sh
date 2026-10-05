#!/bin/bash
# Shared helpers for ops/scrape.sh and ops/catalog.sh. Source it, do not run it.
#
# The two scripts are the whole job: GitHub Actions calls them, and so can anyone on a laptop, so a
# change tested locally is the change that runs in CI.
#
# Everything here has to run on macOS's bash 3.2 and on Linux's bash 5, so no associative arrays,
# mapfile, ${x,,}, |& or wait -n. The callers use `set -uo pipefail`; nothing here relies on -e.

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
export REPO

# mise lives in ~/.local/bin, Homebrew in /opt/homebrew/bin; a minimal PATH may lack both.
for _dir in "${HOME:-/nonexistent}/.local/bin" /opt/homebrew/bin /usr/local/bin; do
  case ":$PATH:" in
    *":$_dir:"*) ;;
    *) PATH="$PATH:$_dir" ;;
  esac
done
unset _dir
export PATH

OS=$(uname -s)

log() { printf '%s %s\n' "$(date '+%H:%M:%S')" "$*"; }
warn() { log "WARNING: $*"; }

# The AWS CLI is called as plain `aws` by the blocks lifted from the workflows. AWS_CLI lets a test
# point it elsewhere; `command` skips this function so it cannot call itself.
aws() { command "${AWS_CLI:-aws}" "$@"; }

file_mode() {
  if [ "$OS" = Darwin ]; then stat -f %Lp "$1"; else stat -c %a "$1"; fi
}

# True when the three R2 values are all set. They are only needed to read the bucket directly or to publish.
have_credentials() {
  [ -n "${R2_ACCOUNT_ID:-}" ] && [ -n "${R2_ACCESS_KEY_ID:-}" ] && [ -n "${R2_SECRET_ACCESS_KEY:-}" ]
}

derive_defaults() {
  : "${R2_BUCKET:=mtg-meta-data}"
  # Only an exact 1 uploads, so a run never writes to R2 by accident.
  : "${PUBLISH=0}"
  VENV=${VENV:-$REPO/scraper/.venv}
  export R2_BUCKET PUBLISH VENV
  # The AWS CLI reads these. With the R2 keys set they replace whatever AWS credentials a laptop's
  # shell carries (a personal key, a session token, a profile), which R2 would refuse.
  if have_credentials; then
    export AWS_ACCESS_KEY_ID=$R2_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY=$R2_SECRET_ACCESS_KEY AWS_DEFAULT_REGION=auto
    unset AWS_SESSION_TOKEN AWS_PROFILE
  fi
  if [ -z "${R2_ENDPOINT:-}" ] && [ -n "${R2_ACCOUNT_ID:-}" ]; then export R2_ENDPOINT=https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com; fi
}

# Reads ~/.config/mooligan-data/env (or $MOOLIGAN_DATA_ENV) into the environment, if it exists. A
# variable that is already set, even to empty, is left alone, so the caller's environment (a
# workflow, a one-off `PUBLISH=1 ops/scrape.sh`) beats the file. The file is parsed, never sourced.
load_env() {
  MOOLIGAN_DATA_ENV=${MOOLIGAN_DATA_ENV:-${HOME:-}/.config/mooligan-data/env}
  if [ -f "$MOOLIGAN_DATA_ENV" ]; then
    local mode line key val first last
    local re='^(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$'
    mode=$(file_mode "$MOOLIGAN_DATA_ENV" 2>/dev/null || echo '?')
    if [ "$mode" != 600 ]; then
      warn "$MOOLIGAN_DATA_ENV has mode $mode; it holds secrets, so run: chmod 600 $MOOLIGAN_DATA_ENV"
    fi
    while IFS= read -r line || [ -n "$line" ]; do
      line=${line%$'\r'}
      line=${line#"${line%%[![:space:]]*}"}
      line=${line%"${line##*[![:space:]]}"}
      case $line in '' | '#'*) continue ;; esac
      [[ $line =~ $re ]] || continue
      key=${BASH_REMATCH[2]}
      val=${BASH_REMATCH[3]}
      if [ "${#val}" -ge 2 ]; then
        first=${val:0:1}
        last=${val:${#val}-1}
        if { [ "$first" = '"' ] || [ "$first" = "'" ]; } && [ "$first" = "$last" ]; then
          val=${val:1:${#val}-2}
        fi
      fi
      # The key matched the pattern above, so the eval cannot run anything else.
      if eval "[ -z \"\${$key+x}\" ]"; then export "$key=$val"; fi
    done < "$MOOLIGAN_DATA_ENV"
  fi
  derive_defaults
}

# Publishing needs the keys, and the run should say so before it does any work.
require_credentials_to_publish() {
  if [ "$PUBLISH" = 1 ] && ! have_credentials; then
    echo "ERROR: PUBLISH=1 needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY, set in the environment or in $MOOLIGAN_DATA_ENV" >&2
    exit 2
  fi
}

# Echoes an interpreter for creating the venv.
pick_python() {
  if [ -n "${PYTHON:-}" ]; then printf '%s\n' "$PYTHON"; return 0; fi
  local mise="" dir=""
  if command -v mise >/dev/null 2>&1; then
    mise=$(command -v mise)
  elif [ -x "${HOME:-}/.local/bin/mise" ]; then
    mise=$HOME/.local/bin/mise
  fi
  if [ -n "$mise" ]; then
    dir=$("$mise" where python@3.12 2>/dev/null) || dir=""
    if [ -n "$dir" ] && [ -x "$dir/bin/python3.12" ]; then printf '%s\n' "$dir/bin/python3.12"; return 0; fi
  fi
  if command -v python3.12 >/dev/null 2>&1; then command -v python3.12; return 0; fi
  if command -v python3 >/dev/null 2>&1; then command -v python3; return 0; fi
  return 1
}

# The venv's interpreter lives in a versioned mise directory, so an upgrade or prune breaks it; it is
# rebuilt when it no longer runs. Requirements are installed only when the two files changed. The
# venv's bin goes first on PATH, so the lifted blocks' `aws` and `python3` are the pinned ones.
ensure_venv() {
  local py hash marker
  if ! "$VENV/bin/python" -c pass >/dev/null 2>&1; then
    py=$(pick_python) || { echo "ERROR: no Python found; install one with: mise install python@3.12" >&2; return 1; }
    log "Creating the venv at $VENV with $py"
    rm -rf "${VENV:?}"
    "$py" -m venv "$VENV" || return 1
  fi
  hash=$("$VENV/bin/python" -c 'import hashlib, sys
digest = hashlib.sha256()
for path in sys.argv[1:]:
    digest.update(open(path, "rb").read())
print(digest.hexdigest())' "$REPO/scraper/requirements.txt" "$REPO/ops/requirements.txt") || return 1
  marker=$VENV/.mooligan-requirements.sha256
  if [ "$(cat "$marker" 2>/dev/null)" != "$hash" ]; then
    log "Installing the requirements into $VENV"
    "$VENV/bin/python" -m pip install --retries 10 -q --upgrade pip || return 1
    "$VENV/bin/python" -m pip install --retries 10 -q -r "$REPO/scraper/requirements.txt" -r "$REPO/ops/requirements.txt" || return 1
    printf '%s\n' "$hash" > "$marker"
  fi
  PATH="$VENV/bin:$PATH"
  export PATH
  log "python: $("$VENV/bin/python" --version 2>&1)"
  log "aws: $("$VENV/bin/aws" --version 2>&1 | head -n 1)"
}
