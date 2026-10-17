#!/usr/bin/env python3
"""Download the live snapshots and state into DIR with plain GETs, no credentials: `fetch_live.py DIR`.

This is the read-only stand-in for syncing snapshots/ and state/ from the bucket, for a run that
will not publish. The base URL is DATA_URL (default https://data.mooligan.com), the same variable
the scraper reads. index.json is read to learn the formats but is not saved: its presence in DIR
means a finished run, and the scraper writes its own.

A 404 is skipped with a note (a file the live run never wrote). Any other failure ends the run with
a non-zero exit, as a failed sync does.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
ATTEMPTS = 3
WORKERS = 8

STATE_FILES = [
    "state/deck-ids.json",
    "state/duplicate-event-ids.json",
    "state/empty-event-ids.json",
    "state/missing-deck-ids.json",
    "state/unresolved-deck-ids.json",
    "state/edhrec.json",
    "state/edhrec-commanders.json",
    "state/card-hashes.json",
    "state/explore-manifest.json",
    "state/printing-ids.json.gz",
    "state/printing-first-seen.json.gz",
    "state/today-commanders.json",
    "state/localized.json.gz",
    "state/rules-keywords.json",
]


def get(base, path):
    """The bytes at base/path, or None for a 404. Three tries for anything else."""
    request = urllib.request.Request(f"{base}/{path}", headers={"User-Agent": USER_AGENT})
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            failure = error
        except (urllib.error.URLError, OSError) as error:
            failure = error
        print(f"warning: {path} failed (attempt {attempt} of {ATTEMPTS}): {failure}", file=sys.stderr, flush=True)
        if attempt < ATTEMPTS:
            time.sleep(5 * attempt)
    raise RuntimeError(f"{path} failed after {ATTEMPTS} attempts: {failure}")


def save(base, directory, path):
    data = get(base, path)
    if data is None:
        print(f"skipped {path} (404)", flush=True)
        return False
    target = os.path.join(directory, path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target + ".part", "wb") as handle:
        handle.write(data)
    os.replace(target + ".part", target)
    return True


def main():
    if len(sys.argv) != 2:
        print("usage: fetch_live.py DIR", file=sys.stderr)
        return 2
    directory = sys.argv[1]
    base = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")

    index = get(base, "index.json")
    if index is None:
        raise RuntimeError(f"{base}/index.json is a 404")
    formats = sorted(json.loads(index)["formats"])
    for name in formats:
        # The names become file paths.
        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise RuntimeError(f"unexpected format name {name!r} in index.json")

    paths = [f"snapshots/{name}.json" for name in formats] + STATE_FILES + [f"state/deck-cards/{name}.json" for name in formats]
    paths += [f"state/snapshots/{name}.json" for name in formats]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        saved = sum(pool.map(lambda path: save(base, directory, path), paths))
    print(f"Downloaded {saved} of {len(paths)} files from {base} into {directory}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - one line and a non-zero exit is all the caller needs
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
