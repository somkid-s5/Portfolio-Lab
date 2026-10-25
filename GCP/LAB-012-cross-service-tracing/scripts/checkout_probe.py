"""Bounded HTTPS checkout probe; does not report a benchmark or SLO."""
from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import socket
import ssl
import statistics
import time
import uuid


class ResolvedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, address: str, port: int, context: ssl.SSLContext, timeout: float):
        super().__init__(hostname, port=port, context=context, timeout=timeout)
        self.address = address
        self.connect_timeout = timeout

    def connect(self) -> None:
        self.sock = socket.create_connection((self.address, self.port), self.connect_timeout)
        self.sock.settimeout(self.connect_timeout)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="TLS hostname in the certificate SAN, e.g. checkout.lab.local")
    parser.add_argument("--ip", required=True, help="regional Gateway IPv4 address")
    parser.add_argument("--ca", required=True, help="path to the self-signed lab certificate")
    parser.add_argument("--requests", type=int, default=12, help="number of requests (1-60)")
    parser.add_argument("--workers", type=int, default=2, help="parallel workers (1-4)")
    parser.add_argument("--timeout", type=float, default=4.0, help="per-connection timeout in seconds (1-10)")
    args = parser.parse_args()
    if not 1 <= args.requests <= 60:
        parser.error("--requests must be between 1 and 60")
    if not 1 <= args.workers <= 4 or args.workers > args.requests:
        parser.error("--workers must be between 1 and 4 and no greater than --requests")
    if not 1 <= args.timeout <= 10:
        parser.error("--timeout must be between 1 and 10 seconds")
    if not args.host or "/" in args.host or ":" in args.host:
        parser.error("--host must be a bare hostname")
    try:
        socket.inet_pton(socket.AF_INET, args.ip)
    except OSError:
        parser.error("--ip must be an IPv4 address")
    return args


def one_request(args: argparse.Namespace, token: str, index: int) -> tuple[int | None, float, str | None]:
    context = ssl.create_default_context(cafile=args.ca)
    connection = ResolvedHTTPSConnection(args.host, args.ip, 443, context, args.timeout)
    started = time.monotonic()
    try:
        payload = json.dumps({"sku": "SKU-001", "quantity": 1}).encode("utf-8")
        connection.request(
            "POST",
            "/v1/checkout",
            body=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Lab-Probe": str(index),
            },
        )
        response = connection.getresponse()
        response.read(4096)
        return response.status, time.monotonic() - started, None
    except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
        return None, time.monotonic() - started, type(exc).__name__
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    import os

    token = os.getenv("LAB012_DEMO_TOKEN", "")
    if not token:
        raise SystemExit("Set LAB012_DEMO_TOKEN in the current shell; do not pass it as a command-line argument.")
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda index: one_request(args, token, index), range(args.requests)))
    statuses: dict[str, int] = {}
    failures: dict[str, int] = {}
    latencies = []
    for status, elapsed, failure in results:
        latencies.append(elapsed)
        if status is not None:
            statuses[str(status)] = statuses.get(str(status), 0) + 1
        if failure:
            failures[failure] = failures.get(failure, 0) + 1
    report = {
        "requests_sent": len(results),
        "workers": args.workers,
        "http_status_counts": statuses,
        "transport_failures": failures,
        "latency_seconds": {
            "min": round(min(latencies), 4),
            "median": round(statistics.median(latencies), 4),
            "max": round(max(latencies), 4),
        },
        "interpretation": "single bounded lab observation; not a benchmark, capacity claim, or SLO",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if statuses == {"200": args.requests} and not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
