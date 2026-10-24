#!/usr/bin/env python3
"""Verify and append immutable input shards, then publish the manifest last."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from lab13.contract import ContractError, parse_manifest_bytes, split_gs_uri, validate_shard_bytes


def _verify_raw(raw: bytes, shard: dict[str, Any], allow_invalid: bool) -> None:
    if allow_invalid:
        if hashlib.sha256(raw).hexdigest() != shard["sha256"]:
            raise ContractError(f"sha256 mismatch for shard {shard['index']}")
        if len(raw.splitlines()) != shard["record_count"]:
            raise ContractError(f"record count mismatch for shard {shard['index']}")
        return
    validate_shard_bytes(raw, shard)


def _append_or_verify(blob: Any, raw: bytes, filename: Path, content_type: str) -> str:
    if blob.exists():
        existing = blob.download_as_bytes()
        if existing != raw:
            raise ContractError(f"existing object {blob.name} differs; do not overwrite it; use a new run_id")
        return "already-present-and-verified"
    try:
        blob.upload_from_filename(str(filename), content_type=content_type, if_generation_match=0)
    except PreconditionFailed:
        existing = blob.download_as_bytes()
        if existing != raw:
            raise ContractError(f"concurrent object {blob.name} differs; do not overwrite it; use a new run_id")
        return "created-concurrently-and-verified"
    return "uploaded"


def upload_dataset(run_dir: Path, input_bucket: str, client: Any | None = None,
                   allow_invalid_shard_index: int | None = None) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    manifest_raw = manifest_path.read_bytes()
    manifest = parse_manifest_bytes(manifest_raw)
    if run_dir.name != manifest["run_id"]:
        raise ContractError("run directory name must match manifest run_id")
    if allow_invalid_shard_index is not None and not 0 <= allow_invalid_shard_index < manifest["shard_count"]:
        raise ContractError("allow-invalid-shard must identify a shard in this manifest")
    if allow_invalid_shard_index is not None and manifest["shard_count"] != 1:
        raise ContractError("invalid-data exercise requires a dedicated one-shard run")
    prepared: list[tuple[dict[str, Any], Path, bytes]] = []
    for shard in sorted(manifest["shards"], key=lambda item: item["index"]):
        bucket_name, object_name = split_gs_uri(shard["uri"])
        if bucket_name != input_bucket:
            raise ContractError("every manifest shard URI must use the selected input bucket")
        local_path = run_dir / "shards" / Path(object_name).name
        raw = local_path.read_bytes()
        _verify_raw(raw, shard, allow_invalid_shard_index == shard["index"])
        prepared.append((shard, local_path, raw))
    client = client or storage.Client()
    bucket = client.bucket(input_bucket)
    uploaded: list[str] = []
    for shard, local_path, raw in prepared:
        _, object_name = split_gs_uri(shard["uri"])
        status = _append_or_verify(bucket.blob(object_name), raw, local_path, "application/x-ndjson")
        uploaded.append(f"{shard['uri']} ({status})")
    manifest_uri = f"gs://{input_bucket}/runs/{manifest['run_id']}/manifest.json"
    _, manifest_object = split_gs_uri(manifest_uri)
    manifest_status = _append_or_verify(bucket.blob(manifest_object), manifest_raw, manifest_path, "application/json")
    return {"run_id": manifest["run_id"], "uploaded_shards": uploaded,
            "manifest_uri": manifest_uri, "manifest_status": manifest_status,
            "records": manifest["total_records"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input-bucket", required=True)
    parser.add_argument("--allow-invalid-shard", type=int,
                        help="intentional permanent-failure exercise; use only with a one-shard disposable run")
    args = parser.parse_args()
    try:
        result = upload_dataset(args.run_dir, args.input_bucket, allow_invalid_shard_index=args.allow_invalid_shard)
    except (ContractError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
