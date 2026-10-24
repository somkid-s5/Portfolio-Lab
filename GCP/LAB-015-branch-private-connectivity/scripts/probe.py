#!/usr/bin/env python3
"""Bounded branch probe for the private Inventory API; never prints ID tokens."""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urlsplit

METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
)


def build_request(url: str, token: str | None) -> urllib.request.Request:
    headers = {"Accept": "application/json", "User-Agent": "lab015-branch-probe/1.0"}
    if token:
        headers["X-Serverless-Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers, method="GET")


def get_id_token(audience: str, opener=urllib.request.urlopen) -> str:
    url = f"{METADATA_IDENTITY_URL}?audience={quote(audience, safe='')}&format=full"
    request = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with opener(request, timeout=5) as response:
        token = response.read().decode("utf-8").strip()
    if not token or "." not in token:
        raise RuntimeError("metadata server did not return an ID token")
    return token


def probe_once(url: str, audience: str, timeout: int, unauthenticated: bool = False) -> tuple[int, dict]:
    token = None if unauthenticated else get_id_token(audience)
    request = build_request(url, token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
        return 0, {"error": "connection_error", "detail": str(reason)}
    try:
        payload = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {"body": "non-json response"}
    return status, payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Private endpoint, such as http://inventory.lab.internal/v1/items")
    parser.add_argument("--audience", required=True, help="Cloud Run service URI, not the private LB URL")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--duration", type=int, default=0, help="Continuous probe duration in seconds; 0 runs once.")
    parser.add_argument("--interval", type=int, default=2)
    parser.add_argument("--expect-deny", action="store_true", help="Send no token and pass only on HTTP 401/403.")
    args = parser.parse_args(argv)
    if urlsplit(args.url).scheme != "http" or not urlsplit(args.url).hostname:
        parser.error("--url must be an http:// URL reachable inside the lab")
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be between 1 and 30 seconds")
    if not 0 <= args.duration <= 900:
        parser.error("--duration must be between 0 and 900 seconds")
    if not 1 <= args.interval <= 30:
        parser.error("--interval must be between 1 and 30 seconds")
    if args.expect_deny and args.duration:
        parser.error("--expect-deny cannot be combined with a continuous probe")

    started = time.monotonic()
    successes = failures = 0
    while True:
        try:
            status, payload = probe_once(
                args.url, args.audience, args.timeout, unauthenticated=args.expect_deny
            )
        except (RuntimeError, urllib.error.URLError, TimeoutError, OSError) as exc:
            status, payload = 0, {"error": "token_or_probe_error", "detail": str(exc)}
        denied = args.expect_deny and status in (401, 403)
        ok = denied or status == 200
        successes += int(ok)
        failures += int(not ok)
        result = {
            "time_unix": round(time.time(), 3),
            "result": "expected-deny" if denied else ("success" if status == 200 else "failure"),
            "http_status": status,
        }
        if status == 200:
            result["item_count"] = payload.get("count")
            result["service_status"] = payload.get("status")
        elif status not in (401, 403) or not args.expect_deny:
            result["error"] = payload.get("error", "unexpected_response")
        print(json.dumps(result, separators=(",", ":")), flush=True)
        if not args.duration:
            return 0 if ok else 1
        elapsed = time.monotonic() - started
        if elapsed >= args.duration:
            break
        time.sleep(min(args.interval, max(0, args.duration - elapsed)))
    print(json.dumps({"summary": {"successes": successes, "failures": failures}}, separators=(",", ":")), flush=True)
    return 0 if successes > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
