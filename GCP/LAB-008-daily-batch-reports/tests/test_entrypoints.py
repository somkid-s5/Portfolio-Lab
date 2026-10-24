"""Command and environment factory tests; constructors are mocked before any RPC."""
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import job, runtime
from app.worker import WorkerFailure


class FakeWorker:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []
    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "CLOUD_RUN_EXECUTION": "lab008-run-20261024",
            "CLOUD_RUN_TASK_ATTEMPT": "0",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_job_main_passes_only_explicit_arguments_and_emits_result(self):
        worker = FakeWorker({
            "status": "succeeded", "business_date": "2026-10-23",
            "report_id": "b" * 64, "report_generation": "700",
        })
        output = io.StringIO()
        with patch.object(job, "_worker_from_env", return_value=worker), \
             patch.object(sys, "stdout", output):
            code = job.main(["--business-date=2026-10-23"])
        self.assertEqual(code, 0)
        self.assertEqual(worker.calls[0], {
            "business_date": "2026-10-23",
            "execution": "lab008-run-20261024",
            "task_attempt": 0,
            "mode": "scheduled",
            "source_object": None,
            "source_generation": None,
        })
        event = json.loads(output.getvalue())
        self.assertEqual(event["event"], "daily_report_run_finished")
        self.assertEqual(event["report_generation"], "700")

    def test_missing_cloud_run_execution_is_rejected_without_client_creation(self):
        os.environ.pop("CLOUD_RUN_EXECUTION")
        output = io.StringIO()
        with patch.object(job, "_worker_from_env") as factory, \
             patch.object(sys, "stdout", output):
            code = job.main(["--business-date=2026-10-23"])
        self.assertEqual(code, 2)
        factory.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["reason"],
                         "invalid_execution_metadata")

    def test_worker_failure_is_safe_and_returns_nonzero(self):
        output = io.StringIO()
        with patch.object(job, "_worker_from_env",
                          return_value=FakeWorker(error=WorkerFailure("output_integrity"))), \
             patch.object(sys, "stdout", output):
            code = job.main(["--business-date=2026-10-23"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["reason"], "output_integrity")

    def test_blocked_data_is_reported_and_fails_cloud_run_execution(self):
        output = io.StringIO()
        with patch.object(job, "_worker_from_env", return_value=FakeWorker({
            "status": "blocked", "business_date": "2026-10-23",
            "validation_code": "INVALID_HEADER",
        })), patch.object(sys, "stdout", output):
            code = job.main(["--business-date=2026-10-23"])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "blocked")


class RuntimeFactoryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": "demo-lab008",
            "RUN_REGION": "asia-southeast1",
            "RUN_JOB_NAME": "lab008-daily-report",
            "REPORT_SCHEDULER_JOB_NAME": "report-schedule",
            "WATCHDOG_SCHEDULER_JOB_NAME": "watchdog",
            "FIRESTORE_DATABASE": "lab008-reports",
            "FIRESTORE_COLLECTION": "daily_runs",
            "SOURCE_BUCKET": "source-bucket",
            "REPORT_BUCKET": "report-bucket",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_coordinator_factory_wires_clients_without_cloud_calls(self):
        credentials = object()
        with patch.object(runtime.google.auth, "default",
                          return_value=(credentials, "demo-lab008")), \
             patch.object(runtime.firestore, "Client") as firestore_client, \
             patch.object(runtime.storage, "Client") as storage_client, \
             patch.object(runtime, "FirestoreLedger") as ledger_factory, \
             patch.object(runtime, "GCSObjects") as objects_factory, \
             patch.object(runtime, "AuthorizedSession") as session_factory, \
             patch.object(runtime, "CloudRunJobRunner") as runner_factory:
            app = runtime.create_app_from_env()
        firestore_client.assert_called_once_with(
            project="demo-lab008", database="lab008-reports",
            credentials=credentials)
        storage_client.assert_called_once_with(
            project="demo-lab008", credentials=credentials)
        ledger_factory.assert_called_once()
        objects_factory.assert_called_once()
        session_factory.assert_called_once_with(credentials)
        runner_factory.assert_called_once()
        self.assertEqual(app.test_client().get("/healthz").status_code, 200)

    def test_project_mismatch_fails_before_client_creation(self):
        with patch.object(runtime.google.auth, "default",
                          return_value=(object(), "wrong-project")), \
             patch.object(runtime.firestore, "Client") as firestore_client:
            with self.assertRaisesRegex(RuntimeError, "runtime_project_mismatch"):
                runtime.create_app_from_env()
        firestore_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
