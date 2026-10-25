"""Bounded Cloud Shell inspection, receipt lookup and audited redrive commands."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import re
import sys
from typing import Any
import uuid

from google.api_core.exceptions import GoogleAPICallError, NotFound
from google.cloud import firestore, storage

from app.domain import ValidationError
from app.ledger import FirestoreLedger, LedgerInvariantError


_HASH = re.compile(r"^[0-9a-f]{64}$")
_PARTNER = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$")
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")


def inspect_delivery(ledger: Any, delivery_id: str) -> dict[str, Any] | None:
    """Return an allowlisted operational projection; never expose event bytes."""
    record = ledger.get_delivery(delivery_id)
    if record is None:
        return None
    fields = (
        "event_id",
        "partner_id",
        "generation",
        "status",
        "task_name",
        "attempt_count",
        "last_attempt_outcome",
        "last_http_status",
        "last_error_code",
        "enqueue_attempts",
        "last_enqueue_error",
        "review_required",
        "review_reason",
        "redrive_count",
        "last_redrive_at",
        "last_redrive_actor",
        "last_redrive_reason",
        "created_at",
        "updated_at",
    )
    return {key: record[key] for key in fields if key in record}


def read_receipt(
    client: Any,
    *,
    bucket_name: str,
    partner_id: str,
    event_id: str,
) -> dict[str, Any] | None:
    """Read only the synthetic receipt fields for one exact partner/event key."""
    if not isinstance(bucket_name, str) or not _BUCKET.fullmatch(bucket_name):
        raise ValidationError("receipt bucket name is invalid")
    if not isinstance(partner_id, str) or not _PARTNER.fullmatch(partner_id):
        raise ValidationError("partner ID is invalid")
    try:
        parsed_event_id = uuid.UUID(event_id)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError("event ID must be a UUID") from exc
    if str(parsed_event_id) != event_id:
        raise ValidationError("event ID must be a lowercase UUID")

    blob = client.bucket(bucket_name).blob(f"events/{partner_id}/{event_id}.json")
    try:
        raw = blob.download_as_bytes(timeout=10)
    except NotFound:
        return None
    try:
        record = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("stored receipt is not valid JSON") from exc
    if (
        not isinstance(record, dict)
        or record.get("event_id") != event_id
        or record.get("partner_id") != partner_id
        or not isinstance(record.get("payload_sha256"), str)
        or not _HASH.fullmatch(record["payload_sha256"])
        or not isinstance(record.get("first_received_at"), str)
        or type(record.get("first_attempt_number")) is not int
    ):
        raise ValueError("stored receipt does not match the requested event")
    return {
        "event_id": event_id,
        "partner_id": partner_id,
        "payload_sha256": record["payload_sha256"],
        "first_received_at": record["first_received_at"],
        "first_attempt_number": record["first_attempt_number"],
    }


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return str(value)


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=_json_default))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect Lab 09 synthetic delivery evidence from Cloud Shell."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="show a redacted delivery summary")
    inspect.add_argument("--project", required=True)
    inspect.add_argument("--delivery-id", required=True)

    receipt = commands.add_parser("receipt", help="look up one partner receipt")
    receipt.add_argument("--project", required=True)
    receipt.add_argument("--bucket", required=True)
    receipt.add_argument("--partner-id", required=True)
    receipt.add_argument("--event-id", required=True)

    redrive = commands.add_parser("redrive", help="audited new-generation retry")
    redrive.add_argument("--project", required=True)
    redrive.add_argument("--region", default="asia-southeast1")
    redrive.add_argument("--delivery-id", required=True)
    redrive.add_argument("--actor-email", required=True)
    redrive.add_argument("--reason", required=True)
    redrive.add_argument("--evidence-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_delivery(
                FirestoreLedger(firestore.Client(project=args.project)),
                args.delivery_id,
            )
            if result is None:
                print("delivery_not_found", file=sys.stderr)
                return 4
            _print_json(result)
            return 0

        if args.command == "receipt":
            result = read_receipt(
                storage.Client(project=args.project),
                bucket_name=args.bucket,
                partner_id=args.partner_id,
                event_id=args.event_id,
            )
            if result is None:
                print(
                    "receipt_missing: this does not prove the partner did not receive the request",
                    file=sys.stderr,
                )
                return 4
            _print_json(result)
            return 0

        result = FirestoreLedger(
            firestore.Client(project=args.project)
        ).redrive(
            args.delivery_id,
            project_id=args.project,
            location_id=args.region,
            actor_email=args.actor_email,
            reason=args.reason,
            evidence_ref=args.evidence_ref,
        )
        _print_json(result)
        print(
            "redrive_recorded: delivery is enqueue_pending; the Reconciler will create "
            "the new task. Review the receipt first for unknown outcomes.",
            file=sys.stderr,
        )
        return 0
    except (ValidationError, LedgerInvariantError, ValueError) as exc:
        print(f"operation_rejected error_type={type(exc).__name__}", file=sys.stderr)
        return 2
    except GoogleAPICallError as exc:
        print(f"cloud_request_failed error_type={type(exc).__name__}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
