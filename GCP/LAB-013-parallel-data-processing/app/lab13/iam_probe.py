"""Verify the Batch runtime identity cannot create objects in protected buckets."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import Forbidden
from google.cloud import storage

from lab13.contract import validate_bucket_name, validate_run_id


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                     sort_keys=True), flush=True)


def probe_bucket(client: Any, bucket_name: str, probe_id: str) -> bool:
    """Return True when the expected permission denial is observed."""
    object_name = f"__lab13-iam-probes__/{probe_id}/must-not-exist.json"
    blob = client.bucket(bucket_name).blob(object_name)
    try:
        blob.upload_from_string(b'{"probe":"lab13"}', content_type="application/json",
                                if_generation_match=0)
    except Forbidden:
        emit("iam_denied_expected", bucket=bucket_name, permission="storage.objects.create",
             probe_object=object_name, result="denied")
        return True
    emit("iam_denied_missing", bucket=bucket_name, permission="storage.objects.create",
         probe_object=object_name, result="unexpectedly-created")
    return False


def run(input_bucket: str, published_bucket: str, probe_id: str, client: Any | None = None) -> int:
    validate_bucket_name(input_bucket)
    validate_bucket_name(published_bucket)
    validate_run_id(probe_id)
    if input_bucket == published_bucket:
        raise ValueError("input and published buckets must be separate")
    client = client or storage.Client()
    results = {
        "input": probe_bucket(client, input_bucket, probe_id),
        "published_manifest": probe_bucket(client, published_bucket, probe_id),
    }
    if all(results.values()):
        emit("iam_boundary_verified", probe_id=probe_id, checks=results, result="pass")
        return 0
    emit("iam_boundary_violation", probe_id=probe_id, checks=results, result="fail",
         cleanup_prefixes=[
             f"gs://{input_bucket}/__lab13-iam-probes__/{probe_id}/",
             f"gs://{published_bucket}/__lab13-iam-probes__/{probe_id}/",
         ])
    return 66


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bucket", required=True)
    parser.add_argument("--published-bucket", required=True)
    parser.add_argument("--probe-id", required=True)
    args = parser.parse_args()
    try:
        code = run(args.input_bucket, args.published_bucket, args.probe_id)
    except Exception as exc:
        emit("iam_probe_error", error_type=type(exc).__name__, reason=str(exc), exit_code=70)
        code = 70
    raise SystemExit(code)


if __name__ == "__main__":
    main()
