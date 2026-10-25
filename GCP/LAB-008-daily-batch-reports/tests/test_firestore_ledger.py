"""Transactional tests against an explicit loopback Firestore emulator."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch
from google.api_core.exceptions import Aborted

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ledger import FirestoreLedger
from app.ledger_state import StateConflict

NOW = datetime(2026, 10, 24, tzinfo=timezone.utc)
DAY = "2026-10-23"
SOURCE = f"incoming/business_date={DAY}/transactions.csv"


class FirestoreLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8087":
            raise RuntimeError("explicit_loopback_emulator_required")
        cls.client = firestore.Client(project="demo-lab008",
            database="lab008-ledger-tests", credentials=AnonymousCredentials())

    def setUp(self):
        self.now = NOW
        self.collection = "test_" + uuid.uuid4().hex[:24]
        self.ledger = FirestoreLedger(self.client, collection=self.collection,
                                      clock=lambda: self.now)

    def tearDown(self):
        for snap in self.ledger.collection.stream(timeout=10):
            snap.reference.delete(timeout=10)

    def claim(self, execution):
        return self.ledger.claim(business_date=DAY, execution=execution,
            task_attempt=0, source_object=SOURCE, source_generation="123")

    def test_concurrent_transactions_allow_only_one_claim(self):
        barrier = threading.Barrier(2, timeout=10)
        def compete(execution):
            barrier.wait()
            return self.claim(execution)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(compete, ("exec-a", "exec-b")))
        self.assertCountEqual([item[1] for item in outcomes], ["claimed", "busy"])
        record = self.ledger.read(DAY)
        self.assertEqual((record["fence"], record["attempt_count"]), (1, 1))

    def test_expired_lease_fences_old_owner_and_persists_report(self):
        _, disposition, old = self.claim("exec-a")
        self.assertEqual(disposition, "claimed")
        from app.ledger_state import LEASE
        self.now = NOW + LEASE
        _, disposition, new = self.ledger.claim(business_date=DAY, execution="exec-b",
            task_attempt=0, source_object=SOURCE, source_generation="123")
        self.assertEqual(disposition, "claimed")
        report = {"object": f"reports/business_date={DAY}/summary.json",
            "generation": "456", "sha256": "a"*64, "report_id": "b"*64,
            "source_generation": "123", "source_sha256": "c"*64}
        with self.assertRaisesRegex(StateConflict, "stale_fence"):
            self.ledger.record_report(DAY, old, report=report)
        self.assertEqual(self.ledger.record_report(DAY, new, report=report)["status"],
                         "report_written")
        self.assertEqual(self.ledger.read(DAY)["owner_execution"], "exec-b")

    def test_transient_emulator_contention_is_retried_not_hidden(self):
        from app import ledger as adapter
        failure = ValueError("Failed to commit transaction in 5 attempts.")
        failure.__cause__ = Aborted("Transaction lock timeout.")
        client = Mock()
        client.transaction.side_effect = [object(), object()]
        fake_run = Mock(side_effect=[failure, ("record", "busy", None)])
        with patch.object(adapter.firestore, "transactional", return_value=fake_run):
            with patch.object(adapter, "sleep") as backoff:
                result = FirestoreLedger(client).claim(
                    business_date=DAY, execution="exec-b", task_attempt=0,
                    source_object=SOURCE, source_generation="123")
        self.assertEqual(result, ("record", "busy", None))
        self.assertEqual(client.transaction.call_count, 2)
        backoff.assert_called_once()

    def test_non_contention_value_error_remains_visible(self):
        from app import ledger as adapter
        client = Mock()
        fake_run = Mock(side_effect=ValueError("invalid business state"))
        with patch.object(adapter.firestore, "transactional", return_value=fake_run):
            with self.assertRaisesRegex(ValueError, "invalid business state"):
                FirestoreLedger(client).claim(
                    business_date=DAY, execution="exec-a", task_attempt=0,
                    source_object=SOURCE, source_generation="123")
        self.assertEqual(client.transaction.call_count, 1)

    def test_missing_source_can_be_recovered_after_upload(self):
        item, disposition = self.ledger.mark_missing_input(DAY)
        self.assertEqual((disposition, item["status"]), ("missing_input", "missing_input"))
        item, disposition, token = self.claim("after-upload")
        self.assertEqual((disposition, item["status"]), ("claimed", "running"))
        self.assertEqual(token["fence"], 1)
        self.assertEqual(self.ledger.read(DAY)["source_generation"], "123")


if __name__ == "__main__":
    unittest.main()
