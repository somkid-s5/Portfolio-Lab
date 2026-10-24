import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "load-orders.py"
spec = importlib.util.spec_from_file_location("lab007_load_orders", SCRIPT)
load_orders = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load_orders)


class FakePortal:
    def __init__(self, origin, *, available=100, fail_once=False):
        self.origin = origin
        self.available = available
        self.available_values = None
        self.fail_once = fail_once
        self.keys = []
        self.order_id = "d" * 32
        self.order_sequence = 0

    def login(self, customer, password):
        self.login_args = (customer, password)

    def catalog_available(self, sku):
        self.sku = sku
        if self.available_values is not None:
            return self.available_values.pop(0)
        return self.available

    def create_order(self, entry):
        self.keys.append(entry["idempotency_key"])
        self.order_sequence += 1
        if self.fail_once:
            self.fail_once = False
            raise load_orders.OutcomeUnknown()
        order_id = "d" * 30 + f"{self.order_sequence:02x}"
        return 200, order_id, "confirmed", True

    def orders_page(self, cursor, timeout):
        return [{"order_id": self.order_id, "state": "confirmed"}], None


class LoadOrdersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        if os.name == "posix":
            self.root.chmod(0o700)
        self.credentials = self.root / "demo-logins.json"
        self.credentials.write_text(json.dumps({
            "alice": {"password": "private-demo-password-" + "x" * 24, "role": "customer"}
        }), encoding="utf-8")
        if os.name == "posix":
            self.credentials.chmod(0o600)
        self.journal = self.root / "workload.json"

    def tearDown(self):
        self.temp.cleanup()

    def args(self, *, resume=False, count=1, observe=0):
        return SimpleNamespace(
            portal="https://lab007-portal-abc123-as.a.run.app",
            demo_logins=str(self.credentials),
            journal=str(self.journal),
            customer=None,
            count=None if resume else count,
            sku=None if resume else "BOOK-01",
            quantity=None if resume else 1,
            rate=None if resume else 1.0,
            observe_seconds=None if resume else observe,
            resume=resume,
        )

    def test_origin_rejects_non_cloud_run_and_mutating_destinations(self):
        for value in ("http://lab007-portal-abc123-as.a.run.app",
                      "https://user@lab007-portal-abc123-as.a.run.app",
                      "https://attacker.example",
                      "https://lab007-portal-abc123-as.a.run.app/path"):
            with self.subTest(value=value), self.assertRaises(load_orders.SafeFailure):
                load_orders.origin_url(value)

    def test_settings_bound_orders_rate_and_total_send_window(self):
        self.assertEqual(load_orders.validate_settings(100, "BOOK-01", 1, 2.0, 60), 2.0)
        for args in ((101, "BOOK-01", 1, 2.0, 0),
                     (10, "BOOK-01", 4, 1.0, 0),
                     (100, "BOOK-01", 1, 1.0, 0),
                     (1, "BOOK-01", 1, 2.1, 0),
                     (1, "BOOK-01", 1, 1.0, 61)):
            with self.subTest(args=args), self.assertRaises(load_orders.SafeFailure):
                load_orders.validate_settings(*args)

    def test_unknown_post_keeps_same_key_for_explicit_resume(self):
        first = FakePortal("https://lab007-portal-abc123-as.a.run.app", fail_once=True)
        outputs = []
        result = load_orders.execute(self.args(), client_factory=lambda _: first,
                                     sleep_fn=lambda _: None, emit=outputs.append)
        self.assertEqual(result, 2)
        self.assertIn("order_outcome_unknown", outputs[-1])
        journal = load_orders.validate_journal(load_orders.private_read(self.journal))
        key = journal["orders"][0]["idempotency_key"]
        self.assertEqual(journal["orders"][0]["attempts"], 1)
        self.assertIsNone(journal["orders"][0]["order_id"])
        self.assertNotIn("private-demo-password", "".join(outputs))

        second = FakePortal("https://lab007-portal-abc123-as.a.run.app")
        result = load_orders.execute(self.args(resume=True), client_factory=lambda _: second,
                                     sleep_fn=lambda _: None, emit=outputs.append)
        self.assertEqual(result, 0)
        self.assertEqual(first.keys, [key])
        self.assertEqual(second.keys, [key])
        saved = load_orders.private_read(self.journal)
        self.assertEqual(saved["orders"][0]["order_id"], second.order_id)
        self.assertEqual(saved["orders"][0]["state"], "confirmed")

    def test_stock_preflight_stops_before_first_order_mutation(self):
        client = FakePortal("https://lab007-portal-abc123-as.a.run.app", available=0)
        outputs = []
        result = load_orders.execute(self.args(count=3), client_factory=lambda _: client,
                                     sleep_fn=lambda _: None, emit=outputs.append)
        self.assertEqual(result, 2)
        self.assertEqual(client.keys, [])
        self.assertIn("insufficient_stock", outputs[-1])

    def test_inventory_before_after_is_saved_for_capacity_evidence(self):
        client = FakePortal("https://lab007-portal-abc123-as.a.run.app")
        client.available_values = [100, 97]
        outputs = []
        result = load_orders.execute(self.args(count=3), client_factory=lambda _: client,
                                     sleep_fn=lambda _: None, emit=outputs.append)
        self.assertEqual(result, 0)
        journal = load_orders.private_read(self.journal)
        self.assertEqual((journal["stock_before"], journal["stock_after"]), (100, 97))
        summary = json.loads(outputs[-1])
        self.assertEqual(summary["stock_decrease"], 3)
        self.assertEqual(len({e["order_id"] for e in summary["orders"]}), 3)

    def test_new_run_refuses_overwrite_and_journal_is_private(self):
        client = FakePortal("https://lab007-portal-abc123-as.a.run.app")
        self.assertEqual(load_orders.execute(self.args(), client_factory=lambda _: client,
                                             sleep_fn=lambda _: None, emit=lambda _: None), 0)
        if os.name == "posix":
            self.assertEqual(self.journal.stat().st_mode & 0o777, 0o600)
        before = load_orders.private_read(self.journal)["run_id"]
        outputs = []
        self.assertEqual(load_orders.execute(self.args(), client_factory=lambda _: client,
                                             sleep_fn=lambda _: None, emit=outputs.append), 2)
        self.assertNotIn("private-demo-password", "".join(outputs))
        self.assertEqual(load_orders.private_read(self.journal)["run_id"], before)


if __name__ == "__main__":
    unittest.main()
