"""No network or cloud identity; verify the bounded replay transport contract."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

path = Path(__file__).resolve().parents[1]/"scripts"/"replay-storage-event.py"
spec = importlib.util.spec_from_file_location("replay_storage", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
sys.path.insert(0, str(path.parents[1]/"app"))
from storage_events import parse_event

PROJECT = "demo-lab006"
ACCOUNT = "lab006-trigger@demo-lab006.iam.gserviceaccount.com"
ORIGIN = "https://worker-abc.asia-southeast1.run.app"
JOB = "a"*32


class ReplayTests(unittest.TestCase):
    def test_origin_and_identity_binding(self):
        self.assertEqual(module.configuration(
            PROJECT, "lab006-input", JOB, "123", ORIGIN+"/", ACCOUNT), ORIGIN)
        for bad in ("http://worker.run.app", ORIGIN+"?token=x",
                    "https://worker.run.app@attacker.example", ORIGIN+":443"):
            with self.assertRaises(module.ReplayError):
                module.configuration(PROJECT, "lab006-input", JOB, "123", bad, ACCOUNT)
        with self.assertRaises(module.ReplayError):
            module.configuration(PROJECT, "lab006-input", JOB, "123", ORIGIN,
                                 ACCOUNT.replace("demo-lab006", "other-project"))

    def test_payload_uses_real_pinned_metadata(self):
        client = Mock()
        blob = client.bucket.return_value.blob.return_value
        blob.generation = 123
        blob.name = f"incoming/{JOB}/source.csv"
        blob.bucket.name = "lab006-input"
        blob.time_created = datetime(2026, 10, 24, tzinfo=timezone.utc)
        body, source, subject = module.event_payload(
            client, PROJECT, "lab006-input", JOB, "123")
        blob.reload.assert_called_once_with(
            if_generation_match=123, timeout=5, retry=None)
        self.assertEqual(json.loads(body)["timeCreated"], "2026-10-24T00:00:00Z")
        self.assertEqual(source, "//storage.googleapis.com/projects/_/buckets/lab006-input")
        self.assertEqual(subject, "objects/"+blob.name)
        blob.generation = 124
        with self.assertRaises(module.ReplayError):
            module.event_payload(client, PROJECT, "lab006-input", JOB, "123")

    def test_three_events_same_binding_two_ids(self):
        opener = Mock()
        response = Mock(status=204)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener.open.return_value = response
        outcomes = module.replay(opener, ORIGIN, "a.b.c", b"{}", "source", "subject")
        self.assertEqual(len(outcomes), 3)
        requests = [c.args[0] for c in opener.open.call_args_list]
        ids = [r.get_header("Ce-id") for r in requests]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[1], ids[2])
        for call in opener.open.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 10)
            self.assertEqual(call.args[0].get_header("Authorization"), "Bearer a.b.c")
            self.assertEqual(call.args[0].data, b"{}")
        self.assertNotIn("a.b.c", json.dumps(outcomes))
        response.read.assert_not_called()

    def test_replay_envelope_roundtrips_through_actual_receiver_parser(self):
        client = Mock()
        blob = client.bucket.return_value.blob.return_value
        blob.generation = 123
        blob.name = f"incoming/{JOB}/source.csv"
        blob.bucket.name = "lab006-input"
        blob.time_created = datetime(2026, 10, 24, tzinfo=timezone.utc)
        body, source, subject = module.event_payload(
            client, PROJECT, "lab006-input", JOB, "123")
        opener = Mock()
        response = Mock(status=204)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener.open.return_value = response
        module.replay(opener, ORIGIN, "a.b.c", body, source, subject)
        for call in opener.open.call_args_list:
            request = call.args[0]
            event = parse_event(dict(request.header_items()), request.data,
                                "lab006-input")
            self.assertEqual(event.job_id, JOB)
            self.assertEqual(event.generation, "123")
            self.assertEqual(event.finalized_at, blob.time_created)

    def test_unknown_and_http_failure_stop(self):
        opener = Mock()
        opener.open.side_effect = TimeoutError("private transport detail")
        outcomes = module.replay(opener, ORIGIN, "a.b.c", b"{}", "source", "subject")
        self.assertEqual(outcomes[0]["outcome"], "unknown")
        self.assertEqual(opener.open.call_count, 1)
        self.assertNotIn("private", json.dumps(outcomes))
        opener.reset_mock()
        opener.open.side_effect = HTTPError(ORIGIN, 403, "denied", {}, None)
        outcomes = module.replay(opener, ORIGIN, "a.b.c", b"{}", "source", "subject")
        self.assertEqual(outcomes[0]["http_status"], 403)
        self.assertEqual(opener.open.call_count, 1)

    @patch.object(module.subprocess, "run")
    def test_token_is_bounded_and_never_echoes_errors(self, run):
        run.return_value = Mock(returncode=0, stdout="a.b.c\n", stderr="warning")
        self.assertEqual(module.identity_token(ORIGIN, ACCOUNT), "a.b.c")
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertIn("--audiences="+ORIGIN, run.call_args.args[0])
        run.return_value = Mock(returncode=1, stdout="secret", stderr="private")
        with self.assertRaisesRegex(module.ReplayError, "^identity_token_unavailable$"):
            module.identity_token(ORIGIN, ACCOUNT)
        run.side_effect = subprocess.TimeoutExpired("gcloud", 30)
        with self.assertRaises(module.ReplayError):
            module.identity_token(ORIGIN, ACCOUNT)


if __name__ == "__main__":
    unittest.main()
