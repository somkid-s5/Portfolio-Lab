import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from werkzeug.security import check_password_hash

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "app"))
from portal_runtime import MetadataTokens, read_auth, build_portal

spec = importlib.util.spec_from_file_location("create_demo", LAB / "scripts/create-secrets.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class RuntimeTests(unittest.TestCase):
    def test_bundle_is_private_hash_only_runtime_and_has_matching_logins(self):
        with tempfile.TemporaryDirectory() as folder:
            out = generator.generate(Path(folder) / "new")
            auth = read_auth(out / "auth.json")
            logins = json.loads((out / "demo-logins.json").read_text())
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
            for name in ("auth.json", "demo-logins.json"):
                self.assertEqual(stat.S_IMODE((out / name).stat().st_mode), 0o600)
            self.assertEqual(len(auth["session_key"]), 64)
            for name, user in auth["users"].items():
                self.assertTrue(check_password_hash(user["password_hash"],
                                                    logins[name]["password"]))
                self.assertNotIn(logins[name]["password"], (out / "auth.json").read_text())

    def test_existing_bundle_and_symlink_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            out = generator.generate(Path(folder) / "new")
            original = (out / "auth.json").read_bytes()
            with self.assertRaises(FileExistsError):
                generator.generate(out)
            self.assertEqual((out / "auth.json").read_bytes(), original)
            link = Path(folder) / "alias"
            link.symlink_to(out, target_is_directory=True)
            with self.assertRaises(FileExistsError):
                generator.generate(link)

    def response(self, body, flavor="Google"):
        response = Mock()
        response.headers = {"Metadata-Flavor": flavor}
        response.read.return_value = body
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = context
        return opener, response

    def test_metadata_tokens_are_bounded_and_identity_audience_is_encoded(self):
        opener, response = self.response(
            b'{"access_token":"test-token","token_type":"Bearer"}')
        tokens = MetadataTokens(opener=opener)
        self.assertEqual(tokens.access_token(), "test-token")
        response.read.assert_called_once_with(65537)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("Metadata-flavor"), "Google")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 3)
        opener, response = self.response(b"aaa.bbb.ccc")
        tokens = MetadataTokens(opener=opener)
        self.assertEqual(tokens.id_token("https://worker.run.app"), "aaa.bbb.ccc")
        self.assertIn("audience=https%3A%2F%2Fworker.run.app",
                      opener.open.call_args.args[0].full_url)

    def test_invalid_metadata_never_becomes_a_token(self):
        for payload, flavor in [(b"x"*65537, "Google"), (b"{}", "wrong"),
                                (b'{"access_token":"bad token","token_type":"Bearer"}', "Google")]:
            opener, _ = self.response(payload, flavor)
            with self.subTest(flavor=flavor), self.assertRaises(ValueError):
                MetadataTokens(opener=opener).access_token()
        opener, _ = self.response(b"not-jwt")
        with self.assertRaises(ValueError):
            MetadataTokens(opener=opener).id_token("https://worker.run.app")
        opener.open.reset_mock()
        with self.assertRaises(ValueError):
            MetadataTokens(opener=opener).id_token("https://evil.invalid")
        opener.open.assert_not_called()

    def test_auth_bounds_and_runtime_refuse_emulator_or_private_key_override(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "auth.json"
            path.write_bytes(b"x"*65537)
            with self.assertRaises(ValueError):
                read_auth(path)
            path.write_text('{"session_key":"short","users":{}}')
            with self.assertRaises(ValueError):
                read_auth(path)
        for name in ("FIRESTORE_EMULATOR_HOST", "GOOGLE_APPLICATION_CREDENTIALS"):
            with patch.dict(os.environ, {name: "must-refuse"}), self.assertRaises(ValueError):
                build_portal()


if __name__ == "__main__":
    unittest.main()
