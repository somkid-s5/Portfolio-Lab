"""Unit and localhost integration tests for the synthetic quote service."""
from __future__ import annotations

import json
import socket
from contextlib import redirect_stdout
from io import StringIO
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import patch
from urllib.request import Request, urlopen

LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "app"))

from quote_engine.network_probe import probe_worker
from quote_engine.pricing import calculate_quote, validate_rules, validate_quote_request
from quote_engine.server import RuntimeConfig, consume_cpu_budget, load_config, make_handler


RULES = {
    "rules_version": "v1",
    "rates": {"base_thb": 35, "per_kg_thb": 8, "per_km_thb": 0.45},
    "service_multipliers": {"standard": 1, "express": 1.8},
    "estimated_days": {"standard": 3, "express": 1},
}
REQUEST_BODY = {"weight_kg": 2, "distance_km": 100, "service_level": "standard"}


class QuoteEngineTests(unittest.TestCase):
    def test_standard_quote_is_deterministic_and_versioned(self):
        result = calculate_quote(REQUEST_BODY, RULES)
        self.assertEqual(result, {
            "amount_thb": 96.0,
            "currency": "THB",
            "estimated_days": 3,
            "rules_version": "v1",
        })

    def test_express_quote_applies_multiplier_and_eta(self):
        request = {**REQUEST_BODY, "service_level": "express"}
        result = calculate_quote(request, RULES)
        self.assertEqual(result["amount_thb"], 172.8)
        self.assertEqual(result["estimated_days"], 1)

    def test_invalid_numeric_and_service_inputs_are_rejected(self):
        invalid = [
            {**REQUEST_BODY, "weight_kg": True},
            {**REQUEST_BODY, "weight_kg": 0},
            {**REQUEST_BODY, "weight_kg": float("inf")},
            {**REQUEST_BODY, "weight_kg": 10 ** 400},
            {**REQUEST_BODY, "distance_km": 5001},
            {**REQUEST_BODY, "service_level": "same-day"},
            {**REQUEST_BODY, "service_level": []},
            [],
        ]
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_quote_request(payload)

    def test_synthetic_cpu_profile_is_bounded(self):
        consume_cpu_budget(0)
        with self.assertRaises(ValueError):
            consume_cpu_budget(101)
        with self.assertRaises(ValueError):
            consume_cpu_budget(True)

    def test_invalid_rules_are_rejected_before_serving(self):
        for rules in ({}, {**RULES, "rates": {**RULES["rates"], "per_km_thb": -1}}):
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                validate_rules(rules)

    def test_api_and_worker_load_different_secrets(self):
        seen = []
        api = load_config("api", lambda secret_id: seen.append(secret_id) or "test-only-token")
        worker = load_config("worker", lambda secret_id: seen.append(secret_id) or json.dumps(RULES))
        self.assertEqual(api.api_token, "test-only-token")
        self.assertEqual(worker.pricing_rules["rules_version"], "v1")
        self.assertEqual(seen, ["api-bearer-token", "quote-rules"])

    def test_live_api_worker_flow_auth_and_log_redaction(self):
        worker_server, worker_thread, worker_url = self.start_server(
            "worker", RuntimeConfig(pricing_rules=RULES)
        )
        api_server, api_thread, api_url = self.start_server(
            "api", RuntimeConfig(api_token="test-token-never-log", worker_url=worker_url)
        )
        self.addCleanup(self.stop_server, api_server, api_thread)
        self.addCleanup(self.stop_server, worker_server, worker_thread)

        with self.assertLogs("quote-engine", level="INFO") as captured:
            status, result = self.post_json(
                api_url + "/v1/quotes",
                REQUEST_BODY,
                headers={"Authorization": "Bearer test-token-never-log", "X-Request-ID": "case-11-1"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(result["amount_thb"], 96.0)
        self.assertEqual(result["rules_version"], "v1")
        combined = "\n".join(captured.output)
        self.assertIn('"request_id":"case-11-1"', combined)
        self.assertIn('"rules_version":"v1"', combined)
        self.assertIn('"event":"worker_quote_computed"', combined)
        self.assertNotIn("test-token-never-log", combined)
        self.assertNotIn("api-bearer-token", combined)
        self.assertNotIn('"distance_km"', combined)
        self.assertNotIn('"weight_kg"', combined)

        status, denied = self.post_json(
            api_url + "/v1/quotes",
            REQUEST_BODY,
            headers={"Authorization": "Bearer incorrect"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(denied["error"], "unauthorized")
        self.assertNotIn("incorrect", json.dumps(denied))

    def test_invalid_request_and_unavailable_worker_have_safe_errors(self):
        api_server, api_thread, api_url = self.start_server(
            "api", RuntimeConfig(api_token="test-token", worker_url="http://127.0.0.1:1")
        )
        self.addCleanup(self.stop_server, api_server, api_thread)

        status, invalid = self.post_json(
            api_url + "/v1/quotes",
            {**REQUEST_BODY, "distance_km": 99999},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid["error"], "distance_km must be between 1 and 5000")

        status, unavailable = self.post_json(
            api_url + "/v1/quotes",
            REQUEST_BODY,
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(status, 503)
        self.assertEqual(unavailable["error"], "worker_unavailable")
        self.assertNotIn("127.0.0.1", json.dumps(unavailable))

    def test_health_endpoint_does_not_return_runtime_secrets(self):
        server, thread, url = self.start_server(
            "api", RuntimeConfig(api_token="top-secret-token", worker_url="http://worker")
        )
        self.addCleanup(self.stop_server, server, thread)
        with urlopen(url + "/healthz", timeout=2) as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
        self.assertNotIn("top-secret-token", body)
        self.assertIn('"status":"ok"', body)

    def start_server(self, role, config):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(role, config))
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_port}"

    @staticmethod
    def stop_server(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    @staticmethod
    def post_json(url, payload, headers=None):
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())



class NetworkProbeTests(unittest.TestCase):
    def test_policy_probe_reports_only_a_confirmed_timeout_as_expected_denial(self):
        output = StringIO()
        with (
            patch("quote_engine.network_probe.socket.getaddrinfo", return_value=[]),
            patch(
                "quote_engine.network_probe.urlopen",
                side_effect=URLError(socket.timeout("bounded probe timeout")),
            ),
            redirect_stdout(output),
        ):
            result = probe_worker(timeout_seconds=0.2)
        self.assertEqual(result, 0)
        self.assertIn("NETWORK_DENIED", output.getvalue())

    def test_policy_probe_fails_if_worker_is_reachable(self):
        output = StringIO()
        response = type("Response", (), {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *_args: None,
            "read": lambda self, _limit: b"{}",
        })()
        with (
            patch("quote_engine.network_probe.socket.getaddrinfo", return_value=[]),
            patch("quote_engine.network_probe.urlopen", return_value=response),
            redirect_stdout(output),
        ):
            result = probe_worker(timeout_seconds=0.2)
        self.assertEqual(result, 4)
        self.assertIn("NETWORK_ALLOWED", output.getvalue())


if __name__ == "__main__":
    unittest.main()
