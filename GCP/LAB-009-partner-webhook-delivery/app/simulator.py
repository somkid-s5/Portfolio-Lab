"""HMAC-verifying partner simulator and bounded deterministic fault modes."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

from app.domain import (
    ValidationError,
    canonical_event_bytes,
    payload_sha256,
    verify_webhook,
)


FAULT_MODES = frozenset({
    "normal",
    "transient-503-first-two",
    "permanent-400",
    "accept-then-503-on-first",
})
_HEADER_INT = re.compile(r"^(0|[1-9][0-9]{0,12})$")


class PartnerSimulator:
    """Dependency-free HTTP handler core; fault mode is deployment config only."""

    def __init__(
        self,
        *,
        partner_id: str,
        secret: bytes,
        receipt_store: Any,
        fault_mode: str = "normal",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(partner_id, str) or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?", partner_id
        ):
            raise ValidationError("partner_id is invalid")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValidationError("simulator HMAC secret must be at least 32 bytes")
        if fault_mode not in FAULT_MODES:
            raise ValidationError("fault_mode is not in the fixed simulator allowlist")
        self._partner = partner_id
        self._secret = secret
        self._receipts = receipt_store
        self._fault_mode = fault_mode
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def partner_id(self) -> str:
        return self._partner

    def receive(self, raw_body: bytes, headers: Any) -> tuple[int, dict[str, str], dict[str, str]]:
        if not isinstance(raw_body, bytes) or not 1 <= len(raw_body) <= 8192:
            return 413, {}, {"error": "payload_size_invalid"}
        try:
            event = json.loads(raw_body)
            canonical = canonical_event_bytes(event)
        except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
            return 400, {}, {"error": "invalid_event"}
        if canonical != raw_body:
            return 400, {}, {"error": "noncanonical_event"}
        event_id = event["event_id"]
        if event["partner_id"] != self._partner or headers.get("X-Event-ID") != event_id:
            return 400, {}, {"error": "event_identity_invalid"}

        timestamp = self._parse_header_int(headers.get("X-Webhook-Timestamp"))
        generation = self._parse_header_int(headers.get("X-Webhook-Generation"))
        attempt = self._parse_header_int(headers.get("X-Webhook-Attempt"))
        if timestamp is None or generation is None or generation < 1 or attempt is None or not 1 <= attempt <= 5:
            return 401, {}, {"error": "signature_invalid"}
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            return 503, {}, {"error": "simulator_clock_unavailable"}
        signature = headers.get("X-Webhook-Signature", "")
        if not verify_webhook(
            self._secret,
            raw_body,
            signature,
            partner_id=self._partner,
            timestamp=timestamp,
            generation=generation,
            attempt_number=attempt,
            now=int(now.timestamp()),
        ):
            return 401, {}, {"error": "signature_invalid"}

        if self._fault_mode == "permanent-400":
            return 400, {}, {"error": "simulated_permanent_rejection"}
        if self._fault_mode == "transient-503-first-two" and attempt <= 2:
            return 503, {"Retry-After": "5"}, {"error": "simulated_transient_failure"}

        try:
            result = self._receipts.create_or_compare(
                partner_id=self._partner,
                event_id=event_id,
                payload_sha256=payload_sha256(raw_body),
                received_at=now.astimezone(timezone.utc),
                attempt_number=attempt,
            )
        except Exception:
            return 503, {}, {"error": "receipt_store_unavailable"}
        if result.outcome == "conflict":
            return 409, {}, {"error": "receipt_conflict"}
        if result.outcome not in ("created", "duplicate"):
            return 503, {}, {"error": "receipt_store_unavailable"}
        if self._fault_mode == "accept-then-503-on-first" and attempt == 1:
            return 503, {"Retry-After": "5"}, {"error": "simulated_lost_acknowledgement"}
        return 200, {}, {
            "status": "duplicate" if result.outcome == "duplicate" else "received",
            "event_id": event_id,
        }

    @staticmethod
    def _parse_header_int(value: Any) -> int | None:
        if not isinstance(value, str) or not _HEADER_INT.fullmatch(value):
            return None
        return int(value)
