import copy
from contextlib import redirect_stdout
import hashlib
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

from werkzeug.security import check_password_hash

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from auth_config import read_auth,validate_auth
from database import read_credentials
import portal_runtime

spec=importlib.util.spec_from_file_location("lab007_secrets",LAB/"scripts/create-secrets.py")
generator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class AuthConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.folder.cleanup)
        cls.target=generator.generate(Path(cls.folder.name)/"bundle")
        cls.auth=read_auth(cls.target/"auth.json")

    def test_private_generated_hashes_and_role_credentials_match(self):
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode),0o700)
        logins=json.loads((self.target/"demo-logins.json").read_text())
        for name,value in logins.items():
            self.assertTrue(check_password_hash(self.auth["users"][name]["password_hash"],
                                                value["password"]))
            self.assertNotIn(value["password"],(self.target/"auth.json").read_text())
        for role in ("portal","worker","dispatcher"):
            bundle=read_credentials(self.target/("db-"+role+".json"),role)
            self.assertEqual(bundle["database"],"order_queue")
        self.assertEqual(json.loads((self.target/"db-bootstrap.json").read_text())["user"],"postgres")
        for file in self.target.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o600)

    def test_existing_directory_is_refused_without_changing_any_bundle(self):
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.target.iterdir()}
        with self.assertRaises(FileExistsError):
            generator.generate(self.target)
        self.assertEqual(before,{p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in self.target.iterdir()})

    def test_reader_is_bounded_and_rejects_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"auth.json"
            for data in (b"x"*4097,b'{"session_key":"a","session_key":"b"}'):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    read_auth(path)
        value=copy.deepcopy(self.auth)
        value["users"]["alice"]["password_hash"]="scrypt:999999999:8:1$x$x"
        with self.assertRaises(ValueError):
            validate_auth(value)

    def test_cli_reports_no_password_or_auth_hash(self):
        output=io.StringIO()
        with tempfile.TemporaryDirectory() as folder,redirect_stdout(output):
            self.assertEqual(generator.main.__name__,"main")
            with patch.object(generator.sys,"argv",["create-secrets.py","--out",str(Path(folder)/"new")]):
                self.assertEqual(generator.main(),0)
            bundle=Path(folder)/"new"
            private=json.loads((bundle/"demo-logins.json").read_text())
            for value in private.values():
                self.assertNotIn(value["password"],output.getvalue())
            auth=json.loads((bundle/"auth.json").read_text())
            self.assertNotIn(auth["session_key"],output.getvalue())
            for value in auth["users"].values():
                self.assertNotIn(value["password_hash"],output.getvalue())

    def test_portal_runtime_mount_validation_and_role_wiring(self):
        with patch.dict(os.environ,{},clear=True), \
             patch.object(portal_runtime,"read_auth") as read, \
             patch.object(portal_runtime,"build_database") as build:
            with self.assertRaises(ValueError):
                portal_runtime.build_portal()
            read.assert_not_called()
            build.assert_not_called()
        database=Mock()
        with patch.dict(os.environ,{"AUTH_FILE":"/secrets/auth/auth.json",
                                   "AUTH_SECRET_VERSION":"1"},clear=True), \
             patch.object(portal_runtime,"read_auth",return_value=self.auth) as read, \
             patch.object(portal_runtime,"build_database",return_value=database) as build, \
             patch.object(portal_runtime.atexit,"register") as register:
            app=portal_runtime.build_portal()
            read.assert_called_once_with("/secrets/auth/auth.json")
            build.assert_called_once_with("portal")
            self.assertIs(app.extensions["lab007_database"],database)
            database.connect.assert_not_called()
            register.assert_called_once_with(database.close)


if __name__=="__main__":
    unittest.main()
