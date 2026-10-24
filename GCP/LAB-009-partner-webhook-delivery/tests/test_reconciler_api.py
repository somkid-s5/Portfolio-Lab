"""HTTP contract tests for the Cloud Scheduler reconciliation target."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError
from app.reconciler_api import create_reconciler_app


SUMMARY = SimpleNamespace(
    pending_seen=4,
    queued_seen=3,
    enqueued=2,
    moved_to_review=1,
    errors=0,
)


class FakeReconciler:
    def __init__(self, result=SUMMARY, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def run_once(self, *, page_size):
        self.calls.append(page_size)
        if self.error:
            raise self.error
        return self.result


class ReconcilerApiTests(unittest.TestCase):
    def setUp(self):
        self.reconciler = FakeReconciler()
        self.app = create_reconciler_app(reconciler=self.reconciler)
        self.client = self.app.test_client()

    def test_empty_scheduler_request_runs_fixed_bounded_page(self):
        response = self.client.post("/internal/reconcile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "status": "completed",
            "pending_seen": 4,
            "queued_seen": 3,
            "enqueued": 2,
            "moved_to_review": 1,
            "errors": 0,
        })
        self.assertEqual(self.reconciler.calls, [25])

    def test_scheduler_empty_json_body_is_accepted(self):
        response = self.client.post(
            "/internal/reconcile", data=b"{}", content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.reconciler.calls, [25])

    def test_partial_page_error_returns_retryable_503(self):
        self.reconciler.result = SimpleNamespace(
            pending_seen=1,
            queued_seen=1,
            enqueued=1,
            moved_to_review=0,
            errors=1,
        )
        response = self.client.post("/internal/reconcile", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["status"], "partial_failure")
        self.assertEqual(response.get_json()["errors"], 1)

    def test_unexpected_payload_is_not_a_reconciler_control_plane(self):
        response = self.client.post(
            "/internal/reconcile",
            json={"page_size": 1000},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.reconciler.calls, [])

    def test_malformed_json_is_rejected_before_reconciliation(self):
        response = self.client.post(
            "/internal/reconcile",
            data=b"{not-json",
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.reconciler.calls, [])

    def test_non_json_body_is_rejected(self):
        response = self.client.post(
            "/internal/reconcile",
            data=b"operator input",
            content_type="text/plain",
        )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.reconciler.calls, [])

    def test_unexpected_reconciler_error_returns_safe_503(self):
        self.reconciler.error = RuntimeError("sensitive details")
        response = self.client.post("/internal/reconcile", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "reconciliation_unavailable"})
        self.assertNotIn(b"sensitive details", response.data)

    def test_health_and_method_contract(self):
        self.assertEqual(self.client.get("/healthz").get_json(), {"status": "ok"})
        self.assertEqual(self.client.get("/internal/reconcile").status_code, 405)

    def test_page_size_is_validated_at_startup(self):
        for invalid in (0, 26, True, "25"):
            with self.subTest(page_size=invalid):
                with self.assertRaises(ValidationError):
                    create_reconciler_app(
                        reconciler=self.reconciler,
                        page_size=invalid,
                    )


if __name__ == "__main__":
    unittest.main()
