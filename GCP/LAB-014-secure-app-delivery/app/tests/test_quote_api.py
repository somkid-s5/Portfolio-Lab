from __future__ import annotations

import json
import os
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from quote_api import _decimal_config, create_app


class QuoteApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app("1.00")
        self.client = self.app.test_client()

    def test_health_endpoint_does_not_depend_on_quote_path(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        self.assertRegex(response.headers["X-Request-ID"], r"^[a-f0-9]{32}$")

    def test_quote_contract_returns_deterministic_baseline(self):
        response = self.client.get(
            "/api/v1/quote?origin=bkk&destination=cnx&weight_kg=5",
            headers={"X-Request-ID": "lab14-test-001"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["request_id"], "lab14-test-001")
        self.assertEqual(body["distance_km"], 700)
        self.assertEqual(body["total_thb"], "455.00")
        self.assertEqual(body["currency"], "THB")
        self.assertEqual(response.headers["X-Request-ID"], "lab14-test-001")

    def test_health_can_pass_while_business_regression_changes_quote(self):
        regression = create_app("1.25").test_client()
        self.assertEqual(regression.get("/healthz").status_code, 200)
        quote = regression.get("/api/v1/quote?origin=BKK&destination=CNX&weight_kg=5")
        self.assertEqual(quote.status_code, 200)
        self.assertEqual(quote.get_json()["total_thb"], "560.00")
        self.assertNotEqual(quote.get_json()["total_thb"], "455.00")

    def test_second_supported_route_uses_its_distance(self):
        response = self.client.get("/api/v1/quote?origin=BKK&destination=HKT&weight_kg=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total_thb"], "539.00")

    def test_unknown_route_fails_with_stable_contract(self):
        response = self.client.get("/api/v1/quote?origin=CNX&destination=BKK&weight_kg=5")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "unsupported_route")

    def test_rejects_missing_or_malformed_weight(self):
        for query in ("", "?origin=BKK&destination=CNX", "?origin=BKK&destination=CNX&weight_kg=heavy"):
            response = self.client.get("/api/v1/quote" + query)
            self.assertEqual(response.status_code, 400)

    def test_rejects_non_finite_and_out_of_range_weight(self):
        for value in ("NaN", "Infinity", "0", "1000.01", "-1"):
            response = self.client.get(f"/api/v1/quote?origin=BKK&destination=CNX&weight_kg={value}")
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.get_json()["error"], "invalid_weight")

    def test_rejects_weight_with_more_than_three_decimal_places(self):
        response = self.client.get("/api/v1/quote?origin=BKK&destination=CNX&weight_kg=1.0001")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid_weight_precision")

    def test_invalid_price_factor_fails_closed(self):
        for value in ("NaN", "0.49", "2.01", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                _decimal_config(value)

    def test_price_factor_is_applied_before_rounding(self):
        response = create_app("1.10").test_client().get(
            "/api/v1/quote?origin=BKK&destination=CNX&weight_kg=5"
        )
        self.assertEqual(Decimal(response.get_json()["total_thb"]), Decimal("497.00"))

    def test_version_exposes_build_provenance_without_secrets(self):
        with patch.dict(os.environ, {"COMMIT_SHA": "abc123", "IMAGE_DIGEST": "sha256:" + "a" * 64}):
            response = self.client.get("/version")
        body = response.get_json()
        self.assertEqual(body["commit_sha"], "abc123")
        self.assertTrue(body["image_digest"].startswith("sha256:"))
        self.assertNotIn("token", json.dumps(body).lower())

    def test_invalid_request_id_is_replaced(self):
        response = self.client.get(
            "/api/v1/quote?origin=BKK&destination=CNX&weight_kg=5",
            headers={"X-Request-ID": "bad id injected"},
        )
        self.assertNotIn("bad", response.headers["X-Request-ID"])
        self.assertRegex(response.headers["X-Request-ID"], r"^[a-f0-9]{32}$")


if __name__ == "__main__":
    unittest.main()
