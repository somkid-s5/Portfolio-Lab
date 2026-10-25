#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a bounded Lab 19 Task API scenario.")
    parser.add_argument("--api-url", required=True, help="Task API URI printed by the runtime Terraform output.")
    parser.add_argument("--mode", choices=("valid", "invalid"), default="valid")
    parser.add_argument("--count", type=int, default=10, help="Maximum 500 requests per invocation.")
    parser.add_argument("--interval-ms", type=int, default=100)
    parser.add_argument("--verify-status", action="store_true", help="Read each accepted task once after a short wait.")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.api_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".run.app"):
        parser.error("--api-url must be the HTTPS Cloud Run *.run.app URL from this Lab.")
    if args.count < 1 or args.count > 500:
        parser.error("--count must be between 1 and 500.")
    if args.interval_ms < 0 or args.interval_ms > 2000:
        parser.error("--interval-ms must be between 0 and 2000.")
    return args


def identity_token() -> str:
    completed = subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        check=True,
        capture_output=True,
        text=True,
    )
    token = completed.stdout.strip()
    if not token:
        raise RuntimeError("gcloud returned an empty identity token.")
    return token


def request(url: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    headers = {"Authorization": "Bearer " + token}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            content = response.read().decode("utf-8")
            return response.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8", errors="replace")
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            decoded = {"body": content[:500]}
        return exc.code, decoded


def main() -> int:
    args = parse_args()
    token = identity_token()
    run_id = uuid.uuid4().hex[:12]
    counts: dict[str, int] = {}
    task_ids: list[str] = []
    started = time.monotonic()

    for index in range(args.count):
        if args.mode == "valid":
            body = {
                "idempotency_key": f"lab19-{run_id}-{index:04d}",
                "items": [{"sku": "DEMO-001", "quantity": 2, "unit_price_cents": 1250}],
            }
        else:
            body = {
                "idempotency_key": f"lab19-invalid-{run_id}-{index:04d}",
                "items": [{"sku": "not valid spaces", "quantity": 0, "unit_price_cents": -1}],
            }

        status, result = request(args.api_url.rstrip("/") + "/tasks", token, body)
        key = str(status)
        counts[key] = counts.get(key, 0) + 1
        task_id = result.get("task_id")
        if task_id:
            task_ids.append(task_id)
        print(json.dumps({"index": index + 1, "http_status": status, "task_id": task_id}, sort_keys=True))
        if args.interval_ms:
            time.sleep(args.interval_ms / 1000)

    status_counts = {int(code): count for code, count in counts.items()}
    expected_status = 202 if args.mode == "valid" else 422
    summary = {
        "mode": args.mode,
        "attempted": args.count,
        "http_status_counts": status_counts,
        "accepted_task_ids": task_ids,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "expected_status": expected_status,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.verify_status and task_ids:
        time.sleep(2)
        verified = 0
        for task_id in task_ids:
            get_status, task = request(args.api_url.rstrip("/") + "/tasks/" + task_id, token)
            if get_status == 200 and task.get("status") in {"QUEUED", "SUCCEEDED"}:
                verified += 1
        print(json.dumps({"status_reads": len(task_ids), "readable": verified}, sort_keys=True))
        if verified != len(task_ids):
            return 1

    return 0 if status_counts.get(expected_status, 0) == args.count else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"traffic tool failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
