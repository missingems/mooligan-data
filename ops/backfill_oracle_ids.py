#!/usr/bin/env python3
"""Queue published decks that have entries without an oracle_id: `backfill_oracle_ids.py DIR`.

A one-off for decks published before the scraper recorded them in state/unresolved-deck-ids.json.
It reads every id in DIR/state/deck-ids.json, downloads decks/{id}.json from DATA_URL (default
https://data.mooligan.com) and adds each deck with an unnamed entry to DIR/state/unresolved-deck-ids.json,
leaving the tries of ids already there as they are. The next scrape names them. A deck that cannot be
downloaded is counted and skipped.

DIR must be a work dir freshly populated from the live state (for example `ops/fetch_live.py DIR`), so
that the merge starts from the tries already recorded. scrape.sh syncs state/ down from R2 and would
overwrite a file that only exists locally, so upload the result before the next scheduled run:

    aws s3 cp DIR/state/unresolved-deck-ids.json "s3://$R2_BUCKET/state/unresolved-deck-ids.json" \\
      --endpoint-url "$R2_ENDPOINT" --content-type application/json --cache-control "no-cache"
"""
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scraper"))

from mtgmeta.store import _unresolved_names  # noqa: E402

USER_AGENT = "mtg-meta-pipeline/1.0 (+https://data.mooligan.com)"
WORKERS = 16


def names_for(base, deck_id):
    """The names without an oracle id in the published deck, or None if it could not be read."""
    request = urllib.request.Request(f"{base}/decks/{deck_id}.json", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return _unresolved_names(json.loads(response.read()))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main():
    if len(sys.argv) != 2:
        print("usage: backfill_oracle_ids.py DIR", file=sys.stderr)
        return 2
    directory = sys.argv[1]
    base = os.environ.get("DATA_URL", "https://data.mooligan.com").rstrip("/")

    with open(os.path.join(directory, "state", "deck-ids.json")) as handle:
        deck_ids = sorted(json.load(handle))
    unresolved_path = os.path.join(directory, "state", "unresolved-deck-ids.json")
    unresolved = {}
    if os.path.exists(unresolved_path):
        with open(unresolved_path) as handle:
            unresolved = json.load(handle)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda deck_id: names_for(base, deck_id), deck_ids))

    failed = queued = 0
    for deck_id, names in zip(deck_ids, results):
        if names is None:
            failed += 1
        elif names and deck_id not in unresolved:
            unresolved[deck_id] = {"attempts": 0, "names": names}
            queued += 1

    os.makedirs(os.path.dirname(unresolved_path), exist_ok=True)
    with open(unresolved_path + ".part", "wb") as handle:
        handle.write(json.dumps(unresolved, sort_keys=True).encode())
    os.replace(unresolved_path + ".part", unresolved_path)
    print(f"Checked {len(deck_ids)} decks, {failed} failed to download, {queued} queued in {unresolved_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
