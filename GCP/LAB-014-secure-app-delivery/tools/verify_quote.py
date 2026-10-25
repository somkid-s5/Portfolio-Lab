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

RUN_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
RUN_API = "https://run.googleapis.com/v2"
MAX_RESPONSE_BYTES = 64 * 1024


def fetch_json(url: str, timeout: float, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "lab014-verifier/1", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError("response exceeds 64 KiB")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("JSON response must be an object")
            return response.status, payload
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": "http_error"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed: {type(exc).__name__}") from exc


def _revision_id(value: str) -> str:
    return value.rsplit("/revisions/", 1)[-1].strip()


def select_revision_url(
    traffic_statuses: list[dict[str, Any]],
    expected_revision: str,
    expected_tag: str | None,
    expected_percent: int,
) -> str:
    expected_id = _revision_id(expected_revision)
    matches = [
        item for item in traffic_statuses
        if _revision_id(str(item.get("revision", ""))) == expected_id
        and item.get("tag") == expected_tag
    ]
    if len(matches) != 1:
        raise RuntimeError("service traffic status does not contain exactly one matching revision and tag")
    selected = matches[0]
    if selected.get("percent") != expected_percent:
        raise RuntimeError(f"revision traffic mismatch: expected {expected_percent} percent")
    url = selected.get("uri")
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("selected revision/tag has no valid HTTPS verification URL")
    return url.rstrip("/")


def _cloud_run_target_url(timeout: int) -> tuple[str, dict[str, str]]:
    project = os.environ.get("CLOUD_RUN_PROJECT", "").strip()
    location = os.environ.get("CLOUD_RUN_LOCATION", "").strip()
    service = os.environ.get("CLOUD_RUN_SERVICE", "").strip()
    revision = os.environ.get("CLOUD_RUN_REVISION", "").strip()
    target = os.environ.get("CLOUD_DEPLOY_TARGET", "").strip()
    phase = os.environ.get("CLOUD_DEPLOY_PHASE", "").strip()
    if not all((project, location, service, revision, target, phase)):
        raise RuntimeError("Cloud Deploy target identity is incomplete")

    if target == "staging":
        if phase != "stable":
            raise RuntimeError("staging verification expected the stable phase")
        tag, expected_percent = None, 100
    elif target == "production":
        if phase == "stable":
            tag, expected_percent = "lab014-stable", 100
        elif phase == "canary-10":
            tag, expected_percent = "lab014-candidate", 10
        elif phase == "canary-50":
            tag, expected_percent = "lab014-candidate", 50
        else:
            raise RuntimeError(f"unsupported production phase: {phase}")
    else:
        raise RuntimeError(f"unsupported Cloud Deploy target: {target}")

    from google.auth import default
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    request = Request()
    try:
        credentials, _ = default(scopes=[RUN_SCOPE])
        credentials.refresh(request)
    except Exception as exc:
        raise RuntimeError(f"Cloud Run service lookup credentials failed: {type(exc).__name__}") from exc

    service_id = service.rsplit("/services/", 1)[-1]
    api_url = (
        f"{RUN_API}/projects/{urllib.parse.quote(project, safe='')}"
        f"/locations/{urllib.parse.quote(location, safe='')}"
        f"/services/{urllib.parse.quote(service_id, safe='')}"
    )
    status, resource = fetch_json(api_url, timeout, {"Authorization": f"Bearer {credentials.token}"})
    if status != 200:
        raise RuntimeError(f"Cloud Run service lookup failed with HTTP {status}")
    statuses = resource.get("trafficStatuses")
    if not isinstance(statuses, list):
        raise RuntimeError("Cloud Run service response omitted trafficStatuses")

    target_url = select_revision_url(statuses, revision, tag, expected_percent)
    service_uri = resource.get("uri")
    parsed_service_uri = urllib.parse.urlparse(service_uri or "")
    if parsed_service_uri.scheme != "https" or not parsed_service_uri.hostname:
        raise RuntimeError("Cloud Run service response omitted a valid canonical URI for the identity-token audience")
    try:
        identity_token = id_token.fetch_id_token(request, service_uri.rstrip("/"))
    except Exception as exc:
        raise RuntimeError(f"Cloud Run invocation identity token failed: {type(exc).__name__}") from exc
    return target_url, {"Authorization": f"Bearer {identity_token}"}


