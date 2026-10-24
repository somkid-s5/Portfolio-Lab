"""Firestore-backed event and delivery ledger for Lab 09."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import re
from typing import Any, Callable, Mapping

from google.cloud import firestore

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
            if status not in ("enqueue_pending", "queued"):
                return False
            txn.update(
                ref,
                {
                    "status": "retry_ended_unknown",
                    "review_required": True,
                    "review_reason": reason,
                    "task_missing_at": updated_at,
                    "updated_at": updated_at,
                },
            )
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
