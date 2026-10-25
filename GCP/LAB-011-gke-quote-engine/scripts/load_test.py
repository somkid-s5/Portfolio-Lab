#!/usr/bin/env python3
"""Bounded HTTPS load generator for the GKE quote endpoint."""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import http.client
import json
import os
from pathlib import Path
import socket
import ssl
import statistics
import time
from urllib.parse import urlsplit


MAX_DURATION_SECONDS = 180
MAX_CONCURRENCY = 8
MAX_REQUESTS = 5000
REQUEST_BODY = json.dumps({
    "weight_kg": 2.0,
    "distance_km": 100.0,
    "service_level": "standard",
}).encode("utf-8")


class ResolvedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a supplied LB IP while preserving TLS SNI and hostname checks."""

    def __init__(self, hostname, connect_ip, port, context, timeout):
        super().__init__(hostname, port=port, context=context, timeout=timeout)
        self.connect_ip = connect_ip

    def connect(self):
        raw = socket.create_connection((self.connect_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="HTTPS URL with the Gateway certificate hostname")
    parser.add_argument("--resolve-ip", required=True, help="Gateway frontend IP from kubectl status")
    parser.add_argument("--ca-file", required=True, type=Path, help="Self-signed certificate to trust for this lab")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-requests", type=int, default=1200)
    parser.add_argument("--timeout-seconds", type=float, default=4.0)
    args = parser.parse_args()
    parts = urlsplit(args.url)
    if parts.scheme != "https" or not parts.hostname or parts.path != "/v1/quotes":
        parser.error("--url must be an HTTPS URL ending in /v1/quotes")
    if not args.ca_file.is_file():
        parser.error("--ca-file must point to the lab certificate")
    if not 1 <= args.duration_seconds <= MAX_DURATION_SECONDS:
        parser.error(f"--duration-seconds must be 1..{MAX_DURATION_SECONDS}")
    if not 1 <= args.concurrency <= MAX_CONCURRENCY:
        parser.error(f"--concurrency must be 1..{MAX_CONCURRENCY}")
    if not 1 <= args.max_requests <= MAX_REQUESTS:
        parser.error(f"--max-requests must be 1..{MAX_REQUESTS}")
    if not 0.2 <= args.timeout_seconds <= 10:
        parser.error("--timeout-seconds must be 0.2..10")
    args.hostname = parts.hostname
    args.port = parts.port or 443
    return args


def one_request(args, context, token):
    connection = ResolvedHTTPSConnection(
        args.hostname, args.resolve_ip, args.port, context, args.timeout_seconds
    )
    started = time.monotonic()
    try:
        connection.request(
            "POST",
            "/v1/quotes",
            body=REQUEST_BODY,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        response.read(1024)
        return response.status, (time.monotonic() - started) * 1000
    finally:
        connection.close()


def main():
    args = parse_args()
    token = os.environ.get("API_TOKEN", "")
    if not token:
        raise SystemExit("Set API_TOKEN in the current shell; never put it in this command line.")
    context = ssl.create_default_context(cafile=str(args.ca_file))
    started = time.monotonic()
    deadline = started + args.duration_seconds
    submitted = 0
    completed = 0
    statuses = {}
    latencies = []
    failures = 0
    pending = set()
    executor = ThreadPoolExecutor(max_workers=args.concurrency)
    try:
        while time.monotonic() < deadline and submitted < args.max_requests:
            while len(pending) < args.concurrency and submitted < args.max_requests and time.monotonic() < deadline:
                pending.add(executor.submit(one_request, args, context, token))
                submitted += 1
            done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                completed += 1
                try:
                    status, latency = future.result()
                    statuses[str(status)] = statuses.get(str(status), 0) + 1
                    latencies.append(latency)
                except (OSError, TimeoutError, http.client.HTTPException):
                    failures += 1
    finally:
        if pending:
            done, unfinished = wait(pending, timeout=args.timeout_seconds + 1)
            for future in done:
                completed += 1
                try:
                    status, latency = future.result()
                    statuses[str(status)] = statuses.get(str(status), 0) + 1
                    latencies.append(latency)
                except (OSError, TimeoutError, http.client.HTTPException):
                    failures += 1
            failures += len(unfinished)
        executor.shutdown(wait=True, cancel_futures=True)

    elapsed = time.monotonic() - started
    latencies.sort()
    def percentile(p):
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, int((len(latencies) - 1) * p))], 2)
    summary = {
        "submitted": submitted,
        "completed": completed,
        "transport_failures": failures,
        "http_statuses": statuses,
        "elapsed_seconds": round(elapsed, 2),
        "requests_per_second": round(completed / elapsed, 2) if elapsed else 0,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "p95": percentile(0.95),
            "max": round(max(latencies), 2) if latencies else None,
        },
        "note": "measurement from this run only; not a capacity or SLA claim",
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    if failures or statuses.get("200", 0) != completed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
