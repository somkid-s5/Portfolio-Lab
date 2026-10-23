"""Firestore transaction adapter. Storage effects must happen outside callbacks."""
from datetime import datetime, timezone
import re
import hashlib
import json
import uuid
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


    def create(self, owner, key, display_name, *, max_bytes=1048576,
               max_rows=10000, processor_version="v1"):
        """Atomically reserve bounded quota and create or replay one logical job."""
        if (not isinstance(owner, str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", owner)):
            raise ValueError("invalid_owner")
        if (not isinstance(key, str) or
                not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", key)):
            raise ValueError("invalid_idempotency_key")
        if (not isinstance(display_name, str) or not 1 <= len(display_name) <= 128 or
                any(ord(c) < 32 or ord(c) == 127 or c in "/\\" for c in display_name)):
            raise ValueError("invalid_display_name")
        # Validate limits before entering the SDK callback.
        job_id = uuid.uuid4().hex
        job_state.new_job(job_id, owner, self.clock(), max_bytes=max_bytes,
                          max_rows=max_rows, processor_version=processor_version)
        fingerprint = hashlib.sha256(json.dumps(
            [display_name, max_bytes, max_rows, processor_version],
            separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        record_id = hashlib.sha256((owner + "\0" + key).encode()).hexdigest()
        record_ref = self.client.collection("idempotency").document(record_id)
        quota_ref = self.client.collection("owner_quotas").document(owner)
        target_ref = self._ref(job_id)

        @firestore.transactional
        def create_once(transaction):
            now = self.clock()
            existing = record_ref.get(transaction=transaction, timeout=10)
            if existing.exists:
                record = existing.to_dict()
                if record["fingerprint"] != fingerprint:
                    raise job_state.Conflict("idempotency_conflict")
                original = self._ref(record["job_id"]).get(
                    transaction=transaction, timeout=10)
                if not original.exists or now >= record["delete_after"]:
                    raise job_state.Conflict("idempotency_record_expired")
                item = original.to_dict()
                if item["owner"] != owner:
                    raise job_state.Conflict("idempotency_integrity")
                return {"job": item, "replayed": True}
            quota_snapshot = quota_ref.get(transaction=transaction, timeout=10)
            quota = quota_snapshot.to_dict() if quota_snapshot.exists else {}
            active_ids = quota.get("active_ids", [])
            if len(active_ids) > 5:
                raise job_state.Conflict("quota_integrity")
            active = []
            for active_id in active_ids:
                snapshot = self._ref(active_id).get(transaction=transaction, timeout=10)
                if not snapshot.exists:
                    continue
                item = snapshot.to_dict()
                if item["owner"] != owner:
                    raise job_state.Conflict("quota_integrity")
                expired = now >= item["expires_at"]
                if item["state"] not in job_state.TERMINAL and not expired:
                    active.append(active_id)
            day = now.strftime("%Y-%m-%d")
            daily_count = quota.get("daily_count", 0) if quota.get("day") == day else 0
            if len(active) >= 5 or daily_count >= 20:
                raise job_state.Conflict("job_quota_exceeded")
            candidate = target_ref.get(transaction=transaction, timeout=10)
            if candidate.exists:
                raise job_state.Conflict("job_id_collision")
            job = job_state.new_job(job_id, owner, now, max_bytes=max_bytes,
                                    max_rows=max_rows,
                                    processor_version=processor_version)
            job["display_name"] = display_name
            transaction.create(target_ref, job)
            transaction.create(record_ref, {"owner": owner, "job_id": job_id,
                                           "fingerprint": fingerprint,
                                           "delete_after": job["delete_after"]})
            transaction.set(quota_ref, {"day": day, "daily_count": daily_count + 1,
                                       "active_ids": active + [job_id],
                                       "delete_after": job["delete_after"]})
            return {"job": job, "replayed": False}

        return create_once(self.client.transaction(max_attempts=5))
