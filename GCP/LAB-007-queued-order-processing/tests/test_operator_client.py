import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
spec=importlib.util.spec_from_file_location("operator_replay",LAB/"scripts/operator-replay.py")
cli=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
ORIGIN="https://lab007-portal-123456789.asia-southeast1.run.app"
EVENT="a"*32
DIGEST="b"*64


class Response(io.BytesIO):
    status=200


class OperatorClientTests(unittest.TestCase):
    def test_origin_is_https_cloud_run_service_only_without_redirects_or_userinfo(self):
        self.assertEqual(cli.origin_url(ORIGIN+"/"),ORIGIN)
        for value in ("http://localhost:8080","https://user:pass@lab007-portal-123.a.run.app",
            ORIGIN+"?x=secret",ORIGIN+"/api/login",ORIGIN+":443",
            "https://lab007-portal-123.run.app.attacker.example","https://attacker.example"):
            with self.assertRaises(ValueError):
                cli.origin_url(value)
        with self.assertRaises(ValueError):
            cli.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_journal_is_durable_private_and_reused_without_replacing_key(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"journal"/"event.json"
            first=cli.journal(target,ORIGIN,EVENT,DIGEST,"dependency_restored")
            contents=target.read_bytes()
            again=cli.journal(target,ORIGIN,EVENT,DIGEST,"dependency_restored")
            self.assertEqual(first,again)
            self.assertEqual(target.read_bytes(),contents)
            self.assertEqual(len(first["idempotency_key"]),32)
            if os.name=="posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode),0o700)

    def test_mismatched_or_partial_journal_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"request.json"
            cli.journal(target,ORIGIN,EVENT,DIGEST,"dependency_restored")
            before=target.read_bytes()
            with self.assertRaises(ValueError):
                cli.journal(target,ORIGIN,EVENT,"c"*64,"dependency_restored")
            self.assertEqual(target.read_bytes(),before)
            target.write_bytes(b'{"partial":')
            with self.assertRaises(ValueError):
                cli.journal(target,ORIGIN,EVENT,DIGEST,"dependency_restored")
            self.assertEqual(target.read_bytes(),b'{"partial":')

    def test_private_reader_rejects_world_readable_files_symlinks_and_oversize(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"private.json"
            path.write_bytes(b'{"ok":true}')
            if os.name=="posix":
                path.chmod(0o644)
                with self.assertRaises(ValueError):cli.private_read(path)
                path.chmod(0o600)
                link=Path(folder)/"link"
                link.symlink_to(path)
                with self.assertRaises(OSError):cli.private_read(link)
            path.write_bytes(b"x"*4097)
            with self.assertRaises(ValueError):cli.private_read(path)

    def test_http_is_bounded_same_origin_and_cookie_csrf_rotate_without_logging(self):
        opener=Mock()
        opener.open.side_effect=[
            Response(cli.canonical({"csrf":"a"*64})),
            Response(cli.canonical({"user":"operator","role":"operator","csrf":"b"*64}))]
        client=cli.Portal(ORIGIN,opener=opener)
        with tempfile.TemporaryDirectory() as folder:
            bundle=Path(folder)/"demo-logins.json"
            bundle.write_bytes(cli.canonical({"operator":{"password":"synthetic-private-password","role":"operator"}}))
            bundle.chmod(0o600)
            client.login(bundle)
        self.assertEqual(client.csrf,"b"*64)
        for call in opener.open.call_args_list:
            self.assertTrue(call.args[0].full_url.startswith(ORIGIN+"/api/"))
            self.assertEqual(call.kwargs["timeout"],10)
        login=opener.open.call_args_list[1].args[0]
        self.assertEqual(json.loads(login.data)["username"],"operator")
        self.assertEqual(login.get_header("X-csrf-token"),"a"*64)
        with self.assertRaises(ValueError):client.request("https://attacker.example")
        opener.open.side_effect=[Response(b"x"*65537)]
        with self.assertRaises(ValueError):client.request("/api/session")

    def test_prepare_validates_binding_and_returns_only_safe_fields(self):
        body={"idempotency_key":"c"*32,"source_digest":DIGEST,"reason":"dependency_restored"}
        response={"event_id":EVENT,"source_digest":DIGEST,"reason":"dependency_restored",
            "epoch":1,"outcome":"prepared","replayed":False,"payload":"private-secret"}
        client=cli.Portal(ORIGIN,opener=Mock())
        client.request=Mock(return_value=response)
        result=client.prepare(EVENT,body)
        self.assertNotIn("payload",result)
        for field,value in (("event_id","d"*32),("source_digest","f"*64),("epoch",True),
                            ("outcome","published"),("replayed","true")):
            bad=dict(response)
            bad[field]=value
            client.request.return_value=bad
            with self.assertRaises(ValueError):client.prepare(EVENT,body)

    def test_cli_keeps_journal_after_unknown_outcome_and_sanitizes_stdout(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"request.json"
            args=["operator-replay.py","--portal",ORIGIN,"--demo-logins","private-secret-path",
                  "--event-id",EVENT,"--source-digest",DIGEST,"--reason","dependency_restored",
                  "--journal",str(path)]
            output=io.StringIO()
            with patch.object(sys,"argv",args),patch.object(cli,"Portal") as client, \
                 patch("sys.stdout",output):
                client.return_value.prepare.side_effect=TimeoutError("private-secret-payload")
                self.assertEqual(cli.main(),2)
            before=path.read_bytes()
            self.assertNotIn("private-secret",output.getvalue())
            self.assertIn("do_not_ack_dead_letter",output.getvalue())
            with patch.object(sys,"argv",args),patch.object(cli,"Portal") as client, \
                 patch("sys.stdout",io.StringIO()):
                client.return_value.prepare.return_value={"event_id":EVENT,"outcome":"prepared"}
                self.assertEqual(cli.main(),0)
            self.assertEqual(path.read_bytes(),before)


if __name__=="__main__":
    unittest.main()
