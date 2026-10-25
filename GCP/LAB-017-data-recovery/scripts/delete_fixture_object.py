from __future__ import annotations

import argparse
import json
import subprocess

DRILL_ID = "LAB017-DRILL-01"


def exact_fixture_uri(baseline_path: str, bucket: str, record_ref: str) -> tuple[str, int]:
    with open(baseline_path, encoding="utf-8") as source:
        baseline = json.load(source)
    manifest = baseline["manifest"]
    if manifest["drill_id"] != DRILL_ID or baseline["drill_id"] != DRILL_ID:
        raise ValueError("baseline is not the Lab 17 fixed fixture set")
    record = next((r for r in manifest["database"]["records"] if r["record_ref"] == record_ref), None)
    if record is None:
        raise ValueError(f"fixture not found: {record_ref}")
    expected_prefix = f"records/{DRILL_ID}/{record_ref}/"
    key = record["attachment_key"]
    if not key.startswith(expected_prefix) or "/" in key[len(expected_prefix):]:
        raise ValueError("refusing a non-fixture object path")
    if not record.get("attachment_generation"):
        raise ValueError("baseline has no live object generation")
    return f"gs://{bucket}/{key}", int(record["attachment_generation"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete exactly one Lab 17 fixture attachment for the recovery drill.")
    parser.add_argument("--baseline", default="lab017-baseline.json")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--record-ref", default="LAB017-REC-003")
    parser.add_argument("--execute", action="store_true", help="required to perform the one-object deletion")
    args = parser.parse_args()
    uri, generation = exact_fixture_uri(args.baseline, args.bucket, args.record_ref)
    print(f"target={uri} generation={generation}")
    if not args.execute:
        print("dry_run=true; review the exact object path, then rerun with --execute")
        return
    subprocess.run(
        ["gcloud", "storage", "rm", f"--if-generation-match={generation}", uri],
        check=True,
    )
    print("object_delete_requested=true")


if __name__ == "__main__":
    main()
