"""Firestore transaction adapter for the daily report state machine."""
from datetime import datetime, timezone
import re

from google.cloud import firestore

from app import ledger_state as state

COLLECTION_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,62}$")


class FirestoreLedger:
    """Persists pure transitions; transaction callbacks perform no external I/O."""

    def __init__(self, client, *, collection="daily_runs", clock=None):
        if not isinstance(collection, str) or not COLLECTION_RE.fullmatch(collection):
            raise ValueError("invalid_ledger_collection")
        self.client = client
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.collection = client.collection(collection)

    def read(self, business_date):
        state._date(business_date)
        snap = self.collection.document(business_date).get(timeout=10)
        return snap.to_dict() if snap.exists else None

    def _change(self, business_date, transition):
        state._date(business_date)
        ref = self.collection.document(business_date)

        @firestore.transactional
        def run(transaction):
            snap = ref.get(transaction=transaction, timeout=10)
            previous = snap.to_dict() if snap.exists else None
            updated, result = transition(previous, self.clock())
            if updated != previous:
                transaction.set(ref, updated)
            return result

        return run(self.client.transaction(max_attempts=5))

    def claim(self, *, business_date, execution, task_attempt, source_object,
              source_generation, operator_backfill=False):
        return self._change(business_date, lambda previous, now: state.claim(
            previous, business_date=business_date, now=now, execution=execution,
            task_attempt=task_attempt, source_object=source_object,
            source_generation=source_generation, operator_backfill=operator_backfill))

    def mark_missing_input(self, business_date):
        return self._change(business_date, lambda previous, now: state.mark_missing_input(
            previous, business_date=business_date, now=now))

    def _apply(self, business_date, transition):
        def apply(previous, now):
            if previous is None:
                raise state.StateConflict("ledger_not_found")
            updated = transition(previous, now)
            return updated, updated
        return self._change(business_date, apply)

    def block_invalid_source(self, business_date, token, *, code):
        return self._apply(business_date, lambda record, now:
            state.block_invalid_source(record, token, now=now, code=code))

    def record_report(self, business_date, token, *, report):
        return self._apply(business_date, lambda record, now:
            state.record_report(record, token, now=now, report=report))

    def mark_notification_pending(self, business_date, token, *, report_id):
        return self._apply(business_date, lambda record, now:
            state.mark_notification_pending(record, token, now=now, report_id=report_id))

    def mark_succeeded(self, business_date, token, *, report_id):
        return self._apply(business_date, lambda record, now:
            state.mark_succeeded(record, token, now=now, report_id=report_id))

    def release_attempt(self, business_date, token, *, reason):
        return self._apply(business_date, lambda record, now:
            state.release_attempt(record, token, now=now, reason=reason))
