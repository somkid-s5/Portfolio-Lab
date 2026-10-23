"""Firestore transaction adapter. Storage effects must happen outside callbacks."""
from datetime import datetime, timezone
import re
from google.cloud import firestore
import job_state


class Jobs:
    def __init__(self, client, *, clock=None):
        self.client = client
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _ref(self, job_id):
        if not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise ValueError("invalid_job_id")
        return self.client.collection("jobs").document(job_id)

    def read_owned(self, job_id, owner):
        snapshot = self._ref(job_id).get(timeout=10)
        if not snapshot.exists or snapshot.to_dict()["owner"] != owner:
            raise KeyError("job_not_found")
        return snapshot.to_dict()

    def _change(self, job_id, transition):
        ref = self._ref(job_id)

        @firestore.transactional
        def change(transaction):
            snapshot = ref.get(transaction=transaction, timeout=10)
            if not snapshot.exists:
                raise KeyError("job_not_found")
            previous = snapshot.to_dict()
            # Refresh UTC time on every SDK transaction retry.
            updated, result = transition(previous, self.clock())
            if updated != previous:
                transaction.set(ref, updated)
            return result

        return change(self.client.transaction(max_attempts=5))

    def claim(self, job_id, generation, token, *, finalized_at):
        def transition(previous, now):
            updated, disposition = job_state.claim(
                previous, generation, token, now, finalized_at=finalized_at)
            return updated, {"disposition": disposition, "job": updated}
        return self._change(job_id, transition)

    def finish(self, job_id, token, *, output=None, reason=None):
        def transition(previous, now):
            updated = job_state.finish(previous, token, now,
                                       output=output, reason=reason)
            return updated, updated
        return self._change(job_id, transition)

    def release_transient(self, job_id, token):
        def transition(previous, now):
            updated = job_state.release_transient(previous, token, now)
            return updated, updated
        return self._change(job_id, transition)

    def operator_retry(self, job_id):
        # Caller must enforce operator authentication/CSRF before this method.
        def transition(previous, now):
            updated = job_state.operator_retry(previous, now)
            return updated, updated
        return self._change(job_id, transition)
