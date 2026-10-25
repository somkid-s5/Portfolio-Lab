"""Bounded negative network-policy probe used by the lab's isolated test Pod."""
from __future__ import annotations

import json
import os
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def probe_worker(timeout_seconds: float = 3.0) -> int:
    base = os.environ.get(
        "QUOTE_WORKER_URL",
        "http://quote-worker.quote-platform.svc.cluster.local:8081",
    ).rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "http" or not parsed.hostname or not parsed.port:
        print("NETWORK_TEST_INCONCLUSIVE reason=invalid_worker_url")
        return 3
    try:
        socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
    except OSError as exc:
        print(f"NETWORK_TEST_INCONCLUSIVE error_type={type(exc).__name__}")
        return 3

    payload = {
        "quote_id": "network-policy-probe",
        "weight_kg": 1.0,
        "distance_km": 1.0,
        "service_level": "standard",
    }
    request = Request(
        base + "/internal/quote",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read(2048)
    except HTTPError as exc:
        print(f"NETWORK_ALLOWED unexpected_http_status={exc.code}")
        return 4
    except URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            print("NETWORK_DENIED reason=connection_timeout")
            return 0
        print(f"NETWORK_TEST_INCONCLUSIVE error_type={type(exc.reason).__name__}")
        return 3
    except (socket.timeout, TimeoutError):
        print("NETWORK_DENIED reason=connection_timeout")
        return 0
    except OSError as exc:
        print(f"NETWORK_TEST_INCONCLUSIVE error_type={type(exc).__name__}")
        return 3
    print("NETWORK_ALLOWED unexpected_worker_response")
    return 4
