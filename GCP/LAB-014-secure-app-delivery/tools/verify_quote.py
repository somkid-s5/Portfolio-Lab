from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any


def fetch_json(url: str, timeout: int) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "lab014-verifier/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(64 * 1024 + 1)
            if len(raw) > 64 * 1024:
                raise ValueError("response exceeds 64 KiB")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON response must be an object")
            return response.status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": "http_error"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed: {type(exc).__name__}") from exc


def verify_once(base_url: str, expected_total: Decimal, timeout: int, expected_commit: str | None = None) -> None:
    health_status, health = fetch_json(base_url + "/healthz", timeout)
    if health_status != 200 or health.get("status") != "ok":
        raise RuntimeError("health check did not return status=ok")

    quote_url = base_url + "/api/v1/quote?" + urllib.parse.urlencode(
        {"origin": "BKK", "destination": "CNX", "weight_kg": "5"}
    )
    quote_status, quote = fetch_json(quote_url, timeout)
    if quote_status != 200 or quote.get("currency") != "THB":
        raise RuntimeError("quote endpoint returned an invalid response")
    try:
        actual = Decimal(str(quote["total_thb"]))
    except (KeyError, ArithmeticError, ValueError) as exc:
        raise RuntimeError("quote response is missing a valid total_thb") from exc
    if actual != expected_total:
        raise RuntimeError(f"business quote mismatch: expected {expected_total:.2f}, got {actual:.2f}")

    if expected_commit:
        version_status, version = fetch_json(base_url + "/version", timeout)
        if version_status != 200 or version.get("commit_sha") != expected_commit:
            raise RuntimeError("deployed commit does not match the expected commit")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded health and business-contract probe for Lab 14.")
    parser.add_argument("--url", default=None, help="target HTTPS URL; otherwise CLOUD_RUN_SERVICE_URLS is used")
    parser.add_argument("--expected-total", default="455.00")
    parser.add_argument("--expected-commit", default=None)
    parser.add_argument("--attempts", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=3)
    parser.add_argument("--interval-seconds", type=int, default=2)
    parser.add_argument("--allow-http", action="store_true", help="allow HTTP only for localhost tests")
    args = parser.parse_args(argv)
    if not 1 <= args.attempts <= 10:
        parser.error("--attempts must be between 1 and 10")
    if not 1 <= args.timeout_seconds <= 5:
        parser.error("--timeout-seconds must be between 1 and 5")
    if not 0 <= args.interval_seconds <= 3:
        parser.error("--interval-seconds must be between 0 and 3")
    try:
        expected = Decimal(args.expected_total)
    except Exception:
        parser.error("--expected-total must be a decimal number")
    if not expected.is_finite() or expected <= 0 or expected.as_tuple().exponent < -2:
        parser.error("--expected-total must be positive with at most two decimal places")
    args.expected = expected
    return args


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    target = args.url or os.environ.get("CLOUD_RUN_SERVICE_URLS", "").split(",")[0].strip()
    if not target:
        print(json.dumps({"result": "fail", "reason": "target URL is required"}), file=sys.stderr)
        return 2
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in (("https", "http") if args.allow_http else ("https",)):
        print(json.dumps({"result": "fail", "reason": "target must use HTTPS"}), file=sys.stderr)
        return 2
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        print(json.dumps({"result": "fail", "reason": "target URL is invalid"}), file=sys.stderr)
        return 2
    if args.allow_http and parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        print(json.dumps({"result": "fail", "reason": "HTTP is allowed only for localhost"}), file=sys.stderr)
        return 2
    started = time.monotonic()
    last_error = "no attempt"
    for attempt in range(1, args.attempts + 1):
        try:
            verify_once(target.rstrip("/"), args.expected, args.timeout_seconds, args.expected_commit)
            print(json.dumps({"result": "pass", "attempt": attempt, "checks": ["healthz", "quote", "version"]}))
            return 0
        except RuntimeError as exc:
            last_error = str(exc)
        if attempt < args.attempts:
            elapsed = time.monotonic() - started
            if elapsed + args.interval_seconds >= 45:
                last_error = "overall 45-second limit reached"
                break
            time.sleep(args.interval_seconds)
    print(json.dumps({"result": "fail", "attempts": args.attempts, "reason": last_error}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
