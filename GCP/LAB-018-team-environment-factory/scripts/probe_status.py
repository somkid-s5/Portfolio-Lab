from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

MAX_REQUESTS = 10


def get_token(audience: str) -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("gcloud could not create an identity token; check the active account and gcloud login")
    return result.stdout.strip()


def probe(url: str, mode: str, count: int, timeout: float) -> int:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.query or parts.fragment:
        print("ERROR: --url must be an HTTPS service URL without query or fragment", file=sys.stderr)
        return 2
    endpoint = url.rstrip("/") + "/healthz"
    token = get_token(url.rstrip("/") + "/") if mode == "authenticated" else None
    statuses: list[int] = []

    for _ in range(count):
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(endpoint, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = response.status
                body = json.loads(response.read(4096).decode("utf-8")) if status == 200 else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = {}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            print("ERROR: request failed or returned invalid JSON; inspect service URL and Cloud Run logs", file=sys.stderr)
            return 1

        statuses.append(status)
        if mode == "authenticated" and (
            status != 200 or body.get("status") != "ok" or not body.get("environment")
        ):
            print(f"FAIL: authenticated request returned HTTP {status}")
            return 1
        if mode == "unauthenticated" and status not in (401, 403):
            print(f"FAIL: unauthenticated request returned HTTP {status}; expected 401 or 403")
            return 1

    print(f"PASS: mode={mode}; requests={len(statuses)}; statuses={','.join(map(str, statuses))}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small, bounded check against Lab 18 Status API.")
    parser.add_argument("--url", required=True, help="Cloud Run service URL.")
    parser.add_argument("--mode", choices=("authenticated", "unauthenticated"), required=True)
    parser.add_argument("--count", type=int, default=1, help=f"Requests (1-{MAX_REQUESTS}; default 1).")
    parser.add_argument("--timeout", type=float, default=5.0, help="Per-request timeout in seconds (1-10).")
    args = parser.parse_args()
    if not 1 <= args.count <= MAX_REQUESTS:
        parser.error(f"--count must be between 1 and 10")
    if not 1 <= args.timeout <= 10:
        parser.error("--timeout must be between 1 and 10 seconds")
    try:
        return probe(args.url, args.mode, args.count, args.timeout)
    except (OSError, subprocess.TimeoutExpired, RuntimeError):
        print("ERROR: authentication tool failed or timed out; token value was not displayed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
