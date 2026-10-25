from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DRILL_ID = "LAB017-DRILL-01"


def identity_token(service_url: str) -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--audiences={service_url}"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def fetch_manifest(service_url: str, drill_id: str) -> dict:
    base = service_url.rstrip("/")
    token = identity_token(base)
    req = Request(
        f"{base}/ops/manifest?drill_id={drill_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(req, timeout=30) as response:
            if response.status != 200:
                raise SystemExit(f"manifest request failed: HTTP {response.status}")
            manifest = json.loads(response.read())
    except HTTPError as exc:
        raise SystemExit(f"manifest request failed: HTTP {exc.code}: {exc.read().decode(errors='replace')}")
    if not manifest.get("integrity_pass"):
        raise SystemExit("baseline integrity check failed; do not start the recovery drill")
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "service_url": base,
        "drill_id": drill_id,
        "manifest": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a verified Lab 17 record and attachment baseline.")
    parser.add_argument("--service-url", required=True)
    parser.add_argument("--output", default="lab017-baseline.json")
    parser.add_argument("--drill-id", default=DRILL_ID)
    args = parser.parse_args()
    baseline = fetch_manifest(args.service_url, args.drill_id)
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(baseline, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(f"baseline_saved={args.output} records={baseline['manifest']['database']['count']}")
