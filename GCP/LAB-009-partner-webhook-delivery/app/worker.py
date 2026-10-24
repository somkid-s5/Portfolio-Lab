"""Fenced Cloud Tasks delivery worker and partner webhook client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
import uuid

import requests

from app.domain import (
    ValidationError,
    canonical_event_bytes,
    classify_partner_status,
    delivery_id as make_delivery_id,
    retry_after_seconds,
    sign_webhook,
    payload_sha256,
)
from app.ledger import FirestoreLedger
from app.secret_manager import SecretConfigurationError


_PARTNER_ID = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?$")
_EVENT_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_DELIVERY_ID = re.compile(r"^[0-9a-f]{64}$")
_SECRET_VERSION = re.compile(
    r"^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/secrets/[A-Za-z0-9_-]{1,255}/versions/[1-9][0-9]*$"
)
MAX_ATTEMPTS = 5
LEASE_SECONDS = 45
PARTNER_TIMEOUT = (5, 5)


@dataclass(frozen=True)
class PartnerEndpoint:
    partner_id: str
    url: str
    secret_version: str


@dataclass(frozen=True)
class WorkerResult:
    status_code: int
    body: Mapping[str, Any]
    headers: Mapping[str, str] | None = None


def validate_partner_endpoint(endpoint: PartnerEndpoint) -> None:
    if not isinstance(endpoint, PartnerEndpoint):
        raise ValidationError("partner endpoint configuration is required")
    if not isinstance(endpoint.partner_id, str) or not _PARTNER_ID.fullmatch(endpoint.partner_id):
        raise ValidationError("partner_id is invalid")
    parsed = urlsplit(endpoint.url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path != f"/v1/webhooks/{endpoint.partner_id}"
        or parsed.query
        or parsed.fragment
    ):
        raise ValidationError("partner URL must be the fixed HTTPS webhook route")
    if not isinstance(endpoint.secret_version, str) or not _SECRET_VERSION.fullmatch(
        endpoint.secret_version
    ):
        raise ValidationError("secret_version must be a pinned Secret Manager version")


def parse_task_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != {
        "delivery_id", "event_id", "generation", "partner_id"
    }:
        raise ValidationError("task payload fields are invalid")
    event_id = payload["event_id"]
    partner_id = payload["partner_id"]
    delivery = payload["delivery_id"]
    generation = payload["generation"]
    if not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id):
        raise ValidationError("event_id is invalid")
    if not isinstance(partner_id, str) or not _PARTNER_ID.fullmatch(partner_id):
        raise ValidationError("partner_id is invalid")
    if not isinstance(delivery, str) or not _DELIVERY_ID.fullmatch(delivery):
        raise ValidationError("delivery_id is invalid")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValidationError("generation is invalid")
    if delivery != make_delivery_id(event_id, partner_id):
        raise ValidationError("delivery_id does not match task identity")
    return {
        "delivery_id": delivery,
        "event_id": event_id,
        "generation": generation,
        "partner_id": partner_id,
    }


class DeliveryWorker:
    """Claim one fenced attempt, sign the canonical event and classify outcome."""

    def __init__(
        self,
        *,
        ledger: FirestoreLedger,
        partner_endpoints: Mapping[str, PartnerEndpoint],
        secret_provider: Callable[[str], bytes],
        http_session: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        lease_seconds: int = LEASE_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        endpoints = dict(partner_endpoints)
        if not endpoints or any(key != value.partner_id for key, value in endpoints.items()):
            raise ValidationError("endpoint keys must match configured partner IDs")
        for endpoint in endpoints.values():
            validate_partner_endpoint(endpoint)
        if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 20 <= lease_seconds <= 120:
            raise ValidationError("lease_seconds must be between 20 and 120")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= MAX_ATTEMPTS:
            raise ValidationError("max_attempts must be between 1 and 5")
        self._ledger = ledger
        self._endpoints = endpoints
        self._secret_provider = secret_provider
        self._http = http_session or requests.Session()
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lease_seconds = lease_seconds
        self._max_attempts = max_attempts

    def process(self, payload: Any) -> WorkerResult:
        try:
            task = parse_task_request(payload)
        except ValidationError:
            return WorkerResult(400, {"error": "invalid_task"})

        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            return WorkerResult(503, {"error": "worker_clock_unavailable"})
        if now.utcoffset() != timezone.utc.utcoffset(now):
            return WorkerResult(503, {"error": "worker_clock_unavailable"})
        now = now.astimezone(timezone.utc)
        lease_token = uuid.uuid4().hex
        try:
            claim = self._ledger.claim_attempt(
                task["delivery_id"],
                event_id=task["event_id"],
                partner_id=task["partner_id"],
                generation=task["generation"],
                lease_token=lease_token,
                lease_until=now + timedelta(seconds=self._lease_seconds),
                max_attempts=self._max_attempts,
                now=now,
            )
        except Exception:
            return WorkerResult(503, {"error": "delivery_ledger_unavailable"})

        if claim.outcome == "terminal":
            return WorkerResult(200, {"status": "already_terminal"})
        if claim.outcome == "stale_generation":
            return WorkerResult(200, {"status": "superseded_generation"})
        if claim.outcome == "review_required":
            return WorkerResult(200, {"status": "manual_review_required"})
        if claim.outcome == "busy":
            return WorkerResult(
                503,
                {"error": "delivery_lease_busy"},
                {"Retry-After": "5"},
            )
        if claim.outcome != "claimed" or claim.attempt_number is None:
            return WorkerResult(503, {"error": "delivery_not_claimable"})

        attempt = claim.attempt_number
        try:
            event_record = self._ledger.get_event(task["event_id"])
        except Exception:
            return self._retry(
                task, attempt, lease_token, error_code="EventLedgerUnavailable"
            )
        event = event_record.get("event") if event_record else None
        if not isinstance(event, dict) or event.get("partner_id") != task["partner_id"]:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="EventRecordMissing",
            )
        try:
            raw_body = canonical_event_bytes(event)
        except ValidationError:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="EventLedgerInvariantError",
            )
        stored_hash = event_record.get("payload_sha256")
        if not isinstance(stored_hash, str) or stored_hash != claim.payload_sha256:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="EventLedgerInvariantError",
            )
        if payload_sha256(raw_body) != stored_hash:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="EventLedgerInvariantError",
            )

        endpoint = self._endpoints.get(task["partner_id"])
        if endpoint is None:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="PartnerConfigurationError",
            )
        try:
            secret = self._secret_provider(endpoint.secret_version)
        except SecretConfigurationError:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="SecretConfigurationError",
            )
        except Exception as exc:
            return self._retry(
                task, attempt, lease_token, error_code=self._safe_error_type(exc)
            )
        if not isinstance(secret, bytes) or len(secret) < 32:
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=None, error_code="InvalidPartnerSecret",
            )

        timestamp = int(now.timestamp())
        signature = sign_webhook(
            secret,
            raw_body,
            partner_id=task["partner_id"],
            timestamp=timestamp,
            generation=task["generation"],
            attempt_number=attempt,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Event-ID": task["event_id"],
            "X-Webhook-Timestamp": str(timestamp),
            "X-Webhook-Generation": str(task["generation"]),
            "X-Webhook-Attempt": str(attempt),
            "X-Webhook-Signature": signature,
        }
        try:
            response = self._http.post(
                endpoint.url,
                data=raw_body,
                headers=headers,
                timeout=PARTNER_TIMEOUT,
                allow_redirects=False,
            )
            status = response.status_code
            classification = classify_partner_status(status)
        except Exception as exc:
            return self._retry(
                task, attempt, lease_token, error_code=self._safe_error_type(exc)
            )

        if classification == "success":
            return self._finish(
                task, attempt, lease_token, outcome="delivered",
                http_status=status,
            )
        if classification == "permanent":
            return self._finish(
                task, attempt, lease_token, outcome="permanent_failed",
                http_status=status,
                error_code=f"partner_http_{status}",
            )

        retry_after = retry_after_seconds(getattr(response, "headers", {}) or {})
        response_code = 429 if status == 429 else 503
        headers_out = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return self._finish(
            task,
            attempt,
            lease_token,
            outcome="retry",
            http_status=status,
            error_code=f"partner_http_{status}",
            retry_after_seconds=retry_after,
            response_code=response_code,
            response_headers=headers_out,
        )

    def _retry(
        self,
        task: Mapping[str, Any],
        attempt: int,
        lease_token: str,
        *,
        error_code: str,
    ) -> WorkerResult:
        return self._finish(
            task,
            attempt,
            lease_token,
            outcome="retry",
            http_status=None,
            error_code=error_code,
            retry_after_seconds=5,
            response_code=503,
            response_headers={"Retry-After": "5"},
        )

    def _finish(
        self,
        task: Mapping[str, Any],
        attempt: int,
        lease_token: str,
        *,
        outcome: str,
        http_status: int | None,
        error_code: str | None = None,
        retry_after_seconds: int | None = None,
        response_code: int | None = None,
        response_headers: Mapping[str, str] | None = None,
    ) -> WorkerResult:
        now = self._clock()
        try:
            committed = self._ledger.finish_attempt(
                task["delivery_id"],
                generation=task["generation"],
                attempt_number=attempt,
                lease_token=lease_token,
                outcome=outcome,
                http_status=http_status,
                error_code=error_code,
                retry_after_seconds=retry_after_seconds,
                now=now,
            )
        except Exception:
            committed = False
        if not committed:
            return WorkerResult(503, {"error": "attempt_commit_unavailable"})
        if outcome == "retry":
            status = response_code or 503
            return WorkerResult(
                status,
                {"error": "partner_temporarily_unavailable"},
                response_headers,
            )
        if outcome == "delivered":
            return WorkerResult(200, {"status": "delivered"})
        return WorkerResult(200, {"status": "permanent_failure_recorded"})

    @staticmethod
    def _safe_error_type(exc: Exception) -> str:
        code = type(exc).__name__
        return code if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", code) else "PartnerRequestError"
