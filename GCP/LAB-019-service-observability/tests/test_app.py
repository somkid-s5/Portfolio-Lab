from __future__ import annotations

import base64
import json
import os
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.api import create_app
from app.migrate import migrate
from app.telemetry import classify_request
from app.worker import create_worker_app


DATABASE_URL = os.environ.get("DATABASE_URL")


@unittest.skipUnless(DATABASE_URL, "Set DATABASE_URL to run the PostgreSQL integration tests.")
class Lab019ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        migrate(cls.engine)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with self.engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE lab19.tasks"))
        self.publisher = Mock()
        self.api = TestClient(create_app(
            engine_factory=lambda: self.engine,
            publisher=self.publisher,
        ))
        self.worker = TestClient(create_worker_app(engine_factory=lambda: self.engine))

    def _push_envelope(self, task_id: str) -> dict:
        data = json.dumps({"task_id": task_id}, separators=(",", ":")).encode("utf-8")
        return {"message": {"data": base64.b64encode(data).decode("ascii"), "messageId": "ci-message"}}

    def _create_task(self, idempotency_key: str = "ci-task-0001") -> str:
        response = self.api.post(
            "/tasks",
            json={
                "idempotency_key": idempotency_key,
                "items": [
                    {"sku": "DEMO-001", "quantity": 2, "unit_price_cents": 1250},
                    {"sku": "DEMO-002", "quantity": 1, "unit_price_cents": 500},
                ],
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()["task_id"]

    def test_api_publishes_and_idempotency_key_returns_same_task(self):
        first = self._create_task()
        second = self._create_task()
        self.assertEqual(first, second)
        self.assertEqual(self.publisher.call_count, 2)
        read = self.api.get("/tasks/" + first)
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["status"], "QUEUED")

    def test_worker_processes_once_and_duplicate_delivery_is_safe(self):
        task_id = self._create_task("ci-task-0002")
        first = self.worker.post("/events", json=self._push_envelope(task_id))
        second = self.worker.post("/events", json=self._push_envelope(task_id))
        self.assertEqual(first.status_code, 204, first.text)
        self.assertEqual(second.status_code, 204, second.text)
        task = self.api.get("/tasks/" + task_id).json()
        self.assertEqual(task["status"], "SUCCEEDED")
        self.assertEqual(task["result"], {"line_count": 2, "total_cents": 3000})

    def test_dead_letter_updates_task_status_and_manual_redrive_recovers(self):
        task_id = self._create_task("ci-task-dead-letter")
        marked_failed = self.worker.post("/dead-letter-events", json=self._push_envelope(task_id))
        self.assertEqual(marked_failed.status_code, 204, marked_failed.text)
        self.assertEqual(self.api.get("/tasks/" + task_id).json()["status"], "FAILED")

        redriven = self.worker.post("/events", json=self._push_envelope(task_id))
        self.assertEqual(redriven.status_code, 204, redriven.text)
        self.assertEqual(self.api.get("/tasks/" + task_id).json()["status"], "SUCCEEDED")

    def test_retryable_worker_failure_can_be_retried(self):
        task_id = self._create_task("ci-task-0003")
        failed_worker = TestClient(
            create_worker_app(engine_factory=lambda: self.engine, fault_mode="503")
        )
        failed = failed_worker.post("/events", json=self._push_envelope(task_id))
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(self.api.get("/tasks/" + task_id).json()["status"], "QUEUED")
        recovered = self.worker.post("/events", json=self._push_envelope(task_id))
        self.assertEqual(recovered.status_code, 204)
        self.assertEqual(self.api.get("/tasks/" + task_id).json()["status"], "SUCCEEDED")

    def test_publish_failure_keeps_idempotency_record_for_client_retry(self):
        failing_api = TestClient(
            create_app(
                engine_factory=lambda: self.engine,
                publisher=Mock(side_effect=RuntimeError("test-only")),
            )
        )
        body = {
            "idempotency_key": "ci-task-publish-retry",
            "items": [{"sku": "DEMO-003", "quantity": 1, "unit_price_cents": 300}],
        }
        failed = failing_api.post("/tasks", json=body)
        self.assertEqual(failed.status_code, 503)
        retried = self.api.post("/tasks", json=body)
        self.assertEqual(retried.status_code, 202)
        self.assertEqual(retried.json()["idempotent_replay"], True)
        self.assertEqual(retried.json()["status"], "QUEUED")

    def test_bad_input_and_health_are_excluded_from_user_sli(self):
        invalid = self.api.post("/tasks", json={"idempotency_key": "short", "items": []})
        self.assertEqual(invalid.status_code, 422)
        health = self.api.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(classify_request("POST", "/tasks", 422), (False, "excluded"))
        self.assertEqual(classify_request("GET", "/healthz", 200), (False, "excluded"))
        self.assertEqual(classify_request("POST", "/tasks", 503), (True, "bad"))
        self.assertEqual(classify_request("GET", "/tasks/abc", 200), (True, "good"))


if __name__ == "__main__":
    unittest.main()
