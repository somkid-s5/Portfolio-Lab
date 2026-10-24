"""Cloud Batch task worker. Uses attached Application Default Credentials; never a key."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from google.api_core.exceptions import (
    Aborted,
    DeadlineExceeded,
    InternalServerError,
    ServiceUnavailable,
    TooManyRequests,
)
from google.cloud import storage

from lab13.contract import ContractError, parse_manifest_bytes, split_gs_uri, validate_shard_bytes


TRANSIENT_API_ERRORS = (Aborted, DeadlineExceeded, InternalServerError, ServiceUnavailable, TooManyRequests)
EXIT_PERMANENT = 65
EXIT_TRANSIENT = 75
EXIT_UNEXPECTED = 70


def emit(event: str, **fields: Any) -> None:
    print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **fields},
                     sort_keys=True), flush=True)


def run_task(env: dict[str, str] | None = None, client: Any | None = None) -> int:
    env = env or os.environ
    try:
        manifest_uri = env["INPUT_MANIFEST_URI"]
        output_bucket_name = env["ATTEMPT_OUTPUT_BUCKET"]
        try:
            task_index = int(env["BATCH_TASK_INDEX"])
            task_count = int(env["BATCH_TASK_COUNT"])
            attempt = int(env.get("BATCH_TASK_RETRY_ATTEMPT", "0"))
        except (KeyError, ValueError) as exc:
            raise ContractError(f"Batch task environment is incomplete or invalid: {exc}") from exc
        if task_index < 0 or task_count < 1 or attempt not in (0, 1):
            raise ContractError("task index/count are invalid or retry attempt exceeds the one-retry lab limit")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", output_bucket_name):
            raise ContractError("ATTEMPT_OUTPUT_BUCKET is not a valid bucket name")
        client = client or storage.Client()
        manifest_bucket_name, manifest_object_name = split_gs_uri(manifest_uri)
        manifest_blob = client.bucket(manifest_bucket_name).blob(manifest_object_name)
        manifest_raw = manifest_blob.download_as_bytes()
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        manifest = parse_manifest_bytes(manifest_raw)
        if task_count != manifest["shard_count"]:
            raise ContractError("BATCH_TASK_COUNT does not match manifest shard_count")
        if task_index >= manifest["shard_count"]:
            raise ContractError("BATCH_TASK_INDEX is outside manifest shard indexes")
        shard = manifest["shards"][task_index]
        run_id = manifest["run_id"]
        common = {"run_id": run_id, "task_index": task_index, "shard_index": shard["index"],
                  "attempt": attempt, "manifest_sha256": manifest_sha256}
        fail_index = env.get("LAB13_FAIL_ONCE_INDEX", "")
        if fail_index:
            if not fail_index.isdigit() or int(fail_index) >= manifest["shard_count"]:
                raise ContractError("LAB13_FAIL_ONCE_INDEX must identify a shard in this manifest")
            if task_index == int(fail_index) and attempt == 0:
                emit("transient_fault_injected", **common, exit_code=EXIT_TRANSIENT)
                return EXIT_TRANSIENT
        input_bucket_name, input_object_name = split_gs_uri(shard["uri"])
        input_raw = client.bucket(input_bucket_name).blob(input_object_name).download_as_bytes()
        totals = validate_shard_bytes(input_raw, shard)
        result = {
            "schema_version": 1,
            "run_id": run_id,
            "task_index": task_index,
            "shard_index": shard["index"],
            "attempt": attempt,
            "manifest_sha256": manifest_sha256,
            "input_uri": shard["uri"],
            "input_sha256": shard["sha256"],
            **totals,
        }
        result_raw = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        output_object_name = f"runs/{run_id}/shards/{task_index:05d}/attempt-{attempt}/result.json"
        output_blob = client.bucket(output_bucket_name).blob(output_object_name)
        output_blob.upload_from_string(result_raw, content_type="application/json", if_generation_match=0)
        emit("shard_succeeded", **common, input_uri=shard["uri"],
             input_bytes=len(input_raw), output_uri=f"gs://{output_bucket_name}/{output_object_name}",
             record_count=totals["record_count"], units_total=totals["units_total"],
             value_minor_total=totals["value_minor_total"], result="success")
        return 0
    except ContractError as exc:
        emit("shard_rejected", reason=str(exc), exit_code=EXIT_PERMANENT,
             task_index=env.get("BATCH_TASK_INDEX"), attempt=env.get("BATCH_TASK_RETRY_ATTEMPT", "0"))
        return EXIT_PERMANENT
    except TRANSIENT_API_ERRORS as exc:
        emit("transient_storage_error", error_type=type(exc).__name__, reason=str(exc),
             task_index=env.get("BATCH_TASK_INDEX"), attempt=env.get("BATCH_TASK_RETRY_ATTEMPT", "0"),
             exit_code=EXIT_TRANSIENT)
        return EXIT_TRANSIENT
    except Exception as exc:  # PermissionDenied, precondition errors, and programming errors are not retryable.
        emit("worker_unexpected_failure", error_type=type(exc).__name__, reason=str(exc),
             task_index=env.get("BATCH_TASK_INDEX"), attempt=env.get("BATCH_TASK_RETRY_ATTEMPT", "0"),
             exit_code=EXIT_UNEXPECTED)
        return EXIT_UNEXPECTED


def main() -> None:
    raise SystemExit(run_task())


if __name__ == "__main__":
    main()
