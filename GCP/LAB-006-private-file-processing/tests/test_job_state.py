from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from job_state import (Conflict, claim, finish, new_job, operator_retry,
                       release_transient)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
JOB_ID = "a" * 32
TOKEN_A = "b" * 32
TOKEN_B = "c" * 32


class JobStateTests(unittest.TestCase):
    def job(self):
        return new_job(JOB_ID, "alice", NOW)

    def claim(self, job, now=NOW, token=TOKEN_A, generation="123"):
        return claim(job, generation, token, now, finalized_at=NOW)

    def output(self):
        return {"name": f"results/{JOB_ID}/123/v1/summary.json",
                "generation": "456", "sha256": "d"*64, "input_sha256": "e"*64}

    def test_contract_is_immutable_and_lease_is_bounded(self):
        job = self.job()
        original = deepcopy(job)
        item, action = self.claim(job)
        self.assertEqual(action, "claimed")
        self.assertEqual(job, original)
        self.assertEqual(item["owner"], "alice")
        self.assertEqual(item["input_generation"], "123")
        self.assertEqual(item["lease_until"], NOW + timedelta(seconds=120))
        self.assertEqual(item["attempt_count"], 1)

    def test_duplicate_busy_and_other_generation_ignored(self):
        first, _ = self.claim(self.job())
        second, action = self.claim(first, token=TOKEN_B)
        self.assertEqual((action, second), ("busy", first))
        other, action = self.claim(first, token=TOKEN_B, generation="999")
        self.assertEqual((action, other), ("ignored_generation", first))

    def test_reclaim_fences_old_worker_and_expired_lease(self):
        first, _ = self.claim(self.job())
        at = NOW + timedelta(seconds=120)
        with self.assertRaises(Conflict):
            finish(first, TOKEN_A, at, output=self.output())
        second, action = self.claim(first, now=at, token=TOKEN_B)
        self.assertEqual(action, "claimed")
        self.assertEqual(second["attempt_count"], 2)
        with self.assertRaises(Conflict):
            finish(second, TOKEN_A, at, output=self.output())
        done = finish(second, TOKEN_B, at, output=self.output())
        self.assertEqual(done["state"], "succeeded")
        self.assertEqual(done["output_generation"], "456")
        replay, action = self.claim(done, now=at)
        self.assertEqual((action, replay), ("terminal", done))

    def test_delayed_delivery_binds_file_finalized_before_deadline(self):
        delayed, action = self.claim(self.job(), now=NOW + timedelta(minutes=10))
        self.assertEqual(action, "claimed")
        late, action = claim(self.job(), "123", TOKEN_A, NOW + timedelta(minutes=10),
                             finalized_at=NOW + timedelta(minutes=6))
        self.assertEqual((late["state"], action), ("expired", "terminal"))
        self.assertIsNone(late["input_generation"])

    def test_expiry_prevents_publish_and_future_claim(self):
        original = self.job()
        item, action = self.claim(original, now=NOW + timedelta(hours=24))
        self.assertEqual((item["state"], action), ("expired", "terminal"))
        near_expiry = NOW + timedelta(hours=24, seconds=-30)
        processing, _ = self.claim(original, now=near_expiry)
        with self.assertRaisesRegex(Conflict, "job_expired"):
            finish(processing, TOKEN_A, NOW + timedelta(hours=24), output=self.output())

    def test_rejection_is_terminal_and_reason_is_safe(self):
        processing, _ = self.claim(self.job())
        with self.assertRaises(ValueError):
            finish(processing, TOKEN_A, NOW, reason="raw secret error")
        rejected = finish(processing, TOKEN_A, NOW, reason="duplicate_sale_id")
        self.assertEqual(rejected["state"], "rejected")
        with self.assertRaises(Conflict):
            operator_retry(rejected, NOW)
        terminal, action = self.claim(rejected)
        self.assertEqual((action, terminal), ("terminal", rejected))

    def test_retry_budget_and_manual_epochs_preserve_input_contract(self):
        job = self.job()
        for epoch in range(3):
            for attempt in range(5):
                job, action = self.claim(job)
                self.assertEqual(action, "claimed")
                job = release_transient(job, TOKEN_A, NOW)
            job, action = self.claim(job)
            self.assertEqual((action, job["state"]), ("needs_operator", "failed"))
            if epoch < 2:
                job = operator_retry(job, NOW)
                self.assertEqual(job["input_generation"], "123")
                self.assertEqual(job["owner"], "alice")
                self.assertEqual((job["max_bytes"], job["processor_version"]),
                                 (1048576, "v1"))
        with self.assertRaises(Conflict):
            operator_retry(job, NOW)

    def test_integrity_failure_cannot_be_operator_retried(self):
        job, _ = self.claim(self.job())
        job = finish(job, TOKEN_A, NOW, reason="failed_integrity")
        with self.assertRaises(Conflict):
            operator_retry(job, NOW)

    def test_output_binding_and_input_validation(self):
        job, _ = self.claim(self.job())
        for key, value in [("name", "results/someone-else/result.json"),
                           ("generation", "0"), ("sha256", "bad")]:
            result = self.output()
            result[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                finish(job, TOKEN_A, NOW, output=result)
        with self.assertRaises(ValueError):
            new_job(JOB_ID, "alice", NOW.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            claim(job, "0", TOKEN_A, NOW, finalized_at=NOW)
        with self.assertRaises(ValueError):
            new_job(JOB_ID, "alice", NOW, max_bytes=999)
        with self.assertRaises(ValueError):
            finish(job, TOKEN_A, NOW)
        with self.assertRaises(ValueError):
            finish(job, TOKEN_A, NOW, output=self.output(), reason="invalid_utf8")


if __name__ == "__main__":
    unittest.main()
