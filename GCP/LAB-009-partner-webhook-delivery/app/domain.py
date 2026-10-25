"""Pure domain contracts for Lab 09 Partner Webhook Relay.

This module deliberately has no Google Cloud SDK dependency. Cloud adapters are
added in separate modules and must preserve these contracts.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any, Mapping, Sequence


MAX_REQUEST_BYTES = 8 * 1024
MAX_CANONICAL_EVENT_BYTES = 8 * 1024
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
EVENT_TYPE = "order.shipped"
SCHEMA_VERSION = 1
SIGNATURE_WINDOW_SECONDS = 300
MAX_RETRY_AFTER_SECONDS = 60

_REQUIRED_SUBMISSION_FIELDS = {
    "partner_id",
    "order_ref",
    "occurred_at",
    "shipping_status",
}
_PARTNER_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$")
_ORDER_REF = re.compile(r"^ORD-[A-Z0-9]{8}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


class ValidationError(ValueError):
    """Raised when an input violates the Lab 09 event contract."""


class ReceiptConflict(ValueError):
    """Raised when one event ID is reused with a different payload hash."""


def _utc_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValidationError(f"{field} must be timezone-aware")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValidationError(f"{field} must use UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: str, field: str) -> str:
    if not isinstance(value, str) or not _RFC3339.fullmatch(value):
        raise ValidationError(f"{field} must be RFC3339 with a timezone")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValidationError(f"{field} is not a valid timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValidationError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _reject_json_constant(value: str) -> None:
    raise ValidationError(f"non-finite JSON number is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_submission(raw_body: bytes, allowed_partners: Sequence[str]) -> dict[str, str]:
    """Parse bounded UTF-8 JSON, reject duplicate/unknown fields, then normalize."""
    if not isinstance(raw_body, bytes):
        raise ValidationError("request body must be bytes")
    if not raw_body or len(raw_body) > MAX_REQUEST_BYTES:
        raise ValidationError(f"request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
    try:
        value = json.loads(
            raw_body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValidationError("request body must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValidationError("request body must be a JSON object")
    if set(value) != _REQUIRED_SUBMISSION_FIELDS:
        missing = sorted(_REQUIRED_SUBMISSION_FIELDS - set(value))
        extra = sorted(set(value) - _REQUIRED_SUBMISSION_FIELDS)
        raise ValidationError(f"submission fields mismatch; missing={missing}, extra={extra}")

    partner_id = value["partner_id"]
    if (
        not isinstance(partner_id, str)
        or not _PARTNER_ID.fullmatch(partner_id)
        or partner_id not in set(allowed_partners)
    ):
        raise ValidationError("partner_id is not in the configured allowlist")

    order_ref = value["order_ref"]
    if not isinstance(order_ref, str) or not _ORDER_REF.fullmatch(order_ref):
        raise ValidationError("order_ref must match ORD- plus 8 uppercase letters/digits")

    if value["shipping_status"] != "shipped":
        raise ValidationError("shipping_status must be shipped")

    return {
        "partner_id": partner_id,
        "order_ref": order_ref,
        "occurred_at": _timestamp(value["occurred_at"], "occurred_at"),
        "shipping_status": "shipped",
    }


def build_event(
    normalized_submission: Mapping[str, str],
    *,
    event_id: str,
    accepted_at: datetime,
) -> dict[str, Any]:
    """Add server-owned fields and return the canonical event object."""
    if set(normalized_submission) != _REQUIRED_SUBMISSION_FIELDS:
        raise ValidationError("normalized submission has unexpected fields")
    if not isinstance(event_id, str) or not _UUID.fullmatch(event_id):
        raise ValidationError("event_id must be a UUID")
    accepted = _utc_datetime(accepted_at, "accepted_at")
    event = {
        "accepted_at": accepted.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "event_id": event_id.lower(),
        "event_type": EVENT_TYPE,
        "occurred_at": _timestamp(normalized_submission["occurred_at"], "occurred_at"),
        "order_ref": normalized_submission["order_ref"],
        "partner_id": normalized_submission["partner_id"],
        "schema_version": SCHEMA_VERSION,
        "shipping_status": "shipped",
    }
    # Validate once more at the serialization boundary; no caller-supplied extras pass through.
    canonical_event_bytes(event)
    return event


def canonical_event_bytes(event: Mapping[str, Any]) -> bytes:
    """Compact deterministic UTF-8 JSON for the exact event field set."""
    required = {
        "accepted_at", "event_id", "event_type", "occurred_at", "order_ref",
        "partner_id", "schema_version", "shipping_status",
    }
    if set(event) != required:
        raise ValidationError("canonical event has unexpected fields")
    if event["event_type"] != EVENT_TYPE or type(event["schema_version"]) is not int or event["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("unsupported event type or schema version")
    if event["shipping_status"] != "shipped":
        raise ValidationError("shipping_status must be shipped")
    if not isinstance(event["event_id"], str) or not _UUID.fullmatch(event["event_id"]) or event["event_id"] != event["event_id"].lower():
        raise ValidationError("event_id must be a lowercase UUID")
    if not isinstance(event["partner_id"], str) or not _PARTNER_ID.fullmatch(event["partner_id"]):
        raise ValidationError("partner_id is invalid")
    if not isinstance(event["order_ref"], str) or not _ORDER_REF.fullmatch(event["order_ref"]):
        raise ValidationError("order_ref is invalid")
    if _timestamp(event["accepted_at"], "accepted_at") != event["accepted_at"]:
        raise ValidationError("accepted_at must be normalized UTC with six fractional digits")
    if _timestamp(event["occurred_at"], "occurred_at") != event["occurred_at"]:
        raise ValidationError("occurred_at must be normalized UTC with six fractional digits")
    encoded = json.dumps(
        dict(event),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_EVENT_BYTES:
        raise ValidationError("canonical event exceeds the byte limit")
    return encoded


def validate_idempotency_key(value: str) -> str:
    if not isinstance(value, str) or not _IDEMPOTENCY_KEY.fullmatch(value):
        raise ValidationError("Idempotency-Key must be 16–128 safe ASCII characters")
    return value


def idempotency_document_id(value: str) -> str:
    key = validate_idempotency_key(value)
    return hashlib.sha256(key.encode("ascii")).hexdigest()


def payload_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def delivery_id(event_id: str, partner_id: str) -> str:
    if not isinstance(event_id, str) or not _UUID.fullmatch(event_id):
        raise ValidationError("event_id must be a UUID")
    if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id):
        raise ValidationError("invalid partner identifier")
    return hashlib.sha256(f"{event_id.lower()}:{partner_id}".encode("utf-8")).hexdigest()


def task_id(delivery: str, generation: int) -> str:
    if not isinstance(delivery, str) or not _SHA256_HEX.fullmatch(delivery):
        raise ValidationError("delivery_id must be a lowercase SHA-256 hex value")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValidationError("generation must be a positive integer")
    digest = hashlib.sha256(delivery.encode("utf-8")).hexdigest()[:32]
    return f"d-{digest}-g{generation}"


def task_resource_name(project: str, location: str, queue: str, delivery: str, generation: int) -> str:
    for name, value in (("project", project), ("location", location), ("queue", queue)):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValidationError(f"invalid {name}")
    return f"projects/{project}/locations/{location}/queues/{queue}/tasks/{task_id(delivery, generation)}"


def task_payload(event: Mapping[str, Any], delivery: str, generation: int) -> dict[str, Any]:
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValidationError("generation must be a positive integer")
    if not isinstance(event, Mapping):
        raise ValidationError("event must be a mapping")
    event_id = event.get("event_id")
    partner_id = event.get("partner_id")
    if not isinstance(event_id, str) or not _UUID.fullmatch(event_id):
        raise ValidationError("event_id must be a UUID")
    if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id):
        raise ValidationError("partner_id is invalid")
    if delivery != delivery_id(event_id, partner_id):
        raise ValidationError("delivery_id does not match the event")
    return {
        "delivery_id": delivery,
        "event_id": event_id.lower(),
        "generation": generation,
        "partner_id": partner_id,
    }


def webhook_signing_bytes(
    raw_body: bytes,
    *,
    partner_id: str,
    timestamp: int,
    generation: int,
    attempt_number: int,
) -> bytes:
    if not _PARTNER_ID.fullmatch(partner_id):
        raise ValidationError("invalid partner_id")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
        raise ValidationError("timestamp must be a nonnegative Unix integer")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValidationError("generation must be positive")
    if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 1:
        raise ValidationError("attempt_number must be positive")
    if not isinstance(raw_body, bytes):
        raise ValidationError("raw_body must be bytes")
    prefix = (
        f"v1\nPOST\n/v1/webhooks/{partner_id}\n{timestamp}\n"
        f"{generation}\n{attempt_number}\n"
    ).encode("ascii")
    return prefix + raw_body


def sign_webhook(
    secret: bytes,
    raw_body: bytes,
    *,
    partner_id: str,
    timestamp: int,
    generation: int,
    attempt_number: int,
) -> str:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValidationError("HMAC secret must contain at least 32 bytes")
    message = webhook_signing_bytes(
        raw_body,
        partner_id=partner_id,
        timestamp=timestamp,
        generation=generation,
        attempt_number=attempt_number,
    )
    return "v1=" + hmac.new(secret, message, hashlib.sha256).hexdigest()


def verify_webhook(
    secret: bytes,
    raw_body: bytes,
    signature: str,
    *,
    partner_id: str,
    timestamp: int,
    generation: int,
    attempt_number: int,
    now: int,
    window_seconds: int = SIGNATURE_WINDOW_SECONDS,
) -> bool:
    if (
        not isinstance(now, int) or isinstance(now, bool)
        or not isinstance(timestamp, int) or isinstance(timestamp, bool)
        or not isinstance(window_seconds, int) or isinstance(window_seconds, bool)
        or window_seconds < 1
    ):
        return False
    if abs(now - timestamp) > window_seconds:
        return False
    try:
        expected = sign_webhook(
            secret,
            raw_body,
            partner_id=partner_id,
            timestamp=timestamp,
            generation=generation,
            attempt_number=attempt_number,
        )
    except (ValidationError, TypeError):
        return False
    return isinstance(signature, str) and hmac.compare_digest(expected, signature)


def classify_partner_status(status_code: int) -> str:
    if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
        raise ValidationError("HTTP status code must be between 100 and 599")
    if 200 <= status_code <= 299:
        return "success"
    if status_code in (408, 429) or status_code >= 500:
        return "transient"
    return "permanent"


def retry_after_seconds(headers: Mapping[str, str], *, cap: int = MAX_RETRY_AFTER_SECONDS) -> int | None:
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValidationError("Retry-After cap must be a positive integer")
    if not isinstance(headers, Mapping):
        raise ValidationError("headers must be a mapping")
    value = next((v for k, v in headers.items() if isinstance(k, str) and k.lower() == "retry-after"), None)
    if not isinstance(value, str) or not value.strip().isdigit():
        return None
    return min(max(int(value.strip()), 1), cap)


def compare_receipt(existing_hash: str, incoming_hash: str) -> str:
    if (
        not isinstance(existing_hash, str) or not _SHA256_HEX.fullmatch(existing_hash)
        or not isinstance(incoming_hash, str) or not _SHA256_HEX.fullmatch(incoming_hash)
    ):
        raise ValidationError("receipt hashes must be lowercase SHA-256 hex")
    if hmac.compare_digest(existing_hash, incoming_hash):
        return "duplicate"
    raise ReceiptConflict("event ID already exists with a different payload hash")
