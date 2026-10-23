import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"scripts"))
spec = importlib.util.spec_from_file_location("boundary_tool", LAB/"scripts/test-upload-boundary.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

JOB = "a"*32
BUCKET = "lab006-test-incoming"


def policy():
    conditions = [["content-length-range",1,1048576], {"bucket":BUCKET},
                  {"key":f"incoming/{JOB}/source.csv"}, {"Content-Type":"text/csv"}]
    encoded = base64.b64encode(json.dumps({"conditions":conditions}).encode()).decode()
    return {"url":"https://storage.googleapis.com/"+BUCKET+"/",
            "fields":{"key":f"incoming/{JOB}/source.csv", "Content-Type":"text/csv",
                      "policy":encoded, "x-goog-signature":"dummy-signature"}}


class BoundaryTests(unittest.TestCase):
    def test_multipart_is_bounded_and_changes_only_intended_field_or_size(self):
        positive = tool.multipart(policy(), JOB, BUCKET, "positive")
        self.assertIn(tool.SOURCE, positive.data)
        mime = tool.multipart(policy(), JOB, BUCKET, "mime")
        self.assertIn(b"application/octet-stream", mime.data)
        oversize = tool.multipart(policy(), JOB, BUCKET, "oversize")
        self.assertGreater(len(oversize.data), 1048576)
        self.assertLess(len(oversize.data), 1048576+20000)
        self.assertNotIn(b"Authorization:", oversize.data)

    def test_foreign_endpoints_and_mismatched_policy_are_refused(self):
        for update in [{"url":"https://evil.invalid/upload"},
                       {"url":"http://storage.googleapis.com/"+BUCKET}]:
            value = policy()
            value.update(update)
            with self.assertRaises(ValueError):
                tool.multipart(value, JOB, BUCKET, "mime")
        value = policy()
        value["fields"]["key"] = "incoming/other/source.csv"
        with self.assertRaises(ValueError):
            tool.multipart(value, JOB, BUCKET, "mime")

    def test_storage_reply_exposes_only_status_and_safe_code(self):
        response = Mock(code=403)
        response.read.return_value = b"<Error><Code>AccessDenied</Code><Message>private-policy-secret</Message></Error>"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = tool.send(tool.multipart(policy(), JOB, BUCKET, "mime"), opener=opener)
        self.assertEqual(result, {"storage_http":403,"storage_error_code":"AccessDenied"})
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)

    def test_stored_journal_is_not_retest_and_binding_prevents_new_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"journal.json"
            record = {"origin":"https://portal.run.app", "bucket":BUCKET,
                      "case":"mime","owner":"alice", "key":"request-key-123",
                      "result":{"storage_http":403,"job_id":JOB,"case":"mime"}}
            tool.save(path, record, new=True)
            with patch.object(tool, "Client") as client:
                result = tool.run("https://portal.run.app", "unused", path, BUCKET, "mime")
                self.assertEqual(result["event"], "stored_result_not_retest")
                client.assert_not_called()
                with self.assertRaises(ValueError):
                    tool.run("https://portal.run.app", "unused", path, BUCKET, "oversize")
                client.assert_not_called()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