def verify_once(
    base_url: str,
    expected_total: Decimal,
    timeout: int,
    expected_commit: str | None = None,
    deadline: float | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    def request_timeout() -> float:
        if deadline is None:
            return timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("overall 45-second verification limit reached")
        return min(float(timeout), remaining)

    health_status, health = fetch_json(base_url + "/healthz", request_timeout(), headers)
    if health_status != 200 or health.get("status") != "ok":
        raise RuntimeError("health check did not return status=ok")
    quote_url = base_url + "/api/v1/quote?" + urllib.parse.urlencode(
        {"origin": "BKK", "destination": "CNX", "weight_kg": "5"}
    )
    quote_status, quote = fetch_json(quote_url, request_timeout(), headers)
    if quote_status != 200 or quote.get("currency") != "THB":
        raise RuntimeError("quote endpoint returned an invalid response")
    try:
        actual = Decimal(str(quote["total_thb"]))
    except (KeyError, ArithmeticError, ValueError) as exc:
        raise RuntimeError("quote response is missing a valid total_thb") from exc
    if actual != expected_total:
        raise RuntimeError(f"business quote mismatch: expected {expected_total:.2f}, got {actual:.2f}")
    if expected_commit:
        version_status, version = fetch_json(base_url + "/version", request_timeout(), headers)
        if version_status != 200 or version.get("commit_sha") != expected_commit:
            raise RuntimeError("deployed commit does not match the expected commit")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded health and business-contract probe for Lab 14.")
    parser.add_argument("--url", default=None, help="direct HTTPS target; otherwise use exact Cloud Deploy revision")
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
    started = time.monotonic()
    deadline = started + 45
    cloud_deploy = not args.url and bool(os.environ.get("CLOUD_RUN_REVISION"))
    target_headers = None
    if cloud_deploy:
        try:
            target_url, target_headers = _cloud_run_target_url(args.timeout_seconds)
        except RuntimeError as exc:
            print(json.dumps({"result": "fail", "reason": str(exc)}), file=sys.stderr)
            return 1
    else:
        target_url = args.url or os.environ.get("CLOUD_RUN_SERVICE_URLS", "").split(",")[0].strip()

    if not target_url:
        print(json.dumps({"result": "fail", "reason": "target URL is required"}), file=sys.stderr)
        return 2
    parsed = urllib.parse.urlparse(target_url)
    if parsed.scheme not in (("https", "http") if args.allow_http else ("https",)):
        print(json.dumps({"result": "fail", "reason": "target must use HTTPS"}), file=sys.stderr)
        return 2
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        print(json.dumps({"result": "fail", "reason": "target URL is invalid"}), file=sys.stderr)
        return 2
    if args.allow_http and parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        print(json.dumps({"result": "fail", "reason": "HTTP is allowed only for localhost"}), file=sys.stderr)
        return 2

    last_error = "no attempt"
    for attempt in range(1, args.attempts + 1):
        try:
            expected_commit = args.expected_commit or os.environ.get("COMMIT_SHA")
            verify_once(target_url.rstrip("/"), args.expected, args.timeout_seconds, expected_commit, deadline, target_headers)
            print(json.dumps({"result": "pass", "attempt": attempt, "checks": ["revision-routing", "healthz", "quote", "commit"]}))
            return 0
        except RuntimeError as exc:
            last_error = str(exc)
        if attempt < args.attempts:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or args.interval_seconds >= remaining:
                last_error = "overall 45-second verification limit reached"
                break
            time.sleep(args.interval_seconds)
    print(json.dumps({"result": "fail", "attempts": args.attempts, "reason": last_error}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
