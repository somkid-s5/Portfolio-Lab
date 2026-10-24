"""Firestore-backed event and delivery ledger for Lab 09."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import re
from typing import Any, Callable, Mapping

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.domain import (
    ValidationError,
    canonical_event_bytes,
    delivery_id as make_delivery_id,
    idempotency_document_id,
    payload_sha256,
    task_id,
)


_HASH = re.compile(r"^[0-9a-f]{64}$")
_COLLECTION_PREFIX = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


class IdempotencyConflict(Exception):
    """One idempotency key was used for different submitted request bytes."""


class LedgerInvariantError(RuntimeError):
    """Stored ledger data or a requested transition violates an invariant."""


@dataclass(frozen=True)
class SubmissionResult:
    event_id: str
    delivery_id: str
    payload_sha256: str
    duplicate: bool


@dataclass(frozen=True)
class AttemptClaim:
    outcome: str
    attempt_number: int | None = None
    lease_token: str | None = None
    payload_sha256: str | None = None


class FirestoreLedger:
    """Atomically persist the canonical event, outbox delivery and key record.

    Firestore transaction callbacks may run more than once. All generated IDs
    and timestamps are therefore prepared before entering the callback.
    """

    def __init__(
        self,
        client: firestore.Client,
        *,
        collection_prefix: str = "lab09",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not _COLLECTION_PREFIX.fullmatch(collection_prefix):
            raise ValueError("collection_prefix must be a short lowercase identifier")
        self._client = client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.events = client.collection(f"{collection_prefix}_events")
        self.deliveries = client.collection(f"{collection_prefix}_deliveries")
        self.idempotency = client.collection(f"{collection_prefix}_idempotency")

    def accept(
        self,
        event: Mapping[str, Any],
        *,
        idempotency_key: str,
        request_sha256: str,
        task_name: str,
    ) -> SubmissionResult:
        """Create the event, delivery outbox and idempotency record atomically."""
        if not isinstance(request_sha256, str) or not _HASH.fullmatch(request_sha256):
            raise ValidationError("request_sha256 must be lowercase SHA-256 hex")
        if not isinstance(task_name, str) or not task_name:
            raise ValidationError("task_name is required")

        payload = canonical_event_bytes(event)
        canonical_hash = payload_sha256(payload)
        event_id = event["event_id"]
        partner_id = event["partner_id"]
        delivery = make_delivery_id(event_id, partner_id)
        generation = 1
        if task_name.rsplit("/", 1)[-1] != task_id(delivery, generation):
            raise ValidationError("task_name does not match delivery and generation")

        key_hash = idempotency_document_id(idempotency_key)
        accepted_at = self._clock()
        if not isinstance(accepted_at, datetime) or accepted_at.tzinfo is None:
            raise ValidationError("ledger clock must return a timezone-aware datetime")
        if accepted_at.utcoffset() != timezone.utc.utcoffset(accepted_at):
            raise ValidationError("ledger clock must return UTC")
        accepted_at = accepted_at.astimezone(timezone.utc)

        event_ref = self.events.document(event_id)
        delivery_ref = self.deliveries.document(delivery)
        key_ref = self.idempotency.document(key_hash)
        event_document = {
            "event": dict(event),
            "canonical_body": payload,
            "payload_sha256": canonical_hash,
            "created_at": accepted_at,
        }
        delivery_document = {
            "event_id": event_id,
            "partner_id": partner_id,
            "generation": generation,
            "status": "enqueue_pending",
            "task_name": task_name,
            "payload_sha256": canonical_hash,
            "created_at": accepted_at,
            "updated_at": accepted_at,
            "enqueue_pending_since": accepted_at,
            "enqueue_attempts": 0,
            "last_enqueue_error": None,
        }
        key_document = {
            "request_sha256": request_sha256,
            "event_sha256": canonical_hash,
            "event_id": event_id,
            "delivery_id": delivery,
            "partner_id": partner_id,
            "created_at": accepted_at,
        }

        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> SubmissionResult:
            existing = key_ref.get(transaction=txn, timeout=10)
            if existing.exists:
                record = existing.to_dict() or {}
                stored_hash = record.get("request_sha256")
                if not isinstance(stored_hash, str) or not hmac.compare_digest(
                    stored_hash, request_sha256
                ):
                    raise IdempotencyConflict(
                        "Idempotency-Key already exists with a different request body"
                    )
                existing_event = record.get("event_id")
                existing_delivery = record.get("delivery_id")
                existing_payload_hash = record.get("event_sha256")
                if (
                    not isinstance(existing_event, str)
                    or not isinstance(existing_delivery, str)
                    or not isinstance(existing_payload_hash, str)
                    or not _HASH.fullmatch(existing_payload_hash)
                ):
                    raise LedgerInvariantError("idempotency record is missing a valid event reference")
                return SubmissionResult(
                    event_id=existing_event,
                    delivery_id=existing_delivery,
                    payload_sha256=existing_payload_hash,
                    duplicate=True,
                )

            txn.create(event_ref, event_document)
            txn.create(delivery_ref, delivery_document)
            txn.create(key_ref, key_document)
            return SubmissionResult(
                event_id=event_id,
                delivery_id=delivery,
                payload_sha256=canonical_hash,
                duplicate=False,
            )

        return commit(transaction)


    def record_enqueue_error(
        self,
        delivery: str,
        *,
        generation: int,
        error_code: str,
        now: datetime | None = None,
    ) -> bool:
        """Record a bounded error code only while this generation is pending."""
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValidationError("generation must be a positive integer")
        if not isinstance(error_code, str) or not re.fullmatch(
            r"[A-Za-z][A-Za-z0-9_.-]{0,63}", error_code
        ):
            raise ValidationError("error_code must be a safe short identifier")
        updated_at = now or self._clock()
        if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
            raise ValidationError("transition time must be timezone-aware")
        if updated_at.utcoffset() != timezone.utc.utcoffset(updated_at):
            raise ValidationError("transition time must be UTC")
        updated_at = updated_at.astimezone(timezone.utc)
        ref = self.deliveries.document(delivery)
        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> bool:
            snapshot = ref.get(transaction=txn, timeout=10)
            if not snapshot.exists:
                raise LedgerInvariantError("delivery record does not exist")
            record = snapshot.to_dict() or {}
            current_generation = record.get("generation")
            if type(current_generation) is not int:
                raise LedgerInvariantError("delivery generation is not an integer")
            if current_generation != generation or record.get("status") != "enqueue_pending":
                return False
            attempts = record.get("enqueue_attempts", 0)
            if type(attempts) is not int or attempts < 0:
                raise LedgerInvariantError("enqueue_attempts is invalid")
            txn.update(
                ref,
                {
                    "enqueue_attempts": attempts + 1,
                    "last_enqueue_error": error_code,
                    "updated_at": updated_at,
                },
            )
            return True

        return commit(transaction)

    def mark_retry_ended_unknown(
        self,
        delivery: str,
        *,
        generation: int,
        reason: str,
        now: datetime | None = None,
    ) -> bool:
        """Move only the matching nonterminal generation to manual review."""
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValidationError("generation must be a positive integer")
        if not isinstance(reason, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{2,63}", reason
        ):
            raise ValidationError("reason must be a safe short identifier")
        updated_at = now or self._clock()
        if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
            raise ValidationError("transition time must be timezone-aware")
        if updated_at.utcoffset() != timezone.utc.utcoffset(updated_at):
            raise ValidationError("transition time must be UTC")
        updated_at = updated_at.astimezone(timezone.utc)
        ref = self.deliveries.document(delivery)
        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> bool:
            snapshot = ref.get(transaction=txn, timeout=10)
            if not snapshot.exists:
                raise LedgerInvariantError("delivery record does not exist")
            record = snapshot.to_dict() or {}
            current_generation = record.get("generation")
            if type(current_generation) is not int:
                raise LedgerInvariantError("delivery generation is not an integer")
            if current_generation != generation:
                return False
            status = record.get("status")
            if status == "retry_ended_unknown":
                if record.get("review_reason") != reason:
                    raise LedgerInvariantError("unknown outcome already has a different reason")
                return True
            expired_attempt_ref = None
            expired_attempt_snapshot = None
            if status == "attempt_running":
                lease_until = record.get("lease_until")
                if not isinstance(lease_until, datetime) or lease_until.tzinfo is None:
                    raise LedgerInvariantError("running attempt has no valid lease deadline")
                if updated_at < lease_until.astimezone(timezone.utc):
                    return False
                attempt_number = record.get("attempt_count")
                if type(attempt_number) is not int or attempt_number < 1:
                    raise LedgerInvariantError("running delivery has no valid attempt number")
                expired_attempt_ref = ref.collection("attempts").document(
                    f"g{generation:03d}-a{attempt_number:03d}"
                )
                expired_attempt_snapshot = expired_attempt_ref.get(
                    transaction=txn, timeout=10
                )
            elif status not in ("enqueue_pending", "queued"):
                return False
            if expired_attempt_ref is not None:
                if expired_attempt_snapshot is None or not expired_attempt_snapshot.exists:
                    raise LedgerInvariantError("running delivery attempt record is missing")
                if (expired_attempt_snapshot.to_dict() or {}).get("status") == "running":
                    txn.update(
                        expired_attempt_ref,
                        {
                            "status": "lease_expired",
                            "finished_at": updated_at,
                            "error_code": reason,
                        },
                    )
            txn.update(
                ref,
                {
                    "status": "retry_ended_unknown",
                    "review_required": True,
                    "review_reason": reason,
                    "task_missing_at": updated_at,
                    "updated_at": updated_at,
                    "lease_token": firestore.DELETE_FIELD,
                    "lease_until": firestore.DELETE_FIELD,
                },
            )
            return True

        return commit(transaction)

    def claim_attempt(
        self,
        delivery: str,
        *,
        event_id: str,
        partner_id: str,
        generation: int,
        lease_token: str,
        lease_until: datetime,
        max_attempts: int = 5,
        now: datetime | None = None,
    ) -> AttemptClaim:
        """Fence one worker attempt and append its durable start record."""
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        if not isinstance(event_id, str) or not event_id:
            raise ValidationError("event_id is required")
        if not isinstance(partner_id, str) or not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,28}[a-z0-9])?", partner_id
        ):
            raise ValidationError("partner_id is invalid")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValidationError("generation must be a positive integer")
        if not isinstance(lease_token, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_token):
            raise ValidationError("lease_token must be 32 lowercase hex characters")
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
            raise ValidationError("max_attempts must be between 1 and 5")
        transition_time = now or self._clock()
        if not isinstance(transition_time, datetime) or transition_time.tzinfo is None:
            raise ValidationError("transition time must be timezone-aware")
        if transition_time.utcoffset() != timezone.utc.utcoffset(transition_time):
            raise ValidationError("transition time must be UTC")
        transition_time = transition_time.astimezone(timezone.utc)
        if not isinstance(lease_until, datetime) or lease_until.tzinfo is None:
            raise ValidationError("lease_until must be timezone-aware")
        if lease_until.utcoffset() != timezone.utc.utcoffset(lease_until):
            raise ValidationError("lease_until must be UTC")
        lease_until = lease_until.astimezone(timezone.utc)
        if not transition_time < lease_until <= transition_time + timedelta(minutes=2):
            raise ValidationError("worker lease must be future-dated and no longer than two minutes")

        ref = self.deliveries.document(delivery)
        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> AttemptClaim:
            snapshot = ref.get(transaction=txn, timeout=10)
            if not snapshot.exists:
                raise LedgerInvariantError("delivery record does not exist")
            record = snapshot.to_dict() or {}
            current_generation = record.get("generation")
            if type(current_generation) is not int:
                raise LedgerInvariantError("delivery generation is not an integer")
            if current_generation != generation:
                return AttemptClaim("stale_generation")
            if record.get("event_id") != event_id or record.get("partner_id") != partner_id:
                raise LedgerInvariantError("task identity does not match delivery record")

            stored_payload_hash = record.get("payload_sha256")
            if not isinstance(stored_payload_hash, str) or not _HASH.fullmatch(stored_payload_hash):
                raise LedgerInvariantError("delivery payload hash is invalid")
            status = record.get("status")
            if status in ("delivered", "permanent_failed"):
                return AttemptClaim("terminal")

            attempt_count = record.get("attempt_count", 0)
            if type(attempt_count) is not int or attempt_count < 0:
                raise LedgerInvariantError("attempt_count is invalid")
            previous_attempt_ref = None
            previous_attempt_snapshot = None
            if status == "attempt_running":
                current_lease_until = record.get("lease_until")
                if not isinstance(current_lease_until, datetime) or current_lease_until.tzinfo is None:
                    raise LedgerInvariantError("running attempt has no valid lease deadline")
                current_lease_until = current_lease_until.astimezone(timezone.utc)
                if transition_time < current_lease_until:
                    return AttemptClaim("busy")
                if attempt_count < 1:
                    raise LedgerInvariantError("running delivery has no attempt number")
                previous_attempt_ref = ref.collection("attempts").document(
                    f"g{generation:03d}-a{attempt_count:03d}"
                )
                previous_attempt_snapshot = previous_attempt_ref.get(
                    transaction=txn, timeout=10
                )
                if not previous_attempt_snapshot.exists:
                    raise LedgerInvariantError("running delivery attempt record is missing")

            claimable = ("enqueue_pending", "queued", "retry_ended_unknown", "attempt_running")
            if status not in claimable:
                return AttemptClaim("not_claimable")
            if attempt_count >= max_attempts:
                if previous_attempt_ref is not None:
                    txn.update(
                        previous_attempt_ref,
                        {
                            "status": "lease_expired",
                            "finished_at": transition_time,
                            "error_code": "lease_expired",
                        },
                    )
                txn.update(
                    ref,
                    {
                        "status": "retry_ended_unknown",
                        "review_required": True,
                        "review_reason": "worker_attempt_limit",
                        "updated_at": transition_time,
                        "lease_token": firestore.DELETE_FIELD,
                        "lease_until": firestore.DELETE_FIELD,
                    },
                )
                return AttemptClaim("review_required")

            if previous_attempt_ref is not None:
                txn.update(
                    previous_attempt_ref,
                    {
                        "status": "lease_expired",
                        "finished_at": transition_time,
                        "error_code": "lease_expired",
                    },
                )
            next_attempt = attempt_count + 1
            attempt_ref = ref.collection("attempts").document(
                f"g{generation:03d}-a{next_attempt:03d}"
            )
            txn.create(
                attempt_ref,
                {
                    "generation": generation,
                    "attempt_number": next_attempt,
                    "status": "running",
                    "started_at": transition_time,
                    "finished_at": None,
                    "http_status": None,
                    "error_code": None,
                },
            )
            update = {
                "status": "attempt_running",
                "attempt_count": next_attempt,
                "lease_token": lease_token,
                "lease_until": lease_until,
                "updated_at": transition_time,
            }
            if status == "retry_ended_unknown":
                update.update(
                    {
                        "review_required": False,
                        "last_review_reason": record.get("review_reason"),
                        "review_reason": firestore.DELETE_FIELD,
                        "task_missing_at": firestore.DELETE_FIELD,
                    }
                )
            txn.update(ref, update)
            return AttemptClaim("claimed", next_attempt, lease_token, stored_payload_hash)

        return commit(transaction)

    def finish_attempt(
        self,
        delivery: str,
        *,
        generation: int,
        attempt_number: int,
        lease_token: str,
        outcome: str,
        http_status: int | None,
        error_code: str | None = None,
        retry_after_seconds: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Commit an attempt result only while its fencing token still owns it."""
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValidationError("generation must be a positive integer")
        if not isinstance(attempt_number, int) or isinstance(attempt_number, bool) or attempt_number < 1:
            raise ValidationError("attempt_number must be positive")
        if not isinstance(lease_token, str) or not re.fullmatch(r"[0-9a-f]{32}", lease_token):
            raise ValidationError("lease_token must be 32 lowercase hex characters")
        if outcome not in ("delivered", "permanent_failed", "retry"):
            raise ValidationError("unsupported attempt outcome")
        if http_status is not None and (
            not isinstance(http_status, int) or isinstance(http_status, bool) or not 100 <= http_status <= 599
        ):
            raise ValidationError("http_status is invalid")
        if error_code is not None and (
            not isinstance(error_code, str)
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", error_code)
        ):
            raise ValidationError("error_code is invalid")
        if retry_after_seconds is not None and (
            not isinstance(retry_after_seconds, int)
            or isinstance(retry_after_seconds, bool)
            or not 0 <= retry_after_seconds <= 60
        ):
            raise ValidationError("retry_after_seconds must be between 0 and 60")
        transition_time = now or self._clock()
        if not isinstance(transition_time, datetime) or transition_time.tzinfo is None:
            raise ValidationError("transition time must be timezone-aware")
        if transition_time.utcoffset() != timezone.utc.utcoffset(transition_time):
            raise ValidationError("transition time must be UTC")
        transition_time = transition_time.astimezone(timezone.utc)

        ref = self.deliveries.document(delivery)
        attempt_ref = ref.collection("attempts").document(
            f"g{generation:03d}-a{attempt_number:03d}"
        )
        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> bool:
            snapshot = ref.get(transaction=txn, timeout=10)
            if not snapshot.exists:
                raise LedgerInvariantError("delivery record does not exist")
            record = snapshot.to_dict() or {}
            current_generation = record.get("generation")
            current_attempt = record.get("attempt_count")
            if type(current_generation) is not int or type(current_attempt) is not int:
                raise LedgerInvariantError("delivery attempt identity is invalid")
            if current_generation != generation or current_attempt != attempt_number:
                return False
            current_lease_until = record.get("lease_until")
            if (
                record.get("status") != "attempt_running"
                or not isinstance(record.get("lease_token"), str)
                or not hmac.compare_digest(record["lease_token"], lease_token)
                or not isinstance(current_lease_until, datetime)
                or current_lease_until.tzinfo is None
                or transition_time >= current_lease_until.astimezone(timezone.utc)
            ):
                return False

            status = "queued" if outcome == "retry" else outcome
            attempt_update = {
                "status": outcome,
                "finished_at": transition_time,
                "http_status": http_status,
                "error_code": error_code,
                "retry_after_seconds": retry_after_seconds,
            }
            delivery_update = {
                "status": status,
                "last_attempt_outcome": outcome,
                "last_http_status": http_status,
                "last_error_code": error_code,
                "updated_at": transition_time,
                "lease_token": firestore.DELETE_FIELD,
                "lease_until": firestore.DELETE_FIELD,
            }
            if outcome == "delivered":
                delivery_update["delivered_at"] = transition_time
            elif outcome == "permanent_failed":
                delivery_update["permanent_failed_at"] = transition_time
            txn.update(attempt_ref, attempt_update)
            txn.update(ref, delivery_update)
            return True

        return commit(transaction)


    def get_event(self, event_id: str) -> dict[str, Any] | None:
        if not isinstance(event_id, str):
            raise ValidationError("event_id must be a string")
        snapshot = self.events.document(event_id).get(timeout=10)
        return snapshot.to_dict() if snapshot.exists else None

    def get_delivery(self, delivery: str) -> dict[str, Any] | None:
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        snapshot = self.deliveries.document(delivery).get(timeout=10)
        return snapshot.to_dict() if snapshot.exists else None


    def list_deliveries(self, status: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Read one bounded status page without a compound-order index."""
        if status not in ("enqueue_pending", "queued", "attempt_running"):
            raise ValidationError("unsupported reconciliation status")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 25:
            raise ValidationError("reconciliation page limit must be between 1 and 25")
        query = (
            self.deliveries.where(filter=FieldFilter("status", "==", status))
            .limit(limit)
        )
        results = []
        for snapshot in query.stream(timeout=10):
            record = snapshot.to_dict() or {}
            record["delivery_id"] = snapshot.id
            results.append(record)
        return results

    def mark_task_enqueued(
        self,
        delivery: str,
        *,
        generation: int,
        task_name: str,
        now: datetime | None = None,
    ) -> bool:
        """Mark only a still-pending matching generation as queued.

        A fast worker may already have advanced the record by the time the
        CreateTask response returns. This method never regresses that state.
        """
        if not isinstance(delivery, str) or not _HASH.fullmatch(delivery):
            raise ValidationError("delivery_id must be lowercase SHA-256 hex")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValidationError("generation must be a positive integer")
        if not isinstance(task_name, str) or not task_name:
            raise ValidationError("task_name is required")
        if task_name.rsplit("/", 1)[-1] != task_id(delivery, generation):
            raise ValidationError("task_name does not match delivery and generation")
        transition_time = now or self._clock()
        if not isinstance(transition_time, datetime) or transition_time.tzinfo is None:
            raise ValidationError("transition time must be timezone-aware")
        if transition_time.utcoffset() != timezone.utc.utcoffset(transition_time):
            raise ValidationError("transition time must be UTC")
        transition_time = transition_time.astimezone(timezone.utc)

        ref = self.deliveries.document(delivery)
        transaction = self._client.transaction(max_attempts=5)

        @firestore.transactional
        def commit(txn: Any) -> bool:
            snapshot = ref.get(transaction=txn, timeout=10)
            if not snapshot.exists:
                raise LedgerInvariantError("delivery record does not exist")
            record = snapshot.to_dict() or {}
            current_generation = record.get("generation")
            current_status = record.get("status")
            current_task = record.get("task_name")
            if type(current_generation) is not int:
                raise LedgerInvariantError("delivery generation is not an integer")
            if current_generation != generation:
                return False
            if current_status == "queued":
                if current_task != task_name:
                    raise LedgerInvariantError("queued delivery has a different task name")
                return True
            if current_status != "enqueue_pending":
                return False
            enqueue_attempts = record.get("enqueue_attempts", 0)
            if type(enqueue_attempts) is not int or enqueue_attempts < 0:
                raise LedgerInvariantError("enqueue_attempts is invalid")
            txn.update(
                ref,
                {
                    "status": "queued",
                    "task_name": task_name,
                    "enqueued_at": transition_time,
                    "updated_at": transition_time,
                    "enqueue_attempts": enqueue_attempts + 1,
                    "last_enqueue_error": None,
                },
            )
            return True

        return commit(transaction)
