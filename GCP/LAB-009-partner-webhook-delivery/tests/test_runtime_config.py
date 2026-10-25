"""Runtime config loaders reject ambiguous, extra and unsafe environment values."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain import ValidationError
from app.runtime_config import (
    load_partner_endpoints,
    load_partner_queues,
    load_project_id,
    load_simulator_settings,
)


PROJECT = "demo-lab009"
QUEUE = {
    "project_id": PROJECT,
    "location_id": "asia-southeast1",
    "queue_id": "partner-a",
    "partner_id": "partner-a",
    "worker_url": "https://worker-a-1234567890.asia-southeast1.run.app/internal/deliver",
    "task_service_account": "lab09-tasks@demo-lab009.iam.gserviceaccount.com",
    "oidc_audience": "https://worker-a-1234567890.asia-southeast1.run.app",
}
ENDPOINT = {
    "partner_id": "partner-a",
    "url": "https://simulator-a-1234567890.asia-southeast1.run.app/v1/webhooks/partner-a",
    "secret_version": "projects/demo-lab009/secrets/partner-a-hmac/versions/1",
}


class RuntimeConfigTests(unittest.TestCase):
    def test_valid_partner_maps_are_nonsecret_and_checked(self):
        with patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": PROJECT,
            "LAB09_PARTNER_QUEUES_JSON": json.dumps([QUEUE]),
            "LAB09_PARTNER_ENDPOINTS_JSON": json.dumps([ENDPOINT]),
        }, clear=True):
            self.assertEqual(load_project_id(), PROJECT)
            self.assertEqual(load_partner_queues()["partner-a"].queue_id, "partner-a")
            self.assertEqual(load_partner_endpoints()["partner-a"].secret_version, ENDPOINT["secret_version"])

    def test_queue_config_rejects_duplicate_or_extra_fields(self):
        with patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": PROJECT,
            "LAB09_PARTNER_QUEUES_JSON": json.dumps([QUEUE, QUEUE]),
        }, clear=True):
            with self.assertRaises(ValidationError):
                load_partner_queues()
        extra = dict(QUEUE, hmac_secret="must-not-be-an-env-field")
        with patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": PROJECT,
            "LAB09_PARTNER_QUEUES_JSON": json.dumps([extra]),
        }, clear=True):
            with self.assertRaises(ValidationError):
                load_partner_queues()

    def test_invalid_queue_endpoint_fails_at_startup_not_on_first_event(self):
        invalid = dict(QUEUE, worker_url="http://worker.example/internal/deliver")
        with patch.dict(os.environ, {
            "GOOGLE_CLOUD_PROJECT": PROJECT,
            "LAB09_PARTNER_QUEUES_JSON": json.dumps([invalid]),
        }, clear=True):
            with self.assertRaises(ValidationError):
                load_partner_queues()

    def test_duplicate_json_keys_and_oversized_config_are_rejected(self):
        with patch.dict(os.environ, {
            "LAB09_PARTNER_ENDPOINTS_JSON": '[{"partner_id":"partner-a","partner_id":"partner-b","url":"https://simulator.example/v1/webhooks/partner-a","secret_version":"projects/demo-lab009/secrets/key/versions/1"}]'
        }, clear=True):
            with self.assertRaises(ValidationError):
                load_partner_endpoints()
        with patch.dict(os.environ, {
            "LAB09_PARTNER_ENDPOINTS_JSON": " " * 16385,
        }, clear=True):
            with self.assertRaises(ValidationError):
                load_partner_endpoints()

    def test_simulator_requires_pinned_secret_bucket_and_allowlisted_fault(self):
        valid = {
            "LAB09_PARTNER_ID": "partner-a",
            "LAB09_SECRET_VERSION": ENDPOINT["secret_version"],
            "LAB09_RECEIPT_BUCKET": "lab09-partner-a-receipts",
            "LAB09_FAULT_MODE": "normal",
        }
        with patch.dict(os.environ, valid, clear=True):
            self.assertEqual(load_simulator_settings()[0], "partner-a")
        invalid = dict(valid, LAB09_FAULT_MODE="public-control")
        with patch.dict(os.environ, invalid, clear=True):
            with self.assertRaises(ValidationError):
                load_simulator_settings()


if __name__ == "__main__":
    unittest.main()
