#!/usr/bin/env python3
"""Run one fixed-seed, bounded Catalog Cache measurement profile."""
import argparse
import fcntl
from concurrent.futures import ThreadPoolExecutor
import json
import math
import random
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

MAX_PROFILE_REQUESTS = 500
MAX_EXPERIMENT_REQUESTS = 2500
MAX_PROFILES = 5
MAX_WORKERS = 10
PROFILES = ("bypass", "cold", "warm", "redis-failure", "change-request")
CATEGORIES = ("books", "electronics", "home", "sports")
_thread_session = threading.local()


def validate_bounds(count, workers):
    if not 1 <= count <= MAX_PROFILE_REQUESTS:
        raise ValueError(f"requests must be between 1 and {MAX_PROFILE_REQUESTS}")
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")


def build_targets(count, seed):
    rng = random.Random(seed)
    targets = []
    for _ in range(count):
        if rng.random() < 0.8:
            product_id = rng.randint(1, 20)
            targets.append(f"/api/products/{product_id}")
        else:
            category = CATEGORIES[rng.randrange(len(CATEGORIES))]
            targets.append(f"/api/catalog?category={category}")
    return targets


def reserve_profile(out_dir, profile, count):
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "experiment.json"
    with (out_dir / ".experiment.lock").open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            manifest = {"schema_version": 1, "attempted_requests": 0, "profiles": {}}
        if profile in manifest["profiles"]:
            raise ValueError(f"profile {profile!r} is already reserved in this experiment")
        if len(manifest["profiles"]) >= MAX_PROFILES:
            raise ValueError(f"an experiment is limited to {MAX_PROFILES} profiles")
        total = manifest["attempted_requests"] + count
        if total > MAX_EXPERIMENT_REQUESTS:
            raise ValueError(f"experiment would exceed {MAX_EXPERIMENT_REQUESTS} requests")
        manifest["attempted_requests"] = total
        manifest["profiles"][profile] = {
            "reserved_requests": count,
            "reserved_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def session_for_thread():
    session = getattr(_thread_session, "session", None)
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=0)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_session.session = session
    return session


def request_one(base_url, target, run_id, timeout_seconds):
    started = time.perf_counter()
    try:
        response = session_for_thread().get(
            base_url + target,
            headers={"X-Lab-Run-ID": run_id},
            timeout=timeout_seconds,
        )
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "status": response.status_code,
            "cache": response.headers.get("X-Cache", "MISSING"),
            "latency_ms": round(elapsed, 3),
            "error": None if 200 <= response.status_code < 300 else "HTTPError",
        }
    except requests.RequestException as error:
        return {
            "status": None,
            "cache": "NO_RESPONSE",
            "latency_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": type(error).__name__,
        }


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)] if ordered else None


def run(args):
    validate_bounds(args.requests, args.workers)
    parsed = urlparse(args.base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base-url must be a root http(s) URL without credentials or query parameters")
    base_url = args.base_url.rstrip("/")
    started_at = datetime.now(timezone.utc)
    run_id = f"lab10-{args.profile}-{started_at:%Y%m%dT%H%M%SZ}"
    out_dir = Path(args.out_dir)
    reserve_profile(out_dir, args.profile, args.requests)
    targets = build_targets(args.requests, args.seed)
    with ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        results = list(executor.map(
            lambda target: request_one(base_url, target, run_id, args.timeout),
            targets,
        ))
    latencies = [result["latency_ms"] for result in results]
    statuses = Counter(str(result["status"]) for result in results)
    cache_counts = Counter(result["cache"] for result in results)
    errors = Counter(result["error"] for result in results if result["error"])
    summary = {
        "schema_version": 1,
        "profile": args.profile,
        "base_url_host": parsed.hostname,
        "run_id": run_id,
        "seed": args.seed,
        "requests_attempted": len(results),
        "workers": args.workers,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "http_status_counts": dict(statuses),
        "cache_status_counts": dict(cache_counts),
        "errors": dict(errors),
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "automatic_retries": 0,
        "request_details": results,
    }
    path = out_dir / f"{args.profile}.json"
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"result_file": str(path), **{k: summary[k] for k in (
        "profile", "requests_attempted", "workers", "http_status_counts",
        "cache_status_counts", "errors", "p50_ms", "p95_ms",
    )}}, sort_keys=True))
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--profile", required=True, choices=PROFILES)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261024)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--out-dir", default="lab10-results")
    args = parser.parse_args()
    if not 0.1 <= args.timeout <= 10:
        parser.error("--timeout must be between 0.1 and 10 seconds")
    try:
        return run(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
