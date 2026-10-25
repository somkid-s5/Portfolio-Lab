"""Coordinator HTTP contract tests with injected in-memory dependencies."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.coordinator import CoordinatorDependencies, create_app
from app.storage import ArtifactConflict, SourceMissing

SCHEDULE_TIME = "2026-10-24T01:15:00+07:00"
REPORT_JOB = "projects/demo-lab008/locations/asia-southeast1/jobs/lab008-report-schedule"
WATCHDOG_JOB = "projects/demo-lab008/locations/asia-southeast1/jobs/lab008-watchdog"


def scheduler_headers(job=REPORT_JOB, schedule_time=SCHEDULE_TIME):
    return {
        "X-CloudScheduler": "true",
        "X-CloudScheduler-JobName": job,
        "X-CloudScheduler-ScheduleTime": schedule_time,
    }


class FakeRunner:
    def __init__(self, operation="projects/demo-lab008/locations/asia-southeast1/operations/op-1",
                 error=None):
        self.operation, self.error, self.dates = operation, error, []
    def run_scheduled(self, business_date):
        self.dates.append(business_date)
        if self.error:
            raise self.error
        return self.operation


class FakeLedger:
    def __init__(self, record=None, error=None):
        self.record, self.error, self.dates = record, error, []
    def read(self, business_date):
        self.dates.append(business_date)
        if self.error:
            raise self.error
        return self.record


class FakeObjects:
    def __init__(self, outcome=None):
        self.outcome, self.calls = outcome, []
    def verify_report(self, object_name, generation, *, expected_sha256, expected_metadata):
        self.calls.append((object_name, generation, expected_sha256, expected_metadata))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return b'{"ok":true}'


GOOD_RECORD = {
    "business_date": "2026-10-23",
    "status": "succeeded",
    "report_object": "reports/business_date=2026-10-23/summary.json",
    "report_generation": "456",
    "report_sha256": "a" * 64,
    "report_id": "b" * 64,
    "source_generation": "123",
    "source_sha256": "c" * 64,
}


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.runner = FakeRunner()
        self.ledger = FakeLedger()
        self.objects = FakeObjects()
        self.app = create_app(CoordinatorDependencies(
            self.runner, self.ledger, self.objects, REPORT_JOB, WATCHDOG_JOB,
            event_sink=self.events.append,
        ))
        self.app.testing = True
        self.client = self.app.test_client()

    def test_healthcheck_has_no_cloud_side_effects(self):
        response = self.client.get("/healthz")
        self.assertEqual((response.status_code, response.json), (200, {"ok": True}))
        self.assertEqual(self.runner.dates, [])
        self.assertEqual(self.ledger.dates, [])

    def test_schedule_uses_logical_date_and_returns_async_operation(self):
        response = self.client.post("/schedule", headers=scheduler_headers())
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json, {
            "accepted": True,
            "business_date": "2026-10-23",
            "operation": self.runner.operation,
        })
        self.assertEqual(self.runner.dates, ["2026-10-23"])

    def test_schedule_rejects_wrong_job_and_invalid_time_before_starting_job(self):
        response = self.client.post("/schedule",
            headers=scheduler_headers(job=WATCHDOG_JOB))
        self.assertEqual((response.status_code, response.json["error"]),
                         (403, "UNEXPECTED_SCHEDULER_JOB"))
        response = self.client.post("/schedule",
            headers=scheduler_headers(schedule_time="2026-13-40T01:15:00+07:00"))
        self.assertEqual((response.status_code, response.json["error"]),
                         (400, "INVALID_SCHEDULE_TIME"))
        self.assertEqual(self.runner.dates, [])

    def test_schedule_api_failure_is_retryable_and_logs_safe_reason(self):
        self.runner.error = RuntimeError("sensitive response body")
        response = self.client.post("/schedule", headers=scheduler_headers())
        self.assertEqual((response.status_code, response.json["error"]),
                         (503, "RUN_API_UNAVAILABLE"))
        self.assertEqual(self.events, [{
            "event": "daily_job_start_failed",
            "business_date": "2026-10-23",
            "reason": "run_api_unavailable",
        }])
        self.assertNotIn("sensitive", repr(self.events))

    def test_watchdog_missing_ledger_is_business_not_ready_not_http_failure(self):
        response = self.client.post("/watchdog",
            headers=scheduler_headers(job=WATCHDOG_JOB))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.events[0], {
            "event": "daily_report_not_ready",
            "business_date": "2026-10-23",
            "status": "not_started",
            "reason": "ledger_not_found",
        })
        self.assertEqual(self.objects.calls, [])

    def test_watchdog_non_success_logs_recorded_safe_state(self):
        self.ledger.record = {"status": "missing_input", "safe_reason": "missing_input"}
        response = self.client.post("/watchdog",
            headers=scheduler_headers(job=WATCHDOG_JOB))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.events[0]["reason"], "missing_input")
        self.assertEqual(self.objects.calls, [])

    def test_watchdog_verifies_report_generation_hash_and_source_binding(self):
        self.ledger.record = dict(GOOD_RECORD)
        response = self.client.post("/watchdog",
            headers=scheduler_headers(job=WATCHDOG_JOB))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.objects.calls, [(
            GOOD_RECORD["report_object"], "456", "a" * 64, {
                "report_id": "b" * 64,
                "source_generation": "123",
                "source_sha256": "c" * 64,
            },
        )])
        self.assertEqual(self.events[0]["event"], "daily_report_ready_verified")

    def test_watchdog_artifact_missing_or_corrupt_emits_alert_event(self):
        for error, reason in ((SourceMissing(), "report_missing"),
                              (ArtifactConflict("tampered"), "report_integrity")):
            with self.subTest(reason=reason):
                self.events.clear()
                self.objects.outcome = error
                self.ledger.record = dict(GOOD_RECORD)
                response = self.client.post("/watchdog",
                    headers=scheduler_headers(job=WATCHDOG_JOB))
                self.assertEqual(response.status_code, 204)
                self.assertEqual(self.events[0]["reason"], reason)

    def test_watchdog_dependency_failure_is_retryable(self):
        self.ledger.error = RuntimeError("internal detail")
        response = self.client.post("/watchdog",
            headers=scheduler_headers(job=WATCHDOG_JOB))
        self.assertEqual((response.status_code, response.json["error"]),
                         (503, "WATCHDOG_DEPENDENCY_UNAVAILABLE"))
        self.assertEqual(self.events[0]["reason"], "dependency_unavailable")
        self.assertNotIn("internal detail", repr(self.events))


if __name__ == "__main__":
    unittest.main()
