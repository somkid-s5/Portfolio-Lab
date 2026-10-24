"""Cloud Tasks request-contract tests use an injected fake client, never RPC."""
from datetime import datetime, timezone
import sys
import unittest
from pathlib import Path

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import tasks_v2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError, build_event, parse_submission, delivery_id, task_resource_name
from app.task_queue import CloudTasksEnqueuer, PartnerQueue, TaskNameConflict


EVENT = build_event(
    parse_submission(
        b'{"partner_id":"partner-a","order_ref":"ORD-AB12CD34",'
        b'"occurred_at":"2026-10-24T01:00:00Z","shipping_status":"shipped"}',
        ("partner-a",),
    ),
    event_id="01234567-89ab-4cde-8fab-0123456789ab",
    accepted_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
)
DELIVERY = delivery_id(EVENT["event_id"], EVENT["partner_id"])
CONFIG = PartnerQueue(
    project_id="demo-lab009",
    location_id="asia-southeast1",
    queue_id="partner-a",
    partner_id="partner-a",
    worker_url="https://worker-a-1234567890.asia-southeast1.run.app/internal/deliver",
    task_service_account="lab09-tasks@demo-lab009.iam.gserviceaccount.com",
    oidc_audience="https://worker-a-1234567890.asia-southeast1.run.app",
)


class FakeTasksClient:
    def __init__(self):
        self.create_error = None
        self.existing_task = None
        self.created = []
        self.get_calls = []

    def create_task(self, *, parent, task, timeout):
        self.created.append((parent, task, timeout))
        if self.create_error:
            raise self.create_error
        return task

    def get_task(self, *, name, timeout):
        self.get_calls.append((name, timeout))
        if isinstance(self.existing_task, Exception):
            raise self.existing_task
        return self.existing_task


class CloudTasksEnqueuerTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeTasksClient()
        self.enqueuer = CloudTasksEnqueuer(self.client)

    def test_builds_deterministic_ids_only_post_with_oidc(self):
        first = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)
        second = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)

        self.assertEqual(first.outcome, "created")
        self.assertEqual(first.task_name, second.task_name)
        parent, task, timeout = self.client.created[0]
        self.assertEqual(parent, "projects/demo-lab009/locations/asia-southeast1/queues/partner-a")
        self.assertEqual(timeout, 10.0)
        self.assertEqual(task.name, first.task_name)
        self.assertEqual(task.http_request.http_method, tasks_v2.HttpMethod.POST)
        self.assertEqual(task.http_request.url, CONFIG.worker_url)
        self.assertEqual(task.http_request.headers["Content-Type"], "application/json")
        self.assertEqual(
            task.http_request.body,
            b'{"delivery_id":"' + DELIVERY.encode() +
            b'","event_id":"01234567-89ab-4cde-8fab-0123456789ab","generation":1,"partner_id":"partner-a"}',
        )
        self.assertEqual(
            task.http_request.oidc_token.service_account_email,
            CONFIG.task_service_account,
        )
        self.assertEqual(task.http_request.oidc_token.audience, CONFIG.oidc_audience)
        self.assertEqual(task.dispatch_deadline.seconds, 30)

    def test_generation_changes_task_name_and_payload(self):
        one = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)
        two = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=2, config=CONFIG)
        self.assertNotEqual(one.task_name, two.task_name)
        self.assertIn(b'"generation":2', self.client.created[1][1].http_request.body)

    def test_already_exists_is_confirmed_with_get_task(self):
        self.client.create_error = AlreadyExists("duplicate")
        expected_name = task_resource_name(
            CONFIG.project_id, CONFIG.location_id, CONFIG.queue_id, DELIVERY, 1
        )
        self.client.existing_task = tasks_v2.Task(name=expected_name)
        result = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)
        self.assertEqual(result.outcome, "already_exists")
        self.assertEqual(self.client.get_calls[-1][0], expected_name)

    def test_already_exists_then_not_found_is_ambiguous_not_recreated(self):
        self.client.create_error = AlreadyExists("duplicate")
        self.client.existing_task = NotFound("gone")
        result = self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)
        self.assertEqual(result.outcome, "missing_after_already_exists")
        self.assertEqual(len(self.client.created), 1)
        self.assertEqual(len(self.client.get_calls), 1)

    def test_get_task_name_mismatch_fails_closed(self):
        self.client.create_error = AlreadyExists("duplicate")
        self.client.existing_task = tasks_v2.Task(name="different")
        with self.assertRaises(TaskNameConflict):
            self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=CONFIG)

    def test_invalid_url_and_cross_partner_queue_are_rejected_before_rpc(self):
        unsafe = PartnerQueue(**{**CONFIG.__dict__, "worker_url": "http://example.com/internal/deliver"})
        with self.assertRaises(ValidationError):
            self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=unsafe)
        other = PartnerQueue(**{**CONFIG.__dict__, "partner_id": "partner-b"})
        with self.assertRaises(ValidationError):
            self.enqueuer.enqueue(EVENT, delivery=DELIVERY, generation=1, config=other)
        self.assertEqual(self.client.created, [])


if __name__ == "__main__":
    unittest.main()
