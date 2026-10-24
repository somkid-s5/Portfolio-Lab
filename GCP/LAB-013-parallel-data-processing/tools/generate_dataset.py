#!/usr/bin/env python3
"""Create deterministic, synthetic JSONL shards and a SHA-256 manifest locally."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from lab13.contract import ContractError, RUN_ID_RE, validate_bucket_name, validate_run_id, validate_shard_bytes


def generate(input_bucket: str, run_id: str, shard_count: int, records_per_shard: int,
             output_root: Path, malformed_shard: int | None = None) -> dict[str, Any]:
    validate_bucket_name(input_bucket)
    validate_run_id(run_id)
    if not 1 <= shard_count <= 64:
        raise ContractError("shard_count must be between 1 and 64")
    if not 1 <= records_per_shard <= 10000:
        raise ContractError("records_per_shard must be between 1 and 10000")
    if malformed_shard is not None and not 0 <= malformed_shard < shard_count:
        raise ContractError("malformed_shard must identify a shard in this dataset")
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    shards_dir = run_dir / "shards"
    shards_dir.mkdir()
    entries: list[dict[str, Any]] = []
    for shard_index in range(shard_count):
        lines: list[bytes] = []
        for offset in range(records_per_shard):
            absolute = shard_index * records_per_shard + offset
            record = {
                "sku": f"SKU-{absolute:08d}",
                "units": (absolute % 5) + 1,
                "unit_price_minor": (absolute % 10000) + 100,
            }
            lines.append((json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
        if malformed_shard == shard_index and lines:
            lines[len(lines) // 2] = b'{"sku":"BROKEN","units":\n'
        raw = b"".join(lines)
        relative = Path("shards") / f"shard-{shard_index:05d}.jsonl"
        (run_dir / relative).write_bytes(raw)
        entry = {
            "index": shard_index,
            "uri": f"gs://{input_bucket}/runs/{run_id}/{relative.as_posix()}",
            "record_count": records_per_shard,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if malformed_shard != shard_index:
            validate_shard_bytes(raw, entry)
        entries.append(entry)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "shard_count": shard_count,
        "total_records": shard_count * records_per_shard,
        "records_per_shard": records_per_shard,
        "shards": entries,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                           encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--records-per-shard", type=int, default=1000)
    parser.add_argument("--output-root", type=Path, default=Path("work/input"))
    parser.add_argument("--malformed-shard", type=int)
    args = parser.parse_args()
    try:
        result = generate(args.input_bucket, args.run_id, args.shards, args.records_per_shard,
                          args.output_root, args.malformed_shard)
    except (ContractError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({"run_id": result["run_id"], "shards": result["shard_count"],
                      "records": result["total_records"],
                      "manifest": str(args.output_root / args.run_id / "manifest.json")}, indent=2))


if __name__ == "__main__":
    main()
