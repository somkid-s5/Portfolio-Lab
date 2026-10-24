"""Pure transition tests for the Firestore daily-run ledger."""
from datetime import datetime, timedelta, timezone
import unittest

from app.ledger_state import (LEASE, StateConflict, block_invalid_source, claim,
                              mark_missing_input, mark_notification_pending,
                              mark_succeeded, new_record, record_report,
                              release_attempt)

NOW = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
DAY = "2026-10-23"
SOURCE = f"incoming/business_date={DAY}/transactions.csv"
CORRECTED = f"incoming/business_date={DAY}/corrections/repair-01.csv"


def claim_first(execution="exec-1", attempt=0, **kwargs):
    return claim(None, business_date=DAY, now=NOW, execution=execution,
                 task_attempt=attempt, source_object=SOURCE,
                 source_generation="101", **kwargs)


def report_for(record):
    return {
        "object": f"reports/business_date={DAY}/summary.json",
        "generation": "202",
        "sha256": "a" * 64,
        "report_id": "b" * 64,
        "source_generation": record["source_generation"],
        "source_sha256": "c" * 64,
    }


class LedgerStateTests(unittest.TestCase):
    def test_claim_creates_source_bound_lease_and_fence(self):
        record, disposition, token = claim_first()
        self.assertEqual(disposition, "claimed")
        self.assertEqual((record["status"], record["fence"], record["source_object"]),
                         ("running", 1, SOURCE))
        self.assertEqual(record["lease_until"], NOW + LEASE)
        self.assertEqual(token, {"execution": "exec-1", "task_attempt": 0, "fence": 1})

    def test_independent_execution_cannot_claim_live_lease(self):
        record, _, _ = claim_first()
        contender, disposition, token = claim(record, business_date=DAY,
            now=NOW + timedelta(seconds=1), execution="exec-2", task_attempt=0,
            source_object=SOURCE, source_generation="101")
        self.assertEqual(disposition, "busy")
        self.assertIsNone(token)
        self.assertEqual(contender["fence"], 1)

    def test_cloud_run_retry_increments_fence_and_stales_previous_attempt(self):
        record, _, old = claim_first()
        retry, disposition, current = claim(record, business_date=DAY,
            now=NOW + timedelta(seconds=30), execution="exec-1", task_attempt=1,
            source_object=SOURCE, source_generation="101")
        self.assertEqual(disposition, "claimed")
        self.assertEqual(retry["fence"], 2)
        with self.assertRaisesRegex(StateConflict, "stale_fence"):
            record_report(retry, old, now=NOW + timedelta(seconds=31),
                          report=report_for(retry))
        self.assertEqual(record_report(retry, current, now=NOW + timedelta(seconds=31),
                                        report=report_for(retry))["status"], "report_written")

    def test_expired_lease_is_reclaimed_with_new_fence(self):
        record, _, token = claim_first()
        reclaimed, disposition, new_token = claim(record, business_date=DAY,
            now=NOW + LEASE, execution="exec-2", task_attempt=0,
            source_object=SOURCE, source_generation="101")
        self.assertEqual((disposition, reclaimed["fence"]), ("claimed", 2))
        with self.assertRaisesRegex(StateConflict, "stale_fence"):
            release_attempt(reclaimed, token, now=NOW + LEASE,
                            reason="dependency_failure")
        self.assertEqual(new_token["execution"], "exec-2")

    def test_report_notification_state_machine_and_stable_event_identity(self):
        record, _, token = claim_first()
        report = report_for(record)
        record = record_report(record, token, now=NOW, report=report)
        self.assertEqual(record["status"], "report_written")
        pending = mark_notification_pending(record, token, now=NOW, report_id="b"*64)
        self.assertEqual((pending["status"], pending["notification_state"]),
                         ("notification_pending", "pending"))
        same = mark_notification_pending(pending, token, now=NOW, report_id="b"*64)
        self.assertEqual(same, pending)
        done = mark_succeeded(pending, token, now=NOW, report_id="b"*64)
        self.assertEqual((done["status"], done["notification_state"]),
                         ("succeeded", "published"))
        again, disposition, no_token = claim(done, business_date=DAY, now=NOW,
            execution="exec-2", task_attempt=0, source_object=SOURCE,
            source_generation="999", operator_backfill=True)
        self.assertEqual((disposition, no_token, again["report_generation"]),
                         ("succeeded", None, "202"))

    def test_wrong_report_binding_cannot_advance_ledger(self):
        record, _, token = claim_first()
        report = report_for(record)
        report["object"] = "reports/business_date=2026-10-22/summary.json"
        with self.assertRaisesRegex(StateConflict, "report_binding_mismatch"):
            record_report(record, token, now=NOW, report=report)

    def test_report_conflict_is_not_overwritten_by_retry(self):
        record, _, token = claim_first()
        report = report_for(record)
        written = record_report(record, token, now=NOW, report=report)
        again = record_report(written, token, now=NOW, report=report)
        self.assertEqual(again["report_generation"], "202")
        conflict = dict(report, sha256="d"*64)
        with self.assertRaisesRegex(StateConflict, "report_integrity_conflict"):
            record_report(written, token, now=NOW, report=conflict)

    def test_invalid_input_blocks_and_only_operator_correction_can_replace_binding(self):
        record, _, token = claim_first()
        blocked = block_invalid_source(record, token, now=NOW, code="INVALID_HEADER")
        self.assertEqual((blocked["status"], blocked["validation_code"]),
                         ("blocked", "INVALID_HEADER"))
        with self.assertRaisesRegex(StateConflict, "source_binding_conflict"):
            claim(blocked, business_date=DAY, now=NOW, execution="manual-1",
                  task_attempt=0, source_object=CORRECTED,
                  source_generation="303")
        corrected, disposition, _ = claim(blocked, business_date=DAY, now=NOW,
            execution="manual-1", task_attempt=0, source_object=CORRECTED,
            source_generation="303", operator_backfill=True)
        self.assertEqual((disposition, corrected["status"], corrected["fence"]),
                         ("claimed", "running", 2))

    def test_correction_source_must_be_date_scoped_and_report_must_not_exist(self):
        record, _, token = claim_first()
        blocked = block_invalid_source(record, token, now=NOW, code="INVALID_HEADER")
        with self.assertRaisesRegex(StateConflict, "invalid_source_object"):
            claim(blocked, business_date=DAY, now=NOW, execution="manual-1",
                  task_attempt=0,
                  source_object="incoming/business_date=2026-10-22/corrections/fix.csv",
                  source_generation="303", operator_backfill=True)
        record, _, token = claim_first()
        blocked = block_invalid_source(record, token, now=NOW, code="INVALID_HEADER")
        # A validly bound correction name is still rejected if any output exists.
        blocked.update(report_generation="202")
        with self.assertRaisesRegex(StateConflict, "source_binding_conflict"):
            claim(blocked, business_date=DAY, now=NOW, execution="manual-1",
                  task_attempt=0, source_object=CORRECTED,
                  source_generation="303", operator_backfill=True)

    def test_missing_input_can_be_recovered_after_upload(self):
        missing, disposition = mark_missing_input(None, business_date=DAY, now=NOW)
        self.assertEqual((disposition, missing["status"]), ("missing_input", "missing_input"))
        started, disposition, _ = claim(missing, business_date=DAY, now=NOW,
            execution="exec-after-upload", task_attempt=0, source_object=SOURCE,
            source_generation="101")
        self.assertEqual((disposition, started["status"]), ("claimed", "running"))

    def test_active_work_cannot_be_replaced_by_missing_input_observation(self):
        record, _, _ = claim_first()
        same, disposition = mark_missing_input(record, business_date=DAY,
            now=NOW + timedelta(seconds=1))
        self.assertEqual((disposition, same["status"]), ("busy", "running"))

    def test_transient_failure_requires_operator_or_cloud_run_retry(self):
        record, _, token = claim_first()
        failed = release_attempt(record, token, now=NOW, reason="dependency_failure")
        self.assertEqual((failed["status"], failed["safe_reason"]), ("failed", "dependency_failure"))
        again, disposition, _ = claim(failed, business_date=DAY,
            now=NOW + timedelta(seconds=1), execution="manual-run", task_attempt=0,
            source_object=SOURCE, source_generation="101")
        self.assertEqual(disposition, "needs_operator")
        recovered, disposition, _ = claim(failed, business_date=DAY,
            now=NOW + timedelta(seconds=1), execution="manual-run", task_attempt=0,
            source_object=SOURCE, source_generation="101", operator_backfill=True)
        self.assertEqual((disposition, recovered["status"]), ("claimed", "running"))

    def test_failure_after_report_write_preserves_recovery_phase(self):
        record, _, token = claim_first()
        written = record_report(record, token, now=NOW, report=report_for(record))
        released = release_attempt(written, token, now=NOW,
                                   reason="transient_publish")
        self.assertEqual(released["status"], "report_written")
        again, disposition, _ = claim(released, business_date=DAY,
            now=NOW + timedelta(seconds=1), execution="manual-run", task_attempt=0,
            source_object=SOURCE, source_generation="101", operator_backfill=True)
        self.assertEqual((disposition, again["status"]), ("claimed", "report_written"))

    def test_history_is_bounded_and_contains_no_fence_token(self):
        record, _, token = claim_first()
        for i in range(120):
            now = NOW + timedelta(seconds=i)
            record, _, token = claim(record, business_date=DAY, now=now,
                execution=f"exec-{i}", task_attempt=0, source_object=SOURCE,
                source_generation="101")
            if i < 119:
                record = release_attempt(record, token, now=now,
                                         reason="dependency_failure")
        self.assertEqual(len(record["history"]), 100)
        self.assertTrue(record["history_truncated"])
        self.assertNotIn("attempt_token", str(record["history"]))

    def test_rejects_non_utc_time_attempt_overrides_and_invalid_sources(self):
        with self.assertRaisesRegex(StateConflict, "utc_time_required"):
            new_record(DAY, datetime(2026, 10, 24))
        with self.assertRaisesRegex(StateConflict, "invalid_task_attempt"):
            claim(None, business_date=DAY, now=NOW, execution="exec", task_attempt=True,
                  source_object=SOURCE, source_generation="101")
        with self.assertRaisesRegex(StateConflict, "invalid_business_date"):
            new_record("2026-2-3", NOW)
        with self.assertRaisesRegex(StateConflict, "invalid_source_generation"):
            claim(None, business_date=DAY, now=NOW, execution="exec", task_attempt=0,
                  source_object=SOURCE, source_generation="0")


if __name__ == "__main__":
    unittest.main()
