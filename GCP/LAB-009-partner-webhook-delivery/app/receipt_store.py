"""Create-only Cloud Storage receipts with explicit duplicate comparison."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from typing import Any
import uuid

from google.api_core.exceptions import PreconditionFailed


_HASH = re.compile(r"^[0-9a-f]{64}$")
_PARTNER_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$")


@dataclass(frozen=True)
class ReceiptWriteResult:
    outcome: str
    object_name: str


class CloudStorageReceiptStore:
    """Persist only receipt metadata; never store webhook body or HMAC."""

    def __init__(self, bucket_name: str, *, client: Any, timeout_seconds: float = 10.0):
        if not isinstance(bucket_name, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", bucket_name
        ):
            raise ValueError("bucket_name is invalid")
        self._bucket = client.bucket(bucket_name)
        self._timeout = timeout_seconds

    def create_or_compare(
        self,
        *,
        partner_id: str,
        event_id: str,
        payload_sha256: str,
        received_at: datetime,
        attempt_number: int,
    ) -> ReceiptWriteResult:
        if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id):
            raise ValueError("partner_id is invalid")
        try:
            parsed_event = uuid.UUID(event_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("event_id is invalid") from exc
        if str(parsed_event) != event_id:
            raise ValueError("event_id must be lowercase UUID")
        if not isinstance(payload_sha256, str) or not _HASH.fullmatch(payload_sha256):
            raise ValueError("payload_sha256 is invalid")
        if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or not 1 <= attempt_number <= 5:
            raise ValueError("attempt_number must be between 1 and 5")
        if not isinstance(received_at, datetime) or received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        if received_at.utcoffset() != timezone.utc.utcoffset(received_at):
            raise ValueError("received_at must be UTC")

        object_name = f"events/{partner_id}/{event_id}.json"
        receipt = {
            "event_id": event_id,
            "partner_id": partner_id,
            "payload_sha256": payload_sha256,
            "first_received_at": received_at.astimezone(timezone.utc).isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "first_attempt_number": attempt_number,
        }
        body = json.dumps(
            receipt,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        blob = self._bucket.blob(object_name)
        try:
            blob.upload_from_string(
                body,
                content_type="application/json",
                if_generation_match=0,
                timeout=self._timeout,
            )
            return ReceiptWriteResult("created", object_name)
        except PreconditionFailed:
            existing_blob = self._bucket.blob(object_name)
            existing_blob.reload(timeout=self._timeout)
            existing_body = existing_blob.download_as_bytes(timeout=self._timeout)
            try:
                existing = json.loads(existing_body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return ReceiptWriteResult("conflict", object_name)
            if (
                isinstance(existing, dict)
                and existing.get("event_id") == event_id
                and existing.get("partner_id") == partner_id
                and existing.get("payload_sha256") == payload_sha256
                and isinstance(existing.get("first_received_at"), str)
                and type(existing.get("first_attempt_number")) is int
            ):
                return ReceiptWriteResult("duplicate", object_name)
            return ReceiptWriteResult("conflict", object_name)
