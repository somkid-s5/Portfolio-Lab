"""Cloud Run Jobs and Pub/Sub adapter tests; all network boundaries are fakes."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo
import unittest

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.integrations import (CloudRunJobRunner, JobRequestError,
                              PublishUncertain, ReportReadyPublisher)


class FakeResponse:
    def __init__(self, body=None, error=None):
        self.body, self.error = body, error
    def raise_for_status(self):
        if self.error:
            raise self.error
    def json(self):
        return self.body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class FakeFuture:
    def __init__(self, message_id=None, error=None):
        self.message_id, self.error = message_id, error
        self.timeout = None
    def result(self, timeout=None):
        self.timeout = timeout
        if self.error:
            raise self.error
        return self.message_id


class FakePublisher:
    def __init__(self, future=None):
        self.future = future or FakeFuture("message-123")
        self.calls = []
    def publish(self, topic, data, **attributes):
        self.calls.append((topic, data, attributes))
        return self.future


REPORT = {
    "object": "reports/business_date=2026-10-23/summary.json",
    "generation": "456",
    "sha256": "a" * 64,
    "report_id": "b" * 64,
    "source_generation": "123",
    "source_sha256": "c" * 64,
}


class CloudRunJobTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession(FakeResponse({
            "name": "projects/demo-lab008/locations/asia-southeast1/operations/op-123"
        }))
        self.runner = CloudRunJobRunner(
            self.session, project="demo-lab008", region="asia-southeast1",
            job="lab008-daily-report",
            clock=lambda: datetime(2026, 10, 24, 1, tzinfo=ZoneInfo("Asia/Bangkok")),
        )

    def test_schedule_calls_v2_run_with_only_date_argument(self):
        operation = self.runner.run_scheduled("2026-10-23")
        self.assertEqual(operation, "projects/demo-lab008/locations/asia-southeast1/operations/op-123")
        url, kwargs = self.session.calls[0]
        self.assertEqual(url, "https://run.googleapis.com/v2/projects/demo-lab008/locations/asia-southeast1/jobs/lab008-daily-report:run")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(kwargs["json"], {"overrides": {"containerOverrides": [
            {"args": ["--business-date=2026-10-23"]}
        ]}})

    def test_backfill_is_bounded_and_correction_source_requires_pair(self):
        op = self.runner.run_operator_backfill("2026-10-17")
        self.assertTrue(op.endswith("/op-123"))
        args = self.session.calls[-1][1]["json"]["overrides"]["containerOverrides"][0]["args"]
        self.assertEqual(args, ["--mode=operator-backfill", "--business-date=2026-10-17"])
        with self.assertRaisesRegex(ValueError, "correction_source_pair_required"):
            self.runner.run_operator_backfill("2026-10-17", source_object=
                "incoming/business_date=2026-10-17/corrections/repair.csv")
        self.runner.run_operator_backfill(
            "2026-10-17",
            source_object="incoming/business_date=2026-10-17/corrections/repair-1.csv",
            source_generation="123",
        )
        args = self.session.calls[-1][1]["json"]["overrides"]["containerOverrides"][0]["args"]
        self.assertEqual(args[-2:], [
            "--source-object=incoming/business_date=2026-10-17/corrections/repair-1.csv",
            "--source-generation=123",
        ])

    def test_rejects_future_current_expired_and_invalid_dates(self):
        for value in ("2026-10-24", "2026-10-25", "2026-10-16", "2026-02-30"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.runner.run_operator_backfill(value)
        with self.assertRaisesRegex(ValueError, "invalid_business_date"):
            self.runner.run_scheduled("2026-10-3")

    def test_rejects_correction_from_other_date_or_invalid_generation(self):
        with self.assertRaisesRegex(ValueError, "invalid_correction_source"):
            self.runner.run_operator_backfill(
                "2026-10-17",
                source_object="incoming/business_date=2026-10-16/corrections/repair.csv",
                source_generation="123",
            )
        with self.assertRaisesRegex(ValueError, "invalid_source_generation"):
            self.runner.run_operator_backfill(
                "2026-10-17",
                source_object="incoming/business_date=2026-10-17/corrections/repair.csv",
                source_generation="latest",
            )

    def test_api_failure_and_untrusted_operation_response_are_safe(self):
        session = FakeSession(FakeResponse(error=RuntimeError("private response body")))
        runner = CloudRunJobRunner(session, project="demo-lab008",
            region="asia-southeast1", job="lab008-daily-report")
        with self.assertRaisesRegex(JobRequestError, "RUN_API_UNAVAILABLE"):
            runner.run_scheduled("2026-10-23")
        self.assertNotIn("private response body", str(JobRequestError("RUN_API_UNAVAILABLE")))
        session = FakeSession(FakeResponse({"name": "projects/other/operations/op"}))
        runner = CloudRunJobRunner(session, project="demo-lab008",
            region="asia-southeast1", job="lab008-daily-report")
        with self.assertRaisesRegex(JobRequestError, "RUN_API_INVALID_RESPONSE"):
            runner.run_scheduled("2026-10-23")


class PubSubPublisherTests(unittest.TestCase):
    def test_publish_uses_stable_report_id_and_non_sensitive_payload(self):
        sdk = FakePublisher()
        publisher = ReportReadyPublisher(sdk,
            topic="projects/demo-lab008/topics/lab008-report-ready")
        message_id = publisher.publish(REPORT)
        self.assertEqual(message_id, "message-123")
        topic, data, attrs = sdk.calls[0]
        event = json.loads(data)
        self.assertEqual(topic, "projects/demo-lab008/topics/lab008-report-ready")
        self.assertEqual(event["event_id"], "b" * 64)
        self.assertEqual(event["event_type"], "report.ready")
        self.assertEqual(event["report"]["generation"], "456")
        self.assertEqual(attrs["event_id"], "b" * 64)
        self.assertEqual(attrs["report_sha256"], "a" * 64)
        self.assertNotIn("amount", event)
        self.assertNotIn("csv", event)

    def test_retries_emit_identical_identity_and_body(self):
        sdk = FakePublisher()
        publisher = ReportReadyPublisher(sdk,
            topic="projects/demo-lab008/topics/lab008-report-ready")
        publisher.publish(REPORT)
        publisher.publish(REPORT)
        self.assertEqual(sdk.calls[0], sdk.calls[1])

    def test_publish_timeout_or_missing_message_id_is_uncertain(self):
        sdk = FakePublisher(FakeFuture(error=TimeoutError()))
        publisher = ReportReadyPublisher(sdk,
            topic="projects/demo-lab008/topics/lab008-report-ready")
        with self.assertRaisesRegex(PublishUncertain, "publish_uncertain"):
            publisher.publish(REPORT)
        sdk = FakePublisher(FakeFuture(None))
        publisher = ReportReadyPublisher(sdk,
            topic="projects/demo-lab008/topics/lab008-report-ready")
        with self.assertRaises(PublishUncertain):
            publisher.publish(REPORT)

    def test_invalid_event_is_rejected_before_rpc(self):
        sdk = FakePublisher()
        publisher = ReportReadyPublisher(sdk,
            topic="projects/demo-lab008/topics/lab008-report-ready")
        invalid_paths = (
            "reports/business_date=2026-10-23/other.json",
            "reports/business_date=2026-13-40/summary.json",
        )
        for object_name in invalid_paths:
            with self.subTest(object_name=object_name):
                invalid = dict(REPORT, object=object_name)
                with self.assertRaisesRegex(ValueError, "invalid_report_event"):
                    publisher.publish(invalid)
        self.assertEqual(sdk.calls, [])


if __name__ == "__main__":
    unittest.main()
