from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from app.main import Handler, MEMORY_STORE

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = [
    ("LAB017-REC-001", "Branch router replacement", "NEW", 12500, "quote-001.txt", "Router replacement estimate: 12500 cents."),
    ("LAB017-REC-002", "Warehouse scanner repair", "REVIEW", 45900, "quote-002.txt", "Scanner repair estimate: 45900 cents."),
    ("LAB017-REC-003", "North depot shelving", "APPROVED", 7800, "quote-003.txt", "Shelving order approved: 7800 cents."),
    ("LAB017-REC-004", "Cold room inspection", "REJECTED", 21300, "quote-004.txt", "Inspection estimate: 21300 cents."),
    ("LAB017-REC-005", "Office access panel", "NEW", 9900, "quote-005.txt", "Access panel estimate: 9900 cents."),
]
DRILL_ID = "LAB017-DRILL-01"


class RecordsHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def setUp(self):
        os.environ["MAINTENANCE_MODE"] = "false"
        os.environ["STORAGE_BACKEND"] = "memory"
        MEMORY_STORE.reset()
        with psycopg.connect(os.environ["PG_DSN"]) as conn:
            conn.execute("TRUNCATE public.records RESTART IDENTITY")
        for record_ref, title, status, amount, filename, attachment in FIXTURES:
            code, _ = self.request("/v1/records", "POST", {
                "record_ref": record_ref,
                "drill_id": DRILL_ID,
                "title": title,
                "status": status,
                "amount_cents": amount,
                "attachment_name": filename,
                "attachment_text": attachment,
            })
            self.assertEqual(code, 201)

    def request(self, path, method="GET", payload=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with urlopen(req, timeout=4) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health_readiness_and_fixture_manifest(self):
        code, body = self.request("/healthz")
        self.assertEqual((code, body["status"]), (200, "ok"))
        code, body = self.request("/readyz")
        self.assertEqual((code, body["status"]), (200, "ready"))
        code, manifest = self.request(f"/ops/manifest?drill_id={DRILL_ID}")
        self.assertEqual(code, 200)
        self.assertTrue(manifest["integrity_pass"])
        self.assertTrue(manifest["objects_ok"])
        self.assertEqual(manifest["database"]["count"], 5)
        self.assertEqual(manifest["database"]["total_amount_cents"], 97400)
        self.assertEqual(manifest["database"]["max_id"], 5)
        self.assertEqual(manifest["database"]["sequence_last_value"], 5)
        self.assertTrue(manifest["database"]["sequence_is_called"])
        self.assertEqual(manifest["database"]["by_status"], {
            "APPROVED": 1, "NEW": 2, "REJECTED": 1, "REVIEW": 1,
        })

    def test_record_search_detail_and_attachment(self):
        code, body = self.request(f"/v1/records?drill_id={DRILL_ID}")
        self.assertEqual((code, body["database"]["count"]), (200, 5))
        code, item = self.request("/v1/records/LAB017-REC-003")
        self.assertEqual((code, item["record_ref"]), (200, "LAB017-REC-003"))
        code, attachment = self.request("/v1/records/LAB017-REC-003/attachment")
        self.assertEqual(code, 200)
        self.assertIn("Shelving order approved", attachment["content_utf8"])

    def test_create_is_idempotent_and_conflicts_are_bounded(self):
        payload = {
            "record_ref": "LAB017-CI-1", "drill_id": DRILL_ID, "title": "Test record",
            "status": "NEW", "amount_cents": 1250, "attachment_name": "ci.txt",
            "attachment_text": "CI attachment",
        }
        code, first = self.request("/v1/records", "POST", payload)
        self.assertEqual(code, 201)
        code, second = self.request("/v1/records", "POST", payload)
        self.assertEqual(code, 200)
        self.assertEqual(first["record_id"], second["record_id"])
        code, body = self.request("/v1/records", "POST", {**payload, "title": "Different"})
        self.assertEqual((code, body["error"]), (409, "record_ref_conflict"))
        code, body = self.request("/v1/records", "POST", {**payload, "status": []})
        self.assertEqual((code, body["error"]), (400, "invalid_request"))
        code, body = self.request("/v1/records", "POST", {**payload, "amount_cents": True})
        self.assertEqual((code, body["error"]), (400, "invalid_request"))

    def test_maintenance_keeps_only_health_and_recovery_checks(self):
        os.environ["MAINTENANCE_MODE"] = "true"
        self.assertEqual(self.request("/healthz")[0], 200)
        self.assertEqual(self.request("/readyz")[0], 200)
        self.assertEqual(self.request(f"/ops/manifest?drill_id={DRILL_ID}")[0], 200)
        code, body = self.request(f"/v1/records?drill_id={DRILL_ID}")
        self.assertEqual((code, body["error"]), (503, "maintenance_mode"))
        code, body = self.request("/v1/records", "POST", {
            "record_ref": "LAB017-FROZEN", "drill_id": DRILL_ID, "title": "Frozen",
            "status": "NEW", "amount_cents": 1, "attachment_name": "frozen.txt",
            "attachment_text": "frozen",
        })
        self.assertEqual((code, body["error"]), (503, "maintenance_mode"))

    def test_integrity_endpoint_detects_missing_or_changed_attachment(self):
        key = "records/LAB017-DRILL-01/LAB017-REC-003/quote-003.txt"
        content, content_type, generation = MEMORY_STORE.live[key]
        MEMORY_STORE.live[key] = (b"tampered", content_type, generation)
        code, body = self.request("/v1/records/LAB017-REC-003/attachment")
        self.assertEqual((code, body["error"]), (409, "attachment_integrity_failed"))
        code, body = self.request(f"/ops/manifest?drill_id={DRILL_ID}")
        self.assertEqual(code, 200)
        self.assertFalse(body["integrity_pass"])

    def test_bad_drill_id_unknown_route_and_delete_are_rejected(self):
        self.assertEqual(self.request("/v1/records?drill_id=../other")[0], 400)
        code, body = self.request("/missing")
        self.assertEqual((code, body["error"]), (404, "not_found"))
        code, body = self.request("/v1/records/LAB017-REC-001", "DELETE")
        self.assertEqual((code, body["error"]), (405, "method_not_allowed"))


if __name__ == "__main__":
    unittest.main()
