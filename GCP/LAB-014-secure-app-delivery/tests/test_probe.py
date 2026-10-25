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

    def test_selects_exact_candidate_revision_tag_and_traffic_share(self):
        statuses = [
            {"revision": "quote-api-00003-old", "tag": "prior", "percent": 90, "uri": "https://prior.example"},
            {"revision": "projects/p/locations/r/services/s/revisions/quote-api-00004-new", "tag": "lab014-candidate", "percent": 10, "uri": "https://candidate.example"},
        ]
        self.assertEqual(
            module.select_revision_url(statuses, "quote-api-00004-new", "lab014-candidate", 10),
            "https://candidate.example",
        )

    def test_cloud_deploy_private_probe_mints_token_for_service_uri(self):
        from unittest.mock import Mock

        credentials = Mock(token="cloud-api-access-token")
        service = {
            "uri": "https://quote-api-abc-uc.a.run.app",
            "trafficStatuses": [{
                "revision": "projects/project/locations/asia-southeast1/services/quote-api/revisions/quote-api-00004",
                "tag": "lab014-candidate",
                "percent": 10,
                "uri": "https://lab014-candidate---quote-api-abc-uc.a.run.app",
            }],
        }
        env = {
            "CLOUD_RUN_PROJECT": "project",
            "CLOUD_RUN_LOCATION": "asia-southeast1",
            "CLOUD_RUN_SERVICE": "projects/project/locations/asia-southeast1/services/quote-api",
            "CLOUD_RUN_REVISION": "quote-api-00004",
            "CLOUD_DEPLOY_TARGET": "production",
            "CLOUD_DEPLOY_PHASE": "canary-10",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            patch("google.auth.default", return_value=(credentials, None)),
            patch("google.oauth2.id_token.fetch_id_token", return_value="private-run-id-token") as mint,
            patch.object(module, "fetch_json", return_value=(200, service)) as fetch,
        ):
            url, headers = module._cloud_run_target_url(3)

        self.assertEqual(url, "https://lab014-candidate---quote-api-abc-uc.a.run.app")
        self.assertEqual(headers, {"Authorization": "Bearer private-run-id-token"})
        self.assertEqual(mint.call_args.args[1], "https://quote-api-abc-uc.a.run.app")
        self.assertIn("Bearer cloud-api-access-token", fetch.call_args.args[2]["Authorization"])
        credentials.refresh.assert_called_once()

    def test_private_target_headers_are_used_for_every_probe_request(self):
        responses = [
            (200, {"status": "ok"}),
            (200, {"currency": "THB", "total_thb": "455.00"}),
            (200, {"commit_sha": "abc123"}),
        ]
        with patch.object(module, "fetch_json", side_effect=responses) as fetch:
            module.verify_once(
                "https://candidate.example",
                Decimal("455.00"),
                3,
                "abc123",
                headers={"Authorization": "Bearer private-run-id-token"},
            )
        self.assertTrue(all(call.args[2]["Authorization"] == "Bearer private-run-id-token" for call in fetch.call_args_list))

    def test_revision_selection_fails_closed_if_candidate_tag_missing(self):
        statuses = [
            {"revision": "quote-api-00004-new", "tag": "prior", "percent": 10, "uri": "https://wrong.example"},
        ]
        with self.assertRaisesRegex(RuntimeError, "exactly one matching"):
            module.select_revision_url(statuses, "quote-api-00004-new", "lab014-candidate", 10)

    def test_revision_selection_requires_expected_traffic_share(self):
        statuses = [{"revision": "quote-api-00004-new", "tag": None, "percent": 10, "uri": "https://service.example"}]
        with self.assertRaisesRegex(RuntimeError, "expected 100 percent"):
            module.select_revision_url(statuses, "quote-api-00004-new", None, 100)

    def test_revision_selection_rejects_non_https_uri(self):
        statuses = [{"revision": "quote-api-00004-new", "tag": "lab014-candidate", "percent": 10, "uri": "http://candidate.example"}]
        with self.assertRaisesRegex(RuntimeError, "valid HTTPS"):
            module.select_revision_url(statuses, "quote-api-00004-new", "lab014-candidate", 10)

    def test_external_http_is_rejected_even_with_allow_flag(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(module.run(["--url", "http://example.test", "--allow-http"]), 2)

    def test_missing_target_is_rejected(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(module.run([]), 2)


if __name__ == "__main__":
    unittest.main()
