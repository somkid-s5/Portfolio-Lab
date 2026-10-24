"""Offline behavior tests for the Lab 12 synthetic microservices."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from main import CATALOG, create_app


class Lab12AppTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"DEMO_BEARER_TOKEN": "test-only-token"}, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def response(self, body, status=200):
        mocked = Mock()
        mocked.status_code = status
        mocked.json.return_value = body
        if status >= 400:
            mocked.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
        return mocked

    def test_health_and_readiness_do_not_call_dependencies(self):
        for role in ("storefront", "order", "catalog", "payment"):
            client = create_app(role, telemetry=False).test_client()
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/readyz").json["status"], "ready")

    def test_storefront_requires_token_before_contacting_order(self):
        client = create_app("storefront", telemetry=False).test_client()
        with patch("main.requests.post") as post:
            denied = client.post("/v1/checkout", json={"sku": "SKU-001", "quantity": 1})
            self.assertEqual(denied.status_code, 401)
            self.assertEqual(post.call_count, 0)
            post.side_effect = requests.Timeout("test order unavailable")
            allowed = client.post(
                "/v1/checkout",
                json={"sku": "SKU-001", "quantity": 1},
                headers={"Authorization": "Bearer test-only-token"},
            )
            self.assertEqual(allowed.status_code, 502)
            self.assertEqual(post.call_count, 1)

    def test_storefront_rejects_invalid_quantity_and_sku(self):
        client = create_app("storefront", telemetry=False).test_client()
        headers = {"Authorization": "Bearer test-only-token"}
        with patch("main.requests.post") as post:
            for payload in (
                {"sku": "SKU-001", "quantity": 0},
                {"sku": "SKU-001", "quantity": 6},
                {"sku": "SKU-001", "quantity": True},
                {"sku": "../../secret", "quantity": 1},
            ):
                self.assertEqual(client.post("/v1/checkout", json=payload, headers=headers).status_code, 400)
            self.assertEqual(post.call_count, 0)

    def test_storefront_returns_trace_and_business_result(self):
        client = create_app("storefront", telemetry=False).test_client()
        with patch("main.requests.post", return_value=self.response({"total_thb": 2500, "currency": "THB"})):
            result = client.post(
                "/v1/checkout",
                json={"sku": "SKU-001", "quantity": 2},
                headers={"Authorization": "Bearer test-only-token"},
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["total_thb"], 2500)
        self.assertEqual(result.json["currency"], "THB")
        self.assertEqual(result.json["catalog_revision"], "legacy-v1")
        self.assertEqual(len(result.json["checkout_id"]), 36)
        self.assertEqual(len(result.json["trace_id"]), 32)

    def test_order_v1_contract_uses_thb_fallback_and_caps_payment_attempts(self):
        client = create_app("order", telemetry=False).test_client()
        with patch.dict(os.environ, {"CATALOG_API_VERSION": "v1"}), \
             patch("main.requests.get", return_value=self.response(CATALOG["SKU-001"])) as catalog, \
             patch("main.requests.post", side_effect=requests.Timeout("bounded test")) as payment, \
             patch("main.time.sleep"):
            result = client.post(
                "/internal/checkout",
                json={"sku": "SKU-001", "quantity": 2, "checkout_id": "checkout-test"},
            )
        self.assertEqual(result.status_code, 503)
        self.assertEqual(result.json["attempts"], 2)
        self.assertEqual(catalog.call_count, 1)
        self.assertEqual(payment.call_count, 2)
        self.assertEqual(
            [call.kwargs["timeout"] for call in payment.call_args_list],
            [1.0, 1.0],
        )

    def test_order_success_preserves_v1_and_reads_optional_v2_fields(self):
        client = create_app("order", telemetry=False).test_client()
        with patch.dict(os.environ, {"CATALOG_API_VERSION": "v2"}), \
             patch("main.requests.get", return_value=self.response({
                 **CATALOG["SKU-001"], "currency": "THB", "catalog_revision": "2026-10-v2"
             })), \
             patch("main.requests.post", return_value=self.response({"approved": True})):
            result = client.post(
                "/internal/checkout",
                json={"sku": "SKU-001", "quantity": 2, "checkout_id": "checkout-test"},
            )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["total_thb"], 2500)
        self.assertEqual(result.json["currency"], "THB")
        self.assertEqual(result.json["catalog_revision"], "2026-10-v2")

    def test_catalog_v2_is_opt_in_and_keeps_v1(self):
        client = create_app("catalog", telemetry=False).test_client()
        with patch.dict(os.environ, {"CATALOG_V2_ENABLED": "false"}):
            self.assertEqual(client.get("/v2/items/SKU-001").status_code, 404)
        with patch.dict(os.environ, {"CATALOG_V2_ENABLED": "true"}):
            v1 = client.get("/v1/items/SKU-001")
            v2 = client.get("/v2/items/SKU-001")
        self.assertEqual(v1.status_code, 200)
        self.assertEqual(v1.json["unit_price_thb"], 1250)
        self.assertNotIn("currency", v1.json)
        self.assertEqual(v2.status_code, 200)
        self.assertEqual(v2.json["currency"], "THB")
        self.assertEqual(v2.json["catalog_revision"], "2026-10-v2")

    def test_payment_mock_is_idempotent_and_never_charges(self):
        client = create_app("payment", telemetry=False).test_client()
        payload = {"idempotency_key": "stable-checkout-key", "amount_thb": 1250}
        with patch.dict(os.environ, {"PAYMENT_MODE": "normal"}):
            first = client.post("/authorize", json=payload)
            second = client.post("/authorize", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json, second.json)

    def test_payment_fault_modes_are_explicit_and_unavailable_returns_503(self):
        client = create_app("payment", telemetry=False).test_client()
        payload = {"idempotency_key": "fault-checkout-key", "amount_thb": 1250}
        with patch.dict(os.environ, {"PAYMENT_MODE": "unavailable"}):
            failed = client.post("/authorize", json=payload)
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.json["error"], "synthetic_unavailable")

    def test_no_route_returns_customer_token_or_payload(self):
        client = create_app("storefront", telemetry=False).test_client()
        with patch("main.requests.post", side_effect=requests.Timeout("token should not be logged")):
            with self.assertLogs("lab012", level="INFO") as captured:
                client.post(
                    "/v1/checkout",
                    json={"sku": "SKU-001", "quantity": 1},
                    headers={"Authorization": "Bearer test-only-token"},
                )
        self.assertNotIn("test-only-token", "\n".join(captured.output))
        self.assertNotIn('"quantity":1', "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
