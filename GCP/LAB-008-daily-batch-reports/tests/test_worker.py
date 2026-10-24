"""End-to-end worker state/data-flow tests with deterministic cloud-adapter doubles."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations import PublishUncertain
from app.ledger_state import (LEASE, StateConflict, block_invalid_source, claim,
                              mark_missing_input, mark_notification_pending,
                              mark_succeeded, new_record, record_report,
                              release_attempt)
from app.storage import ArtifactConflict, InvalidSource, SourceChanged, SourceMissing
from app.worker import DailyReportWorker, WorkerFailure


DAY = "2026-10-23"
SOURCE = f"incoming/business_date={DAY}/transactions.csv"
CORRECTION = f"incoming/business_date={DAY}/corrections/repair-1.csv"
NOW = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
FIXTURE = (Path(__file__).resolve().parents[1] / "fixtures" / "transactions.csv").read_bytes()


class InMemoryLedger:
    def __init__(self, clock):
        self.clock, self.record = clock, None

    def _now(self):
        return self.clock()

    def claim(self, **kwargs):
        self.record, disposition, token = claim(
            self.record, business_date=kwargs["business_date"], now=self._now(),
            execution=kwargs["execution"], task_attempt=kwargs["task_attempt"],
            source_object=kwargs["source_object"], source_generation=kwargs["source_generation"],
            operator_backfill=kwargs.get("operator_backfill", False))
        return self.record, disposition, token

    def mark_missing_input(self, business_date):
        self.record, disposition = mark_missing_input(
            self.record, business_date=business_date, now=self._now())
        return self.record, disposition

    def block_invalid_source(self, business_date, token, *, code):
        self.record = block_invalid_source(self.record, token, now=self._now(), code=code)
        return self.record

    def record_report(self, business_date, token, *, report):
        self.record = record_report(self.record, token, now=self._now(), report=report)
        return self.record

    def mark_notification_pending(self, business_date, token, *, report_id):
        self.record = mark_notification_pending(
            self.record, token, now=self._now(), report_id=report_id)
        return self.record

    def mark_succeeded(self, business_date, token, *, report_id):
        self.record = mark_succeeded(self.record, token, now=self._now(), report_id=report_id)
        return self.record

    def release_attempt(self, business_date, token, *, reason):
        self.record = release_attempt(self.record, token, now=self._now(), reason=reason)
        return self.record

    def read(self, business_date):
        return self.record


class InMemoryObjects:
    def __init__(self):
        self.sources = {}
        self.outputs = {}
        self.output_generation = 700
        self.mutate_after_pin = False
        self.create_count = 0

    @staticmethod
    def default_source(business_date):
        return f"incoming/business_date={business_date}/transactions.csv"

    @staticmethod
    def report_name(business_date):
        return f"reports/business_date={business_date}/summary.json"

    def add_source(self, name, generation, data, content_type="text/csv"):
        self.sources[name] = {
            "generation": str(generation), "data": data, "content_type": content_type,
        }

    def source_generation(self, object_name, *, business_date):
        item = self.sources.get(object_name)
        if item is None:
            raise SourceMissing()
        return item["generation"]

    def read_source(self, object_name, generation, *, business_date):
        item = self.sources.get(object_name)
        if item is None:
            raise SourceMissing()
        if item["generation"] != str(generation):
            raise SourceChanged()
        if item["content_type"] != "text/csv":
            raise InvalidSource("INVALID_CONTENT_TYPE")
        if self.mutate_after_pin:
            raise SourceChanged()
        return item["data"]

    def create_report(self, business_date, body, *, source_generation,
                      source_sha256, report_id):
        name = self.report_name(business_date)
        output_sha = hashlib.sha256(body).hexdigest()
        expected = {
            "object": name, "sha256": output_sha, "report_id": report_id,
            "source_generation": source_generation, "source_sha256": source_sha256,
        }
        existing = self.outputs.get(name)
        if existing is not None:
            previous = existing["metadata"]
            if (existing["body"] != body or any(
                    previous.get(key) != value for key, value in expected.items())):
                raise ArtifactConflict("existing_report_mismatch")
            return dict(previous)
        metadata = {**expected, "generation": str(self.output_generation)}
        self.output_generation += 1
        self.create_count += 1
        self.outputs[name] = {"body": body, "metadata": dict(metadata)}
        return metadata


class FakePublisher:
    def __init__(self, fail_count=0):
        self.fail_count = fail_count
        self.events = []
    def publish(self, report):
        self.events.append(dict(report))
        if self.fail_count:
            self.fail_count -= 1
            raise PublishUncertain()
        return f"message-{len(self.events)}"


class SimulatedCrash(RuntimeError):
    pass


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.clock = lambda: self.now
        self.ledger = InMemoryLedger(self.clock)
        self.objects = InMemoryObjects()
        self.publisher = FakePublisher()
        self.objects.add_source(SOURCE, "101", FIXTURE)
        self.worker = DailyReportWorker(ledger=self.ledger, objects=self.objects,
                                        publisher=self.publisher, clock=self.clock)

    def run_job(self, *, execution="exec-1", task_attempt=0, mode="scheduled",
                source_object=None, source_generation=None, worker=None):
        return (worker or self.worker).run(
            business_date=DAY, execution=execution, task_attempt=task_attempt,
            mode=mode, source_object=source_object, source_generation=source_generation)

    def test_success_builds_source_bound_artifact_then_publishes(self):
        result = self.run_job()
        self.assertEqual(result["status"], "succeeded")
        record = self.ledger.read(DAY)
        self.assertEqual(record["status"], "succeeded")
        self.assertEqual(record["source_generation"], "101")
        self.assertEqual(record["report_generation"], "700")
        self.assertEqual(len(self.objects.outputs), 1)
        body = next(iter(self.objects.outputs.values()))["body"]
        report = json.loads(body)
        self.assertEqual(report["row_count"], 4)
        self.assertEqual(report["total_amount_minor"], 79000)
        self.assertEqual(len(self.publisher.events), 1)
        self.assertEqual(self.publisher.events[0]["report_id"], report["report_id"])

    def test_duplicate_succeeded_invocation_has_no_side_effects(self):
        first = self.run_job()
        result = self.run_job(execution="duplicate")
        self.assertEqual(first["report_id"], result["report_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.objects.create_count, 1)
        self.assertEqual(len(self.publisher.events), 1)

    def test_missing_source_records_missing_input_without_empty_output(self):
        self.objects.sources.clear()
        result = self.run_job()
        self.assertEqual(result["status"], "missing_input")
        self.assertEqual(self.ledger.read(DAY)["status"], "missing_input")
        self.assertEqual(self.objects.outputs, {})
        self.assertEqual(self.publisher.events, [])

    def test_invalid_csv_blocks_ledger_without_report_or_notification(self):
        self.objects.add_source(SOURCE, "101", b"not,the,expected,header\n")
        result = self.run_job()
        self.assertEqual((result["status"], result["validation_code"]),
                         ("blocked", "INVALID_HEADER"))
        self.assertEqual(self.ledger.read(DAY)["safe_reason"], "invalid_source")
        self.assertEqual(self.objects.outputs, {})
        self.assertEqual(self.publisher.events, [])

    def test_invalid_source_can_be_corrected_only_with_explicit_operator_backfill(self):
        self.objects.add_source(SOURCE, "101", b"bad\n")
        self.assertEqual(self.run_job()["status"], "blocked")
        self.objects.add_source(CORRECTION, "202", FIXTURE)
        result = self.run_job(mode="operator-backfill", source_object=CORRECTION,
                              source_generation="202")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.ledger.read(DAY)["source_object"], CORRECTION)
        self.assertEqual(self.ledger.read(DAY)["source_generation"], "202")

    def test_lost_worker_after_report_record_recovers_without_rewrite(self):
        def crash(_artifact):
            raise SimulatedCrash("process stopped after report write")
        crashing = DailyReportWorker(ledger=self.ledger, objects=self.objects,
            publisher=self.publisher, clock=self.clock, after_report_recorded=crash)
        with self.assertRaises(SimulatedCrash):
            self.run_job(worker=crashing)
        self.assertEqual(self.ledger.read(DAY)["status"], "report_written")
        self.assertEqual(self.objects.create_count, 1)
        self.assertEqual(self.publisher.events, [])
        result = self.run_job(task_attempt=1)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.objects.create_count, 1)
        self.assertEqual(len(self.publisher.events), 1)

    def test_uncertain_publish_retries_same_event_identity(self):
        self.publisher.fail_count = 1
        with self.assertRaisesRegex(WorkerFailure, "notification_publish_uncertain"):
            self.run_job()
        self.assertEqual(self.ledger.read(DAY)["status"], "notification_pending")
        self.assertEqual(self.ledger.read(DAY)["safe_reason"], "transient_publish")
        result = self.run_job(task_attempt=1)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.publisher.events[0]["report_id"],
                         self.publisher.events[1]["report_id"])
        self.assertEqual(self.objects.create_count, 1)

    def test_live_independent_claim_is_busy_without_side_effect(self):
        self.ledger.claim(business_date=DAY, execution="owner", task_attempt=0,
            source_object=SOURCE, source_generation="101", operator_backfill=False)
        result = self.run_job(execution="other")
        self.assertEqual(result["status"], "busy")
        self.assertEqual(self.objects.outputs, {})
        self.assertEqual(self.publisher.events, [])

    def test_explicit_missing_correction_does_not_mutate_daily_ledger(self):
        with self.assertRaisesRegex(WorkerFailure, "correction_source_missing"):
            self.run_job(mode="operator-backfill", source_object=CORRECTION,
                         source_generation="999")
        self.assertIsNone(self.ledger.read(DAY))

    def test_changed_pinned_source_releases_attempt_and_fails_safe(self):
        self.objects.mutate_after_pin = True
        with self.assertRaisesRegex(WorkerFailure, "source_generation_unavailable"):
            self.run_job()
        self.assertEqual(self.ledger.read(DAY)["status"], "failed")
        self.assertEqual(self.ledger.read(DAY)["safe_reason"], "dependency_failure")
        self.assertEqual(self.publisher.events, [])

    def test_mode_and_schedule_overrides_are_guarded(self):
        with self.assertRaisesRegex(ValueError, "invalid_run_mode"):
            self.run_job(mode="administrator")
        with self.assertRaisesRegex(ValueError, "scheduled_source_override_forbidden"):
            self.run_job(source_object=SOURCE, source_generation="101")
        with self.assertRaisesRegex(ValueError, "correction_source_pair_required"):
            self.run_job(mode="operator-backfill", source_object=CORRECTION)

    def test_operator_backfill_window_is_enforced_in_worker(self):
        old_worker = DailyReportWorker(ledger=self.ledger, objects=self.objects,
            publisher=self.publisher, clock=lambda: NOW + timedelta(days=8))
        with self.assertRaisesRegex(ValueError, "backfill_outside_seven_day_window"):
            self.run_job(mode="operator-backfill", worker=old_worker)


if __name__ == "__main__":
    unittest.main()
