"""Bounded HTTP probe for Lab 01. Python standard library only; no cloud writes."""
import argparse
import concurrent.futures
import csv
import json
import math
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def request_once(url, index, timeout):
    started = datetime.now(timezone.utc).isoformat()
    tick = time.perf_counter()
    status, backend, error = 0, '', ''
    try:
        # Each request has its own connection, with no client cookie affinity.
        req = Request(url + '/api?probe=' + uuid.uuid4().hex,
                      headers={'Connection': 'close', 'Cache-Control': 'no-cache'})
        with build_opener(ProxyHandler({})).open(req, timeout=timeout) as response:
            status = response.status
            result = json.loads(response.read())
            backend = result.get('hostname', '')
            if result.get('service') != 'field-notes' or not backend:
                error = 'Unexpected application payload'
    except HTTPError as exc:
        status, error = exc.code, str(exc)
    except Exception as exc:
        error = str(exc)
    return {'request': index, 'started_utc': started, 'status': status,
            'backend': backend, 'latency_ms': round((time.perf_counter() - tick) * 1000, 2),
            'error': error}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Origin only, e.g. http://203.0.113.10')
    parser.add_argument('--requests', type=int, default=100)
    parser.add_argument('--concurrency', type=int, default=5)
    parser.add_argument('--rate', type=float, default=5, help='Maximum submissions per second')
    parser.add_argument('--timeout', type=float, default=5)
    parser.add_argument('--out', required=True, help='New output file prefix; existing files are not overwritten')
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username
            or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        parser.error('--url must be an HTTP(S) origin without path, query or credentials')
    if not (1 <= args.requests <= 600 and 1 <= args.concurrency <= 10
            and 0 < args.rate <= 10 and 0 < args.timeout <= 30):
        parser.error('Limits: 1–600 requests, 1–10 workers, rate <=10/s, timeout <=30s')
    prefix = Path(args.out)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    csv_path, json_path = Path(str(prefix) + '.csv'), Path(str(prefix) + '.json')
    if csv_path.exists() or json_path.exists():
        parser.error('Output already exists. Choose a new --out prefix for this run.')
    started = time.perf_counter()
    futures = []
    # Bound both queued and running work so slow targets cannot build an unbounded backlog.
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        pending = set()
        next_submission = started
        for index in range(1, args.requests + 1):
            if len(pending) >= args.concurrency:
                _, pending = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
            delay = next_submission - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            next_submission = time.perf_counter() + 1 / args.rate
            future = pool.submit(request_once, args.url.rstrip('/'), index, args.timeout)
            futures.append(future)
            pending.add(future)
        rows = [future.result() for future in futures]
    duration = time.perf_counter() - started
    ok = [row for row in rows if row['status'] == 200 and not row['error']]
    latencies = sorted(row['latency_ms'] for row in ok)
    summary = {
        'finished_utc': datetime.now(timezone.utc).isoformat(), 'url': args.url,
        'requests': len(rows), 'concurrency': args.concurrency, 'submission_rate_limit': args.rate,
        'success': len(ok), 'failed': len(rows) - len(ok),
        'error_rate_pct': round((len(rows) - len(ok)) / len(rows) * 100, 2),
        'duration_seconds': round(duration, 2), 'observed_rps': round(len(rows) / duration, 2),
        'p95_success_latency_ms': latencies[math.ceil(len(latencies) * .95) - 1] if latencies else None,
        'backend_counts': dict(Counter(row['backend'] for row in ok)),
        'status_counts': dict(Counter(str(row['status']) for row in rows)),
        'note': 'Client-observed sample. Not a production capacity or availability certification.'
    }
    with csv_path.open('x', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with json_path.open('x', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if len(ok) == len(rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
