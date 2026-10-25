from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class ChangeRequestError(ValueError):
    pass


IDENTITY = re.compile(r"^(user|group):[^\s@]+(?:@[^\s@]+)?$")
REQUEST_ID = re.compile(r"^CR-[A-Z0-9-]{4,24}$")
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
REQUIRED = {
    "request_id",
    "owner",
    "reason",
    "resource_scope",
    "digest",
    "approver",
    "approval_status",
    "approval_reference",
    "created_at",
    "expires_at",
}


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ChangeRequestError(f"{field} must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ChangeRequestError(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ChangeRequestError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def validate_change_request(record: Any, *, now: datetime | None = None) -> dict[str, str]:
    if not isinstance(record, dict):
        raise ChangeRequestError("change request must be a JSON object")
    missing = REQUIRED - record.keys()
    extra = record.keys() - REQUIRED
    if missing:
        raise ChangeRequestError("missing required fields: " + ", ".join(sorted(missing)))
    if extra:
        raise ChangeRequestError("unknown fields: " + ", ".join(sorted(extra)))

    request_id = record["request_id"]
    if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
        raise ChangeRequestError("request_id must look like CR-2026-01")
    owner = record["owner"]
    approver = record["approver"]
    if not isinstance(owner, str) or not IDENTITY.fullmatch(owner):
        raise ChangeRequestError("owner must be a user: or group: principal")
    if not isinstance(approver, str) or not IDENTITY.fullmatch(approver):
        raise ChangeRequestError("approver must be a user: or group: principal")
    if owner == approver:
        raise ChangeRequestError("owner and approver must be different identities")

    reason = record["reason"]
    scope = record["resource_scope"]
    digest = record["digest"]
    if not isinstance(reason, str) or not 20 <= len(reason.strip()) <= 500:
        raise ChangeRequestError("reason must contain 20 to 500 characters")
    if not isinstance(scope, str) or not scope.startswith("projects/") or len(scope) > 240:
        raise ChangeRequestError("resource_scope must identify a specific projects/... resource")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ChangeRequestError("digest must be sha256 followed by 64 lowercase hexadecimal characters")

    approval_status = record["approval_status"]
    if not isinstance(approval_status, str) or approval_status not in {"PENDING", "APPROVED", "REJECTED"}:
        raise ChangeRequestError("approval_status must be PENDING, APPROVED, or REJECTED")
    approval_reference = record["approval_reference"]
    if approval_status == "APPROVED" and (
        not isinstance(approval_reference, str) or not approval_reference.strip()
    ):
        raise ChangeRequestError("an approved request must include its approval evidence reference")
    if approval_status != "APPROVED" and approval_reference not in ("", None):
        raise ChangeRequestError("approval_reference is only valid after approval")

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    created = _timestamp(record["created_at"], "created_at")
    expires = _timestamp(record["expires_at"], "expires_at")
    if created > current + timedelta(minutes=5):
        raise ChangeRequestError("created_at cannot be in the future")
    if expires <= current:
        raise ChangeRequestError("change request has expired")
    if expires <= created or expires - created > timedelta(days=30):
        raise ChangeRequestError("expires_at must be after creation and no more than 30 days later")

    return {
        "request_id": request_id,
        "owner": owner,
        "approver": approver,
        "approval_status": approval_status,
        "digest": digest,
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a bounded Lab 14 change-request record; this never changes Binary Authorization."
    )
    parser.add_argument("request_file", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.request_file.open(encoding="utf-8") as source:
            result = validate_change_request(json.load(source))
    except (OSError, json.JSONDecodeError, ChangeRequestError) as exc:
        print(json.dumps({"result": "invalid", "reason": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps({"result": "valid", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
