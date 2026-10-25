from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))

from lab13.contract import parse_manifest_bytes
from reconcile import evaluate, render_report
from render_batch_job import build_job


def base_args(**overrides):
    values = {
        "purpose": "process", "project": "lab13-demo-123", "region": "asia-southeast1",
        "job_id": "lab13-test-001",
        "image_uri": "asia-southeast1-docker.pkg.dev/lab13-demo-123/lab013-images/worker@sha256:" + "a" * 64,
        "runtime_service_account": "lab013-runtime@lab13-demo-123.iam.gserviceaccount.com",
        "network": "lab013-vpc", "subnetwork": "lab013-workers", "machine_type": "e2-standard-2",
        "timeout_seconds": 900, "manifest_uri": "gs://lab13-input-abc123/runs/lab13-test-001/manifest.json",
        "attempt_output_bucket": "lab13-attempt-abc123", "task_count": 2, "parallelism": 2,
        "fail_once_index": 0, "input_bucket": None, "published_bucket": None,
        "probe_id": None, "output": Path("job.json"),
    }
    values.update(overrides)
    return Namespace(**values)


def fixture_manifest():
    raw_shard = b'{"sku":"SKU-00000000","units":1,"unit_price_minor":100}\n'
    return {
        "schema_version": 1, "run_id": "lab13-test-001",
        "shard_count": 1, "total_records": 1, "records_per_shard": 1,
        "shards": [{"index": 0,
                    "uri": "gs://lab13-input-abc123/runs/lab13-test-001/shards/shard-00000.jsonl",
                    "record_count": 1, "sha256": hashlib.sha256(raw_shard).hexdigest()}],
    }


