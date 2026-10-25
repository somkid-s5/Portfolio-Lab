"""Manifest and synthetic-record contracts shared by Lab 13 tools and workers."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


RUN_ID_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_SHARDS = 64
MAX_RECORDS_PER_SHARD = 10_000


class ContractError(ValueError):
    """Input or manifest violates the versioned Lab 13 data contract."""


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ContractError("run_id must be 3-40 lowercase letters, digits, or hyphens and start with a letter")
    return run_id


def validate_bucket_name(bucket: str) -> str:
    if not BUCKET_RE.fullmatch(bucket) or ".." in bucket or len(bucket) > 63:
        raise ContractError("bucket name is not a valid 3-63 character Cloud Storage bucket name")
    return bucket


def split_gs_uri(uri: str) -> tuple[str, str]:
    if not isinstance(uri, str) or not uri.startswith("gs://"):
        raise ContractError("expected a gs:// URI")
    remainder = uri[5:]
    bucket, separator, object_name = remainder.partition("/")
    validate_bucket_name(bucket)
    if not separator or not object_name or object_name.startswith("/") or "\x00" in object_name:
        raise ContractError("gs:// URI must include a bucket and object path")
    return bucket, object_name


def parse_manifest_bytes(raw: bytes, expected_run_id: str | None = None) -> dict[str, Any]:
    try:
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"manifest is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ContractError("manifest schema_version must be integer 1")
    run_id_value = manifest.get("run_id")
    if not isinstance(run_id_value, str):
        raise ContractError("manifest run_id must be a string")
    run_id = validate_run_id(run_id_value)
    if expected_run_id and run_id != expected_run_id:
        raise ContractError("manifest run_id does not match the requested run")
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not 1 <= len(shards) <= MAX_SHARDS:
        raise ContractError(f"manifest must contain between 1 and {MAX_SHARDS} shards")
    if type(manifest.get("shard_count")) is not int or manifest["shard_count"] != len(shards):
        raise ContractError("manifest shard_count does not match shards")
    records_per_shard = manifest.get("records_per_shard")
    if type(records_per_shard) is not int or not 1 <= records_per_shard <= MAX_RECORDS_PER_SHARD:
        raise ContractError(f"records_per_shard must be between 1 and {MAX_RECORDS_PER_SHARD}")
    indexes: list[int] = []
    total_records = 0
    seen_uris: set[str] = set()
    input_bucket: str | None = None
    for shard in shards:
        if not isinstance(shard, dict):
            raise ContractError("each shard entry must be an object")
        index = shard.get("index")
        count = shard.get("record_count")
        uri = shard.get("uri")
        digest = shard.get("sha256")
        if type(index) is not int or index < 0:
            raise ContractError("shard index must be a non-negative integer")
        if type(count) is not int or count != records_per_shard:
            raise ContractError("each shard record_count must equal records_per_shard")
        if not isinstance(uri, str):
            raise ContractError("shard uri must be a string")
        bucket, object_name = split_gs_uri(uri)
        if input_bucket is None:
            input_bucket = bucket
        if bucket != input_bucket:
            raise ContractError("all shard URIs must use the same input bucket")
        if object_name != f"runs/{run_id}/shards/shard-{index:05d}.jsonl":
            raise ContractError(f"shard {index} URI must follow the immutable run/shard path")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ContractError("shard sha256 must be 64 lowercase hexadecimal characters")
        if uri in seen_uris:
            raise ContractError("shard URIs must be unique")
        seen_uris.add(uri)
        indexes.append(index)
        total_records += count
    if indexes != list(range(len(shards))):
        raise ContractError("shards must be ordered by contiguous index starting at zero")
    if type(manifest.get("total_records")) is not int or manifest["total_records"] != total_records:
        raise ContractError("manifest total_records does not equal the sum of shard record_count values")
    return manifest


def validate_shard_bytes(raw: bytes, shard: dict[str, Any]) -> dict[str, int]:
    digest = hashlib.sha256(raw).hexdigest()
    if digest != shard["sha256"]:
        raise ContractError(f"sha256 mismatch for shard {shard['index']}")
    lines = raw.splitlines()
    if len(lines) != shard["record_count"]:
        raise ContractError(f"record count mismatch for shard {shard['index']}")
    units_total = 0
    value_minor_total = 0
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise ContractError(f"blank JSONL line at {line_number}")
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"malformed JSONL at line {line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ContractError(f"record at line {line_number} must be a JSON object")
        sku = record.get("sku")
        units = record.get("units")
        unit_price_minor = record.get("unit_price_minor")
        if not isinstance(sku, str) or not re.fullmatch(r"SKU-[0-9]{8}", sku):
            raise ContractError(f"invalid sku at line {line_number}")
        if type(units) is not int or units < 1 or units > 20:
            raise ContractError(f"units must be an integer from 1 to 20 at line {line_number}")
        if type(unit_price_minor) is not int or unit_price_minor < 1 or unit_price_minor > 100000000:
            raise ContractError(f"unit_price_minor must be a positive integer at line {line_number}")
        units_total += units
        value_minor_total += units * unit_price_minor
    return {"record_count": len(lines), "units_total": units_total, "value_minor_total": value_minor_total}
