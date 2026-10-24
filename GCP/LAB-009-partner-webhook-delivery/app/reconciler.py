"""Bounded outbox and Cloud Tasks reconciliation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Mapping

from app.domain import ValidationError
from app.ledger import FirestoreLedger
from app.task_queue import CloudTasksEnqueuer, PartnerQueue


STALE_ENQUEUE_AFTER = timedelta(minutes=15)
MAX_PAGE_SIZE = 25
_PENDING_UNKNOWN_REASON = "enqueue_pending_timeout"
_QUEUED_UNKNOWN_REASON = "queued_task_not_found"
_RUNNING_UNKNOWN_REASON = "attempt_lease_expired_task_missing"


@dataclass(frozen=True)
class ReconcileSummary:
    pending_seen: int = 0
    queued_seen: int = 0
    running_seen: int = 0
    enqueued: int = 0
    moved_to_review: int = 0
    errors: int = 0


class OutboxReconciler:
    """Repair fresh outbox records and inspect a bounded page of queued or expired running tasks."""

    def __init__(
        self,
        *,
        ledger: FirestoreLedger,
        enqueuer: CloudTasksEnqueuer,
        partner_queues: Mapping[str, PartnerQueue],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ledger = ledger
        self._enqueuer = enqueuer
        self._queues = dict(partner_queues)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_once(self, *, page_size: int = MAX_PAGE_SIZE) -> ReconcileSummary:
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValidationError("reconciler page size must be between 1 and 25")
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValidationError("reconciler clock must return a timezone-aware datetime")
        if now.utcoffset() != timezone.utc.utcoffset(now):
            raise ValidationError("reconciler clock must return UTC")
        now = now.astimezone(timezone.utc)

        pending_budget = (page_size + 2) // 3
        queued_budget = (page_size + 1) // 3
        running_budget = page_size // 3
        pending = self._ledger.list_deliveries(
            "enqueue_pending", limit=pending_budget
        )
        queued = (
            self._ledger.list_deliveries("queued", limit=queued_budget)
            if queued_budget
            else []
        )
        running = (
            self._ledger.list_deliveries("attempt_running", limit=running_budget)
            if running_budget
            else []
        )
        enqueued = moved = errors = 0

        for record in pending:
            delivery = record.get("delivery_id")
            generation = record.get("generation")
            partner_id = record.get("partner_id")
            event_id = record.get("event_id")
            pending_since = record.get("enqueue_pending_since")
            if (
                not isinstance(delivery, str)
                or not isinstance(generation, int)
                or isinstance(generation, bool)
                or not isinstance(partner_id, str)
                or not isinstance(event_id, str)
                or not isinstance(pending_since, datetime)
                or pending_since.tzinfo is None
            ):
                errors += 1
                continue
            if now - pending_since.astimezone(timezone.utc) >= STALE_ENQUEUE_AFTER:
                try:
                    if self._ledger.mark_retry_ended_unknown(
                        delivery,
                        generation=generation,
                        reason=_PENDING_UNKNOWN_REASON,
                        now=now,
                    ):
                        moved += 1
                except Exception:
                    errors += 1
                continue

            try:
                event_record = self._ledger.get_event(event_id)
            except Exception:
                errors += 1
                continue
            event = event_record.get("event") if event_record else None
            config = self._queues.get(partner_id)
            if not isinstance(event, dict) or config is None:
                error_code = "EventRecordMissing" if not isinstance(event, dict) else "PartnerConfigurationError"
                try:
                    self._ledger.record_enqueue_error(
                        delivery,
                        generation=generation,
                        error_code=error_code,
                        now=now,
                    )
                except Exception:
                    errors += 1
                continue
            try:
                result = self._enqueuer.enqueue(
                    event,
                    delivery=delivery,
                    generation=generation,
                    config=config,
                )
                if result.outcome in ("created", "already_exists"):
                    if self._ledger.mark_task_enqueued(
                        delivery,
                        generation=generation,
                        task_name=result.task_name,
                        now=now,
                    ):
                        enqueued += 1
                elif result.outcome == "missing_after_already_exists":
                    if self._ledger.mark_retry_ended_unknown(
                        delivery,
                        generation=generation,
                        reason="task_missing_after_already_exists",
                        now=now,
                    ):
                        moved += 1
                else:
                    raise RuntimeError("unexpected_enqueue_outcome")
            except Exception as exc:
                error_code = type(exc).__name__
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", error_code):
                    error_code = "EnqueueError"
                try:
                    if self._ledger.record_enqueue_error(
                        delivery,
                        generation=generation,
                        error_code=error_code,
                        now=now,
                    ):
                        errors += 1
                except Exception:
                    errors += 1

        for record in queued:
            delivery = record.get("delivery_id")
            generation = record.get("generation")
            task_name = record.get("task_name")
            if (
                not isinstance(delivery, str)
                or not isinstance(generation, int)
                or isinstance(generation, bool)
                or not isinstance(task_name, str)
            ):
                errors += 1
                continue
            try:
                exists = self._enqueuer.task_exists(task_name)
                if not exists and self._ledger.mark_retry_ended_unknown(
                    delivery,
                    generation=generation,
                    reason=_QUEUED_UNKNOWN_REASON,
                    now=now,
                ):
                    moved += 1
            except Exception:
                errors += 1

        for record in running:
            delivery = record.get("delivery_id")
            generation = record.get("generation")
            task_name = record.get("task_name")
            lease_until = record.get("lease_until")
            if (
                not isinstance(delivery, str)
                or not isinstance(generation, int)
                or isinstance(generation, bool)
                or not isinstance(task_name, str)
                or not isinstance(lease_until, datetime)
                or lease_until.tzinfo is None
            ):
                errors += 1
                continue
            if now < lease_until.astimezone(timezone.utc):
                continue
            try:
                exists = self._enqueuer.task_exists(task_name)
                if not exists and self._ledger.mark_retry_ended_unknown(
                    delivery,
                    generation=generation,
                    reason=_RUNNING_UNKNOWN_REASON,
                    now=now,
                ):
                    moved += 1
            except Exception:
                errors += 1

        return ReconcileSummary(
            pending_seen=len(pending),
            queued_seen=len(queued),
            running_seen=len(running),
            enqueued=enqueued,
            moved_to_review=moved,
            errors=errors,
        )