class ToolTests(unittest.TestCase):
    def test_job_config_is_digest_pinned_private_and_selectively_retryable(self):
        config = build_job(base_args())
        task = config["taskGroups"][0]
        self.assertEqual(task["taskCount"], 2)
        self.assertEqual(task["parallelism"], 2)
        self.assertEqual(task["taskCountPerNode"], 1)
        self.assertTrue(config["allocationPolicy"]["network"]["networkInterfaces"][0]["noExternalIpAddress"])
        self.assertEqual(task["taskSpec"]["maxRetryCount"], 1)
        self.assertEqual(task["taskSpec"]["lifecyclePolicies"],
                         [{"action": "RETRY_TASK", "actionCondition": {"exitCodes": [75]}}])
        self.assertIn("@sha256:", task["taskSpec"]["runnables"][0]["container"]["imageUri"])

    def test_job_renderer_rejects_mutable_image_reference(self):
        with self.assertRaises(ValueError):
            build_job(base_args(image_uri="asia-southeast1-docker.pkg.dev/demo/repo/worker:latest"))

    def test_iam_probe_job_has_one_task_and_no_retry(self):
        args = base_args(purpose="iam-probe", input_bucket="lab13-input-abc123",
                         published_bucket="lab13-published-abc123", probe_id="lab13-probe-001")
        config = build_job(args)
        task = config["taskGroups"][0]
        self.assertEqual((task["taskCount"], task["parallelism"]), (1, 1))
        self.assertEqual(task["taskSpec"]["maxRetryCount"], 0)
        self.assertIn("lab13.iam_probe", task["taskSpec"]["runnables"][0]["container"]["commands"])

    def test_reconciliation_requires_successful_job_tasks_and_one_result_per_shard(self):
        manifest = parse_manifest_bytes(json.dumps(fixture_manifest()).encode())
        result = {"schema_version": 1, "run_id": manifest["run_id"], "task_index": 0, "shard_index": 0,
                  "attempt": 1, "manifest_sha256": "b" * 64, "input_sha256": manifest["shards"][0]["sha256"],
                  "record_count": 1, "units_total": 1, "value_minor_total": 100}
        raw_result = json.dumps(result).encode()
        path = "runs/lab13-test-001/shards/00000/attempt-1/result.json"
        tasks = [{"name": "projects/p/locations/r/jobs/j/taskGroups/group0/tasks/task-0",
                  "status": {"state": "SUCCEEDED", "statusEvents": [
                      {"taskExecution": {"exitCode": 75}}]}}]
        good = evaluate({"status": {"state": "SUCCEEDED"}}, tasks, manifest, [(path, raw_result)])
        self.assertTrue(good["complete"])
        self.assertEqual(good["attempt_count_by_task"]["0"], 2)
        failed = evaluate({"status": {"state": "FAILED"}}, tasks, manifest, [(path, raw_result)])
        self.assertFalse(failed["complete"])
        self.assertTrue(any("not SUCCEEDED" in issue for issue in failed["issues"]))

    def test_reconciler_accepts_numeric_batch_resource_name_and_checks_retry_trace(self):
        manifest = parse_manifest_bytes(json.dumps(fixture_manifest()).encode())
        raw = json.dumps({
            "schema_version": 1, "run_id": manifest["run_id"], "task_index": 0, "shard_index": 0,
            "attempt": 0, "manifest_sha256": "b" * 64,
            "input_sha256": manifest["shards"][0]["sha256"],
            "record_count": 1, "units_total": 1, "value_minor_total": 100,
        }).encode()
        result_path = "runs/lab13-test-001/shards/00000/attempt-0/result.json"
        task = {"name": "projects/p/locations/r/jobs/j/taskGroups/group0/tasks/0",
                "status": {"state": "SUCCEEDED"}}
        good = evaluate({"status": {"state": "SUCCEEDED"}}, [task], manifest, [(result_path, raw)])
        self.assertTrue(good["complete"])
        retry_task = {"name": task["name"], "status": {"state": "SUCCEEDED", "statusEvents": [
            {"taskExecution": {"exitCode": 65}}]}}
        retried = evaluate({"status": {"state": "SUCCEEDED"}}, [retry_task], manifest, [(result_path, raw)])
        self.assertFalse(retried["complete"])
        self.assertTrue(any("invalid names, JSON, or manifest bindings" in issue for issue in retried["issues"]))

    def test_reconciliation_refuses_missing_or_duplicate_shard_outputs(self):
        manifest = parse_manifest_bytes(json.dumps(fixture_manifest()).encode())
        job = {"status": {"state": "SUCCEEDED"}}
        tasks = [{"name": "projects/p/locations/r/jobs/j/taskGroups/group0/tasks/task0",
                  "status": {"state": "SUCCEEDED"}}]
        self.assertFalse(evaluate(job, tasks, manifest, [])["complete"])
        result = {"schema_version": 1, "run_id": manifest["run_id"], "task_index": 0, "shard_index": 0,
                  "attempt": 0, "manifest_sha256": "b" * 64, "input_sha256": manifest["shards"][0]["sha256"], "record_count": 1,
                  "units_total": 1, "value_minor_total": 100}
        raw = json.dumps(result).encode()
        path = "runs/lab13-test-001/shards/00000/attempt-0/result.json"
        evaluated = evaluate(job, tasks, manifest, [(path, raw), (path.replace("attempt-0", "attempt-1"), raw)])
        self.assertFalse(evaluated["complete"])

    def test_partial_html_never_claims_publication(self):
        manifest = parse_manifest_bytes(json.dumps(fixture_manifest()).encode())
        evaluated = evaluate({"status": {"state": "FAILED"}}, [], manifest, [])
        report = render_report(evaluated)
        self.assertIn("PARTIAL — DO NOT PUBLISH", report)
        self.assertIn("not published", report)
        self.assertNotIn("COMPLETE</span>", report)

    def test_generator_rejects_existing_run_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            from generate_dataset import generate
            generate("lab13-input-abc123", "lab13-repeat-001", 1, 1, Path(tmp))
            with self.assertRaises(FileExistsError):
                generate("lab13-input-abc123", "lab13-repeat-001", 1, 1, Path(tmp))


if __name__ == "__main__":
    unittest.main()
