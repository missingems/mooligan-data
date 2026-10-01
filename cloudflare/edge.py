"""Puts data.mooligan.com's cost guards in place on Cloudflare: cache, rate limit, private paths.

R2 bills each read that reaches the bucket, and nothing Cloudflare's cache answers.
JSON isn't cached by default, and a query string makes a new cache entry, so
without these rules every app request, and every `?x=<random>` an abuser sends,
is a billed read. This script owns four things and nothing else:

- a cache rule for the host: cache everything, honour each file's Cache-Control,
  and leave the query string out of the cache key;
- Tiered Cache, so Cloudflare's data centres refill from each other, not from R2;
- a rate limit per IP on the host;
- a firewall rule blocking `state/`, the scraper's bookkeeping, which is uncached
  and which only the scraper reads, through the S3 API.

It also turns off the bucket's r2.dev URL, which bypasses all of the above.

Rules are found by their `ref`, so rules made by hand in the same phases stay as
they are. Without --apply it only prints what it would change.

Needs CLOUDFLARE_API_TOKEN (Zone: Zone Read, Cache Rules Edit, Zone WAF Edit,
Zone Settings Edit; Account: Workers R2 Storage Edit) and CLOUDFLARE_ACCOUNT_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

API = "https://api.cloudflare.com/client/v4"
ZONE = "mooligan.com"
HOST = "data.mooligan.com"
BUCKET = "mtg-meta-data"
REF_PREFIX = "mooligan-data-"
# Fields a rule keeps when sent back; the rest (version, last_updated) are read-only.
WRITABLE = ("id", "ref", "expression", "action", "action_parameters", "description", "enabled", "ratelimit", "logging")


def desired_rules(host: str, requests_per_10s: int) -> Dict[str, dict]:
    """The rule this script owns in each ruleset phase."""
    on_host = f'(http.host eq "{host}")'
    return {
        "http_request_cache_settings": {
            "ref": REF_PREFIX + "cache",
            "description": f"{host}: cache everything, honour Cache-Control, ignore query strings",
            "expression": on_host,
            "action": "set_cache_settings",
            "action_parameters": {
                "cache": True,
                "edge_ttl": {"mode": "respect_origin"},
                "browser_ttl": {"mode": "respect_origin"},
                "cache_key": {"custom_key": {"query_string": {"exclude": {"all": True}}}},
            },
            "enabled": True,
        },
        "http_request_firewall_custom": {
            "ref": REF_PREFIX + "private",
            "description": f"{host}: state/ is the scraper's, read through the S3 API",
            "expression": f'(http.host eq "{host}" and starts_with(http.request.uri.path, "/state/"))',
            "action": "block",
            "enabled": True,
        },
        "http_ratelimit": {
            "ref": REF_PREFIX + "rate",
            "description": f"{host}: at most {requests_per_10s} requests per IP per 10 seconds",
            "expression": on_host,
            "action": "block",
            "ratelimit": {
                "characteristics": ["cf.colo.id", "ip.src"],
                "period": 10,
                "requests_per_period": requests_per_10s,
                "mitigation_timeout": 10,
            },
            "enabled": True,
        },
    }


def merge(existing: List[dict], ours: dict) -> Tuple[List[dict], bool]:
    """Returns the phase's rules with ours in place of any earlier copy, and whether anything changed."""
    kept, previous = [], None
    for rule in existing:
        if rule.get("ref") == ours["ref"]:
            previous = rule
        else:
            kept.append({key: rule[key] for key in WRITABLE if key in rule})
    wanted = dict(ours)
    if previous is not None and "id" in previous:
        wanted["id"] = previous["id"]
    changed = previous is None or any(previous.get(key) != value for key, value in ours.items())
    return kept + [wanted], changed


class CloudflareError(Exception):
    pass


class Cloudflare:
    def __init__(self, token: str):
        self._token = token

    def call(self, method: str, path: str, body: Optional[dict] = None):
        request = urllib.request.Request(
            API + path,
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read())
            except ValueError:
                raise CloudflareError(f"{method} {path}: HTTP {error.code}") from None
            if error.code == 404 and method == "GET":
                return None
        if not payload.get("success", False):
            messages = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors", []))
            raise CloudflareError(f"{method} {path}: {messages or 'failed'}")
        return payload.get("result")


def configure(cf: Cloudflare, account_id: str, requests_per_10s: int, apply: bool) -> List[str]:
    """Brings each guard in line, returning the errors met along the way."""
    errors: List[str] = []
    verb = "Updating" if apply else "Would update"

    def step(name, run):
        try:
            run()
        except CloudflareError as error:
            print(f"✗ {name}: {error}")
            errors.append(f"{name}: {error}")

    zones = cf.call("GET", f"/zones?name={ZONE}") or []
    if not zones:
        raise CloudflareError(f"zone {ZONE} not found, or the token can't read it")
    zone = zones[0]["id"]

    for phase, ours in desired_rules(HOST, requests_per_10s).items():
        def apply_rule(phase=phase, ours=ours):
            entrypoint = cf.call("GET", f"/zones/{zone}/rulesets/phases/{phase}/entrypoint") or {}
            rules, changed = merge(entrypoint.get("rules", []), ours)
            if not changed:
                print(f"✓ {phase}: {ours['ref']} already in place")
                return
            print(f"→ {verb} {phase}: {ours['description']}")
            if apply:
                cf.call("PUT", f"/zones/{zone}/rulesets/phases/{phase}/entrypoint", {"rules": rules})
        step(phase, apply_rule)

    for name, path in (
        ("Tiered Cache", f"/zones/{zone}/argo/tiered_caching"),
        ("Smart Tiered Cache topology", f"/zones/{zone}/cache/tiered_cache_smart_topology_enable"),
    ):
        def apply_setting(name=name, path=path):
            current = (cf.call("GET", path) or {}).get("value")
            if current == "on":
                print(f"✓ {name}: on")
                return
            print(f"→ {verb} {name}: {current} → on")
            if apply:
                cf.call("PATCH", path, {"value": "on"})
        step(name, apply_setting)

    def apply_r2_dev():
        path = f"/accounts/{account_id}/r2/buckets/{BUCKET}/domains/managed"
        enabled = (cf.call("GET", path) or {}).get("enabled")
        if enabled is False:
            print(f"✓ r2.dev URL of {BUCKET}: off")
            return
        print(f"→ {verb} r2.dev URL of {BUCKET}: on → off")
        if apply:
            cf.call("PUT", path, {"enabled": False})
    step("r2.dev URL", apply_r2_dev)

    return errors


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="make the changes; without it, only print them")
    parser.add_argument("--requests-per-10s", type=int, default=200, help="rate limit per IP (default 200)")
    args = parser.parse_args(argv)
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not token or not account_id:
        print("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID are required", file=sys.stderr)
        return 2
    try:
        errors = configure(Cloudflare(token), account_id, args.requests_per_10s, args.apply)
    except CloudflareError as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1
    if not args.apply:
        print("Dry run: nothing changed. Run with --apply to make these changes.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
