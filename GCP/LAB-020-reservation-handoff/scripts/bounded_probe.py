"""Sequential, read-only Cloud Run probe. Maximum 30 requests; no load claim."""
import argparse
import json
import statistics
import time
import urllib.error
import urllib.request


def percentile(values, fraction):
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="IAP-protected API base URL")
    parser.add_argument("--token", required=True, help="Short-lived ID token; never save it")
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    if not 1 <= args.count <= 30:
        parser.error("--count must be between 1 and 30")
    latencies, failures = [], []
    for number in range(1, args.count + 1):
        request = urllib.request.Request(
            args.url.rstrip("/") + "/api/slots",
            headers={"Authorization": "Bearer " + args.token, "Accept": "application/json"},
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                elapsed = (time.monotonic() - started) * 1000
                if response.status != 200:
                    failures.append({"request": number, "status": response.status})
                else:
                    json.load(response); latencies.append(elapsed)
        except urllib.error.HTTPError as error:
            failures.append({"request": number, "status": error.code})
        except Exception as error:
            failures.append({"request": number, "error": type(error).__name__})
        time.sleep(0.2)
    result = {"requests": args.count, "successful": len(latencies), "failures": failures}
    if latencies:
        result.update(
            p50_ms=round(statistics.median(latencies), 2),
            p95_ms=round(percentile(latencies, 0.95), 2),
            min_ms=round(min(latencies), 2),
            max_ms=round(max(latencies), 2),
        )
    print(json.dumps(result, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
