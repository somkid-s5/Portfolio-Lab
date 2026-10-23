"""Requires a loopback emulator. Never falls back to Google Cloud."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import threading
import unittest
import uuid

from google.cloud import firestore
from google.auth.credentials import AnonymousCredentials
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from firestore_jobs import Jobs
from job_state import Conflict, new_job
from processor import Processor, IntegrityFailure
from csv_domain import Rejected

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class MemoryObjects:
    """Storage test double only; transaction side remains a real emulator."""
    def __init__(self, data):
        self.data = data
        self.outputs = {}
        self.creates = 0
        self.reads = 0

    def read_source(self, name, generation, max_bytes):
        self.reads += 1
        if generation != "123":
            raise AssertionError("unpinned source")
        if len(self.data) > max_bytes:
            raise Rejected("file_too_large")
        return self.data

    def create_or_verify(self, name, body, **metadata):
        if name in self.outputs:
            if self.outputs[name] != (body, metadata):
                raise IntegrityFailure()
        else:
            self.outputs[name] = (body, metadata)
            self.creates += 1
        return "456"


class FirestoreJobsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8086":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(project="demo-lab006", database="lab006-files",
                                      credentials=AnonymousCredentials())

    def setUp(self):
        self.job_id = uuid.uuid4().hex
        self.ref = self.client.collection("jobs").document(self.job_id)
        self.ref.create(new_job(self.job_id, "alice", NOW), timeout=10)
        self.jobs = Jobs(self.client, clock=lambda: NOW)

    def tearDown(self):
        self.ref.delete(timeout=10)

    def output(self):
        return {"name": f"results/{self.job_id}/123/v1/summary.json",
                "generation": "456", "sha256": "d"*64, "input_sha256": "e"*64}

    def test_two_transactions_only_one_worker_claims(self):
        gate = threading.Barrier(2, timeout=10)
        def compete(token):
            gate.wait()
            return self.jobs.claim(self.job_id, "123", token, finalized_at=NOW)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(compete, ["a"*32, "b"*32]))
        self.assertCountEqual([x["disposition"] for x in outcomes], ["claimed", "busy"])
        item = self.ref.get(timeout=10).to_dict()
        self.assertEqual((item["attempt_count"], item["input_generation"]), (1, "123"))

    def test_reclaim_and_stale_commit_do_not_corrupt_new_attempt(self):
        self.jobs.claim(self.job_id, "123", "a"*32, finalized_at=NOW)
        later = Jobs(self.client, clock=lambda: NOW + timedelta(seconds=120))
        later.claim(self.job_id, "123", "b"*32, finalized_at=NOW)
        before = self.ref.get(timeout=10).to_dict()
        with self.assertRaises(Conflict):
            later.finish(self.job_id, "a"*32, output=self.output())
        self.assertEqual(self.ref.get(timeout=10).to_dict(), before)
        done = later.finish(self.job_id, "b"*32, output=self.output())
        self.assertEqual((done["state"], done["output_generation"]), ("succeeded", "456"))
        self.assertEqual(later.claim(self.job_id, "123", "c"*32,
                                    finalized_at=NOW)["disposition"], "terminal")

    def test_owner_and_generation_boundary(self):
        with self.assertRaisesRegex(KeyError, "job_not_found"):
            self.jobs.read_owned(self.job_id, "bob")
        self.assertEqual(self.jobs.read_owned(self.job_id, "alice")["owner"], "alice")
        self.jobs.claim(self.job_id, "123", "a"*32, finalized_at=NOW)
        result = self.jobs.claim(self.job_id, "999", "b"*32, finalized_at=NOW)
        self.assertEqual(result["disposition"], "ignored_generation")
        self.assertEqual(self.ref.get(timeout=10).to_dict()["input_generation"], "123")

    def test_retry_budget_and_operator_epoch_are_transactional(self):
        for _ in range(5):
            result = self.jobs.claim(self.job_id, "123", "a"*32, finalized_at=NOW)
            self.assertEqual(result["disposition"], "claimed")
            self.jobs.release_transient(self.job_id, "a"*32)
        result = self.jobs.claim(self.job_id, "123", "a"*32, finalized_at=NOW)
        self.assertEqual(result["disposition"], "needs_operator")
        retried = self.jobs.operator_retry(self.job_id)
        self.assertEqual((retried["attempt_epoch"], retried["attempt_count"]), (1, 0))
        self.assertEqual(retried["input_generation"], "123")
        self.assertEqual(self.jobs.claim(self.job_id, "123", "b"*32,
                                       finalized_at=NOW)["disposition"], "claimed")


    def test_same_key_race_creates_one_job_and_one_quota_reservation(self):
        owner = "owner_" + uuid.uuid4().hex
        key = "same-key-" + uuid.uuid4().hex
        gate = threading.Barrier(2, timeout=10)
        def create(_):
            gate.wait()
            return self.jobs.create(owner, key, "sales.csv")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(create, range(2)))
        ids = {result["job"]["job_id"] for result in results}
        self.assertEqual(len(ids), 1)
        self.assertCountEqual([r["replayed"] for r in results], [False, True])
        quota = self.client.collection("owner_quotas").document(owner).get().to_dict()
        self.assertEqual((quota["daily_count"], len(quota["active_ids"])), (1, 1))
        with self.assertRaisesRegex(Conflict, "idempotency_conflict"):
            self.jobs.create(owner, key, "different.csv")
        self.assertEqual(self.jobs.create(owner, key, "sales.csv")["job"]["job_id"],
                         next(iter(ids)))

    def test_active_quota_replay_and_terminal_slot_reuse(self):
        owner = "owner_" + uuid.uuid4().hex
        jobs = [self.jobs.create(owner, f"key-number-{i}", "sales.csv")["job"]
                for i in range(5)]
        with self.assertRaisesRegex(Conflict, "job_quota_exceeded"):
            self.jobs.create(owner, "key-number-6", "sales.csv")
        self.assertTrue(self.jobs.create(owner, "key-number-0", "sales.csv")["replayed"])
        first = jobs[0]["job_id"]
        self.jobs.claim(first, "123", "a"*32, finalized_at=NOW)
        self.jobs.finish(first, "a"*32, reason="invalid_utf8")
        self.assertFalse(self.jobs.create(owner, "key-number-6", "sales.csv")["replayed"])

    def test_daily_quota_does_not_reset_with_terminal_jobs_or_new_keys(self):
        owner = "owner_" + uuid.uuid4().hex
        for index in range(20):
            job = self.jobs.create(owner, f"daily-key-{index}", "sales.csv")["job"]
            self.jobs.claim(job["job_id"], "123", "a"*32, finalized_at=NOW)
            self.jobs.finish(job["job_id"], "a"*32, reason="invalid_utf8")
        with self.assertRaisesRegex(Conflict, "job_quota_exceeded"):
            self.jobs.create(owner, "daily-key-21", "sales.csv")
        tomorrow = Jobs(self.client, clock=lambda: NOW + timedelta(days=1))
        self.assertFalse(tomorrow.create(owner, "new-day-key", "sales.csv")["replayed"])

    def test_expired_idempotency_reference_never_silently_creates_new_job(self):
        owner = "owner_" + uuid.uuid4().hex
        original = self.jobs.create(owner, "expired-key", "sales.csv")["job"]
        self.client.collection("jobs").document(original["job_id"]).delete()
        with self.assertRaisesRegex(Conflict, "idempotency_record_expired"):
            self.jobs.create(owner, "expired-key", "sales.csv")



    def test_worker_recovers_output_metadata_gap_with_same_result(self):
        data = b"sale_id,sku,quantity,unit_price_satang\nS1,BOOK-01,2,100\n"
        objects = MemoryObjects(data)
        worker = Processor(self.jobs, objects, fail_after_output_once=True)
        first = worker.run(self.job_id, "123", NOW)
        self.assertEqual((first["status"], first["reason"]),
                         (503, "intentional_after_output"))
        pending = self.ref.get(timeout=10).to_dict()
        self.assertEqual(pending["state"], "processing")
        self.assertTrue(pending["output_fault_consumed"])
        self.assertNotIn("output_generation", pending)
        self.assertEqual(worker.run(self.job_id, "123", NOW)["reason"], "succeeded")
        done = self.ref.get(timeout=10).to_dict()
        self.assertEqual(done["output_generation"], "456")
        self.assertEqual(objects.creates, 1)
        self.assertEqual(worker.run(self.job_id, "123", NOW)["reason"], "terminal")
        self.assertEqual(objects.reads, 2)

    def test_worker_validation_rejects_and_acknowledges_without_output(self):
        objects = MemoryObjects(b"bad,header\n")
        worker = Processor(self.jobs, objects)
        result = worker.run(self.job_id, "123", NOW)
        self.assertEqual((result["status"], result["reason"]), (204, "rejected"))
        self.assertEqual(self.ref.get(timeout=10).to_dict()["safe_reason"], "invalid_header")
        self.assertEqual(objects.creates, 0)

    def test_worker_integrity_mismatch_is_not_overwritten_or_auto_retried(self):
        objects = MemoryObjects(
            b"sale_id,sku,quantity,unit_price_satang\nS1,BOOK-01,1,0\n")
        name = f"results/{self.job_id}/123/v1/summary.json"
        objects.outputs[name] = (b"corrupt", {})
        worker = Processor(self.jobs, objects)
        self.assertEqual(worker.run(self.job_id, "123", NOW)["reason"],
                         "failed_integrity")
        self.assertEqual(objects.outputs[name], (b"corrupt", {}))
        with self.assertRaises(Conflict):
            self.jobs.operator_retry(self.job_id)

    def test_worker_different_generation_and_unknown_job_do_not_read_source(self):
        self.jobs.claim(self.job_id, "123", "a"*32, finalized_at=NOW)
        objects = MemoryObjects(b"unused")
        worker = Processor(self.jobs, objects)
        self.assertEqual(worker.run(self.job_id, "999", NOW)["reason"],
                         "ignored_generation")
        self.assertEqual(worker.run(uuid.uuid4().hex, "123", NOW)["reason"],
                         "unknown_job")
        self.assertEqual(objects.reads, 0)



    def test_owner_filtered_pages_are_bounded_and_cursor_never_grants_access(self):
        alice, bob = "alice_" + uuid.uuid4().hex, "bob_" + uuid.uuid4().hex
        created = [self.jobs.create(alice, f"page-key-{i}", "sales.csv")["job"]["job_id"]
                   for i in range(4)]
        foreign = self.jobs.create(bob, "foreign-key", "private.csv")["job"]["job_id"]
        first = self.jobs.list_owned(alice, limit=2)
        second = self.jobs.list_owned(alice, limit=2, cursor=first["next_cursor"])
        observed = [item["job_id"] for page in (first, second) for item in page["jobs"]]
        self.assertEqual(observed, sorted(created))
        self.assertIsNone(second["next_cursor"])
        self.assertNotIn(foreign, observed)
        forged = self.jobs.list_owned(alice, limit=20, cursor=foreign)
        self.assertTrue(all(item["owner"] == alice for item in forged["jobs"]))
        for limit in (0, 21, True):
            with self.assertRaises(ValueError):
                self.jobs.list_owned(alice, limit=limit)
        with self.assertRaises(ValueError):
            self.jobs.list_owned(alice, cursor="../other")


if __name__ == "__main__":
    unittest.main()
