from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def build_report(incident: str, restore_point: str, validated_at: str) -> dict:
    incident_dt = parse_utc(incident)
    restore_dt = parse_utc(restore_point)
    validated_dt = parse_utc(validated_at)
    if restore_dt > incident_dt:
        raise ValueError("restore point cannot be later than incident time")
    if validated_dt < incident_dt:
        raise ValueError("validation time cannot precede incident time")
    rpo = (incident_dt - restore_dt).total_seconds()
    rto = (validated_dt - incident_dt).total_seconds()
    return {
        "incident_at_utc": incident_dt.isoformat().replace("+00:00", "Z"),
        "restore_point_utc": restore_dt.isoformat().replace("+00:00", "Z"),
        "validated_at_utc": validated_dt.isoformat().replace("+00:00", "Z"),
        "observed_rpo_seconds": rpo,
        "observed_rto_seconds": rto,
        "rpo_target_seconds": 300,
        "rto_target_seconds": 1800,
        "rpo_target_met": rpo <= 300,
        "rto_target_met": rto <= 1800,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calculate measured RPO and RTO; it does not predict service guarantees.")
    parser.add_argument("--incident-at", required=True)
    parser.add_argument("--restore-point", required=True)
    parser.add_argument("--validated-at", required=True)
    parser.add_argument("--output", default="lab017-recovery-measurement.json")
    args = parser.parse_args()
    report = build_report(args.incident_at, args.restore_point, args.validated_at)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
