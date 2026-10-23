import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from signed_access import Access
from job_state import Conflict, new_job

NOW = datetime.now(timezone.utc)
JOB_ID = "a"*32
UPLOAD = "lab006-upload@demo-lab006.iam.gserviceaccount.com"
DOWNLOAD = "lab006-download@demo-lab006.iam.gserviceaccount.com"


class SignedAccessTests(unittest.TestCase):
    def setUp(self):
        self.jobs = Mock()
        self.job = new_job(JOB_ID, "alice", NOW)
        self.jobs.read_owned.return_value = self.job
        self.tokens = Mock(return_value="temporary-token-never-log")
        self.client = storage.Client(project="demo-lab006",
                                     credentials=AnonymousCredentials())
        self.access = Access(self.jobs, self.client, "lab006-incoming",
                             "lab006-results", UPLOAD, DOWNLOAD, self.tokens,
                             clock=lambda: NOW)

    def test_real_sdk_policy_contains_exact_key_mime_size_and_no_acl(self):
        with patch("google.cloud.storage.client._sign_message",
                   return_value=base64.b64encode(b"signature").decode()) as signer:
            result = self.access.upload_policy(JOB_ID, "alice")
        self.jobs.read_owned.assert_called_once_with(JOB_ID, "alice")
        policy = json.loads(base64.b64decode(result["fields"]["policy"]))
        self.assertIn({"bucket": "lab006-incoming"}, policy["conditions"])
        self.assertIn({"key": f"incoming/{JOB_ID}/source.csv"}, policy["conditions"])
        self.assertIn(["content-length-range", 1, 1048576], policy["conditions"])
        self.assertIn({"Content-Type": "text/csv"}, policy["conditions"])
        self.assertIn({"success_action_status": "201"}, policy["conditions"])
        self.assertNotIn("acl", result["fields"])
        self.assertTrue(result["url"].startswith("https://"))
        self.assertEqual(signer.call_args.args[1:], ("temporary-token-never-log", UPLOAD))

    def test_owner_denial_and_expiry_never_sign(self):
        self.jobs.read_owned.side_effect = KeyError("job_not_found")
        with self.assertRaises(KeyError):
            self.access.upload_policy(JOB_ID, "bob")
        self.tokens.assert_not_called()
        self.jobs.read_owned.side_effect = None
        self.job["expires_at"] = NOW
        with self.assertRaises(Conflict):
            self.access.download_link(JOB_ID, "alice")
        self.tokens.assert_not_called()

    def test_upload_deadline_state_and_binding_are_checked_before_token(self):
        for field, value in [("upload_deadline", NOW), ("state", "processing"),
                             ("input_generation", "123"),
                             ("object_name", "incoming/other/source.csv")]:
            original = dict(self.job)
            self.job[field] = value
            with self.subTest(field=field), self.assertRaises(Conflict):
                self.access.upload_policy(JOB_ID, "alice")
            self.job.clear()
            self.job.update(original)
        self.tokens.assert_not_called()

    def test_real_sdk_download_pins_generation_and_caps_expiry(self):
        self.job.update(state="succeeded", input_generation="123",
                        output_generation="456",
                        output_name=f"results/{JOB_ID}/123/v1/summary.json",
                        expires_at=NOW+timedelta(seconds=25))
        with patch("google.cloud.storage._signing._sign_message",
                   return_value=base64.b64encode(b"signature").decode()) as signer:
            result = self.access.download_link(JOB_ID, "alice")
        query = parse_qs(urlsplit(result["url"]).query)
        self.assertEqual(query["generation"], ["456"])
        self.assertLessEqual(int(query["X-Goog-Expires"][0]), 25)
        self.assertEqual(query["response-content-type"], ["application/json"])
        self.assertIn("attachment", query["response-content-disposition"][0])
        self.assertEqual(signer.call_args.args[2], DOWNLOAD)

    def test_unready_or_corrupt_output_cannot_be_signed(self):
        with self.assertRaises(Conflict):
            self.access.download_link(JOB_ID, "alice")
        self.job.update(state="succeeded", input_generation="123",
                        output_name="results/other/file", output_generation="456")
        with self.assertRaises(Conflict):
            self.access.download_link(JOB_ID, "alice")
        self.tokens.assert_not_called()


if __name__ == "__main__":
    unittest.main()
