from __future__ import annotations

import argparse
import json
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DRILL_ID = "LAB017-DRILL-01"
FIXTURES = [
    ("LAB017-REC-001", "Branch router replacement", "NEW", 12500, "quote-001.txt", "Router replacement estimate: 12500 cents."),
    ("LAB017-REC-002", "Warehouse scanner repair", "REVIEW", 45900, "quote-002.txt", "Scanner repair estimate: 45900 cents."),
    ("LAB017-REC-003", "North depot shelving", "APPROVED", 7800, "quote-003.txt", "Shelving order approved: 7800 cents."),
    ("LAB017-REC-004", "Cold room inspection", "REJECTED", 21300, "quote-004.txt", "Inspection estimate: 21300 cents."),
    ("LAB017-REC-005", "Office access panel", "NEW", 9900, "quote-005.txt", "Access panel estimate: 9900 cents."),
]


def identity_token(audience: str) -> str:
    result = subprocess.run(
        ["gcloud", "auth", "print-identity-token", f"--audiences={audience}"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def post_record(service_url: str, token: str, fixture: tuple) -> dict:
    ref, title, status, amount, filename, attachment = fixture
    payload = {
        "record_ref": ref, "drill_id": DRILL_ID, "title": title, "status": status,
        "amount_cents": amount, "attachment_name": filename, "attachment_text": attachment,
    }
    req = Request(
        service_url.rstrip("/") + "/v1/records",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(req, timeout=20) as response:
            result = json.loads(response.read())
            result["http_status"] = response.status
            return result
    except HTTPError as exc:
        raise SystemExit(f"Seed failed for {ref}: HTTP {exc.code}: {exc.read().decode(errors='replace')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the five fixed synthetic Lab 17 records.")
    parser.add_argument("--service-url", required=True)
    parser.add_argument("--audience", help="service URL used as the ID-token audience; defaults to --service-url")
    args = parser.parse_args()
    token = identity_token((args.audience or args.service_url).rstrip("/"))
    for fixture in FIXTURES:
        print(json.dumps(post_record(args.service_url, token, fixture), ensure_ascii=False))
    print(f"seeded_drill_id={DRILL_ID} fixture_count={len(FIXTURES)}")


if __name__ == "__main__":
    main()
