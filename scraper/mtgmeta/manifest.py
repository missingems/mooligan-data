"""explore-manifest.json: the SHA-256 of each Explore file, so an app can see in one request which ones changed.

Lists explore.json, previews.json, today.json, popular-cards/{format}.json and breakouts/{format}.json, and nothing else (the app
reads the movers through today.json). A run does not rewrite every one of them, and the files it leaves alone are
not in the work directory, so the manifest of the run before is kept in `state/` and its entries carry over.
Written last, after every file it lists. See docs/data-format.md.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

SCHEMA = 1
PATH = "explore-manifest.json"
STATE_PATH = "state/explore-manifest.json"

# The Explore files: three single files, and the folders of one file per format.
FILES = ("explore.json", "previews.json", "today.json")
FOLDERS = ("popular-cards", "breakouts")
SHA256 = re.compile(r"[0-9a-f]{64}")


def is_explore_path(path: str) -> bool:
    """Whether `path` is one of the Explore files, as the manifest names it."""
    if path in FILES:
        return True
    folder, _, name = path.partition("/")
    return folder in FOLDERS and name.endswith(".json") and len(name) > len(".json") and "/" not in name


def explore_paths(directory: Path) -> List[str]:
    """The Explore files in a work directory, sorted."""
    found = [name for name in FILES if (directory / name).is_file()]
    for folder in FOLDERS:
        found += [f"{folder}/{path.name}" for path in (directory / folder).glob("*.json") if path.is_file()]
    return sorted(found)


def read_previous(directory: Path) -> Dict[str, dict]:
    """The entries of the manifest the run before kept in `state/`: only Explore files, only well-formed hashes.

    A missing, unreadable or corrupt file gives no entries, so the manifest then lists what this run wrote.
    """
    try:
        files = json.loads((directory / STATE_PATH).read_text(encoding="utf-8"))["files"]
        return {path: {"sha256": entry["sha256"]} for path, entry in files.items() if is_explore_path(path) and _has_hash(entry)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _has_hash(entry: object) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("sha256"), str) and bool(SHA256.fullmatch(entry["sha256"]))


def build_manifest(directory: Path, now: datetime, previous_files: Dict[str, dict]) -> dict:
    """The file: `previous_files` with an entry, from the bytes on disk, for every Explore file in `directory`."""
    files = dict(previous_files)
    for path in explore_paths(directory):
        files[path] = {"sha256": hashlib.sha256((directory / path).read_bytes()).hexdigest()}
    return {
        "schema": SCHEMA,
        "generated_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": dict(sorted(files.items())),
    }


def write_manifest(directory: Path, now: datetime) -> List[str]:
    """Writes explore-manifest.json and the copy in `state/` for the next run, and returns the path published.

    Writes nothing, and returns no path, when there is no Explore file to list.
    """
    document = build_manifest(directory, now, read_previous(directory))
    if not document["files"]:
        return []
    body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode()
    for relative in (STATE_PATH, PATH):
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return [PATH]
