from __future__ import annotations

import argparse
import json
from pathlib import Path

FIELDS = (
    "id", "record_ref", "title", "status", "amount_cents", "state",
    "attachment_key", "attachment_sha256", "attachment_bytes", "created_at",
)


def compare_manifests(baseline: dict, current: dict) -> list[str]:
    errors = []
    if not current.get("integrity_pass"):
        errors.append("current manifest reports integrity_pass=false")
    if current.get("drill_id") != baseline.get("drill_id"):
        errors.append("drill_id differs")
    before = baseline.get("database", {})
    after = current.get("database", {})
    for field in ("count", "total_amount_cents", "max_id", "sequence_last_value", "sequence_is_called", "by_status"):
        if before.get(field) != after.get(field):
            errors.append(f"database.{field} differs: baseline={before.get(field)!r} current={after.get(field)!r}")
    before_records = {item["record_ref"]: item for item in before.get("records", [])}
    after_records = {item["record_ref"]: item for item in after.get("records", [])}
    if before_records.keys() != after_records.keys():
        errors.append("record_ref set differs")
    for ref in sorted(before_records.keys() & after_records.keys()):
        for field in FIELDS:
            if before_records[ref].get(field) != after_records[ref].get(field):
                errors.append(f"{ref}.{field} differs")
    if not current.get("objects_ok"):
        errors.append("one or more attachments are missing or have the wrong checksum")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a recovered manifest with the saved baseline.")
    parser.add_argument("--baseline", default="lab017-baseline.json")
    parser.add_argument("--current", required=True, help="JSON response saved from /ops/manifest")
    args = parser.parse_args()
    baseline_doc = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    current_doc = json.loads(Path(args.current).read_text(encoding="utf-8"))
    current = current_doc.get("manifest", current_doc)
    errors = compare_manifests(baseline_doc["manifest"], current)
    if errors:
        print("recovery_gate=FAIL")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("recovery_gate=PASS")
    print(f"records={current['database']['count']} total_amount_cents={current['database']['total_amount_cents']}")
    print(f"sequence_last_value={current['database']['sequence_last_value']} attachments_ok=true")


if __name__ == "__main__":
    main()
