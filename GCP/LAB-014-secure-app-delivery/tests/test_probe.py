from __future__ import annotations

import importlib.util
import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_quote", ROOT / "tools" / "verify_quote.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class QuoteProbeTests(unittest.TestCase):
    def test_attempts_and_timeout_are_bounded(self):
        for args in (["--attempts", "0"], ["--attempts", "11"], ["--timeout-seconds", "0"], ["--timeout-seconds", "6"]):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                module.parse_args(args)

    def test_probe_checks_health_quote_and_expected_version(self):
        responses = [
            (200, {"status": "ok"}),
            (200, {"currency": "THB", "total_thb": "455.00"}),
            (200, {"commit_sha": "abc123"}),
        ]
        with patch.object(module, "fetch_json", side_effect=responses) as fetch:
            module.verify_once("https://example.test", Decimal("455.00"), 3, "abc123")
        self.assertEqual(fetch.call_count, 3)

    def test_probe_rejects_healthy_service_with_business_regression(self):
        responses = [(200, {"status": "ok"}), (200, {"currency": "THB", "total_thb": "560.00"})]
        with patch.object(module, "fetch_json", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "business quote mismatch"):
                module.verify_once("https://example.test", Decimal("455.00"), 3)

    def test_probe_rejects_wrong_expected_commit(self):
        responses = [
            (200, {"status": "ok"}),
            (200, {"currency": "THB", "total_thb": "455.00"}),
            (200, {"commit_sha": "other"}),
        ]
        with patch.object(module, "fetch_json", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "commit"):
                module.verify_once("https://example.test", Decimal("455.00"), 3, "abc123")

    def test_selects_exact_candidate_revision_and_tag(self):
        statuses = [
            {"revision": "quote-api-00003-old", "tag": "prior", "percent": 90, "uri": "https://prior.example"},
            {"revision": "projects/p/locations/r/services/s/revisions/quote-api-00004-new", "tag": "lab014-candidate", "percent": 100, "uri": "https://candidate.example"},
        ]
        self.assertEqual(
            module.select_revision_url(statuses, "quote-api-00004-new", "lab014-candidate"),
            "https://candidate.example",
        )

    def test_revision_selection_fails_closed_if_candidate_tag_missing(self):
        statuses = [
            {"revision": "quote-api-00004-new", "tag": "prior", "percent": 100, "uri": "https://wrong.example"},
        ]
        with self.assertRaisesRegex(RuntimeError, "exactly one matching"):
            module.select_revision_url(statuses, "quote-api-00004-new", "lab014-candidate")

    def test_revision_selection_requires_100_percent_tag_route(self):
        statuses = [{"revision": "quote-api-00004-new", "tag": None, "percent": 10, "uri": "https://service.example"}]
        with self.assertRaisesRegex(RuntimeError, "exactly 100 percent"):
            module.select_revision_url(statuses, "quote-api-00004-new", None)

    def test_external_http_is_rejected_even_with_allow_flag(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(module.run(["--url", "http://example.test", "--allow-http"]), 2)

    def test_missing_target_is_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(module.run([]), 2)


if __name__ == "__main__":
    unittest.main()
