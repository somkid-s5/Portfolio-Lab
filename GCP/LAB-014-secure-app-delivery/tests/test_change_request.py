from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("change_request", ROOT / "tools" / "check_change_request.py")
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class ChangeRequestTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
        self.record = {
            "request_id": "CR-2026-01",
            "owner": "user:engineer@example.com",
            "reason": "Request a time-bounded exception review for a specific release digest.",
            "resource_scope": "projects/lab-project-123/attestors/lab014-release-attestor",
            "digest": "sha256:" + "a" * 64,
            "approver": "group:cloud-approvers@example.com",
            "approval_status": "PENDING",
            "approval_reference": "",
            "created_at": "2026-10-24T12:00:00Z",
            "expires_at": "2026-10-31T12:00:00Z",
        }

    def test_accepts_pending_bounded_request_without_changing_policy(self):
        result = module.validate_change_request(self.record, now=self.now)
        self.assertEqual(result["request_id"], "CR-2026-01")
        self.assertEqual(result["approval_status"], "PENDING")

    def test_rejects_expired_unowned_or_self_approved_requests(self):
        cases = [
            ({"expires_at": "2026-10-23T12:00:00Z"}, "expired"),
            ({"owner": ""}, "owner must"),
            ({"approver": "user:engineer@example.com"}, "different identities"),
            ({"approval_status": "APPROVED"}, "approval evidence"),
            ({"digest": "sha256:bad"}, "64 lowercase"),
            ({"expires_at": (self.now + timedelta(days=31)).isoformat()}, "no more than 30 days"),
            ({"unexpected": "not allowed"}, "unknown fields"),
        ]
        for changes, expected in cases:
            with self.subTest(expected=expected):
                value = {**self.record, **changes}
                with self.assertRaisesRegex(module.ChangeRequestError, expected):
                    module.validate_change_request(value, now=self.now)


if __name__ == "__main__":
    unittest.main()
