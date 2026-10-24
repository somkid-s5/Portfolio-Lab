import base64
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_secrets as module


PASSWORD = "P" * 43
AUTH_PASSWORD_HASH = "scrypt:32768:8:1$abcdefghijklmnop$" + "a" * 128


def make_bundle(path, bootstrap_password=PASSWORD):
    path.mkdir(mode=0o700)
    os.chmod(path, 0o700)
    roles = {"alice": "customer", "bob": "customer", "operator": "operator"}
    auth = {
        "session_key": "a" * 64,
        "users": {
            name: {"role": role, "password_hash": AUTH_PASSWORD_HASH}
            for name, role in roles.items()
        },
    }
    demo = {
        name: {"role": role, "password": "D" * 32}
        for name, role in roles.items()
    }
    values = {
        "auth.json": auth,
        "demo-logins.json": demo,
        "db-portal.json": {"user": "order_api", "password": "A" * 43, "database": "order_queue"},
        "db-worker.json": {"user": "order_worker", "password": "B" * 43, "database": "order_queue"},
        "db-dispatcher.json": {"user": "outbox_dispatcher", "password": "C" * 43, "database": "order_queue"},
        "db-bootstrap.json": {"user": "postgres", "password": bootstrap_password, "database": "order_queue"},
    }
    for name, value in values.items():
        target = path / name
        target.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(target, 0o600)


class FakeAPI:
    def __init__(self):
        self.versions = {}
        self.password_updates = []
        self.add_calls = []
        self.fail_after_add = False
        self.fail_operation_poll = False
        self.wrong_instance = False
        self.wrong_secret_replica = False

    def request(self, method, url, body=None, not_found_ok=False):
        if "/instances/lab007-orders/users?" in url and method == "GET":
            return {"items": [{"name": "postgres"}]}
        if "/instances/lab007-orders/users?" in url and method == "PUT":
            self.password_updates.append(body["password"])
            return {"name": "projects/lab-project/operations/op-1"}
        if "/operations/op-1" in url:
            if self.fail_operation_poll:
                raise module.SafeFailure("google_api_request_failed")
            return {"status": "DONE"}
        if "/instances/lab007-orders" in url:
            return {
                "name": "lab007-orders" if not self.wrong_instance else "other",
                "region": "asia-southeast1",
                "databaseVersion": "POSTGRES_16",
                "state": "RUNNABLE",
                "settings": {
                    "ipConfiguration": {
                        "ipv4Enabled": False,
                        "privateNetwork": "projects/lab-project/global/networks/lab007-vpc",
                    }
                },
            }
        if "/projects/lab-project/secrets/" in url:
            secret_id = url.split("/secrets/")[1].split("/")[0].split(":")[0]
            if url.endswith("/versions/latest:access"):
                version = self.versions.get(secret_id)
                if version is None:
                    if not_found_ok:
                        return None
                    raise AssertionError("unexpected missing-version read")
                return {
                    "name": f"projects/lab-project/secrets/{secret_id}/versions/{version[0]}",
                    "payload": {"data": base64.b64encode(version[1]).decode("ascii")},
                }
            if method == "GET":
                return {
                    "name": f"projects/lab-project/secrets/{secret_id}",
                    "replication": {
                        "userManaged": {
                            "replicas": [{
                                "location": "us-central1" if self.wrong_secret_replica else "asia-southeast1"
                            }]
                        }
                    },
                }
            if method == "POST":
                self.add_calls.append(secret_id)
                number = str(len([1 for key in self.versions if key == secret_id]) + 1)
                # Use per-secret monotonic version numbers.
                previous = self.versions.get(secret_id)
                number = str(int(previous[0]) + 1) if previous else "1"
                self.versions[secret_id] = (number, base64.b64decode(body["payload"]["data"]))
                if self.fail_after_add:
                    self.fail_after_add = False
                    raise module.SafeFailure("google_api_request_failed")
                return {"name": f"projects/lab-project/secrets/{secret_id}/versions/{number}"}
        raise AssertionError((method, url))


class SecretPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "private"
        make_bundle(self.directory)
        self.api = FakeAPI()

    def tearDown(self):
        self.temp.cleanup()

    def test_first_publish_and_rerun_preserve_password_and_versions(self):
        first = module.publish("lab-project", self.directory, initialize=True, api=self.api)
        self.assertEqual(first["postgres_password"], "initialized")
        self.assertEqual(len(first["versions"]), 5)
        self.assertEqual(len(self.api.password_updates), 1)
        self.assertEqual(self.api.password_updates, [PASSWORD])
        second = module.publish("lab-project", self.directory, api=self.api)
        self.assertEqual(second["postgres_password"], "preserved")
        self.assertEqual(len(second["versions_reused"]), 5)
        self.assertEqual(len(self.api.password_updates), 1)
        self.assertEqual(len(self.api.add_calls), 5)

    def test_first_run_requires_explicit_initial_password_flag(self):
        with self.assertRaisesRegex(module.SafeFailure, "first_run_requires_initialize_flag"):
            module.publish("lab-project", self.directory, api=self.api)
        self.assertEqual(self.api.password_updates, [])
        self.assertEqual(self.api.add_calls, [])
        self.assertFalse((self.directory / module.STATE_NAME).exists())

    def test_existing_different_secret_is_refused_before_any_mutation(self):
        self.api.versions["lab007-auth"] = ("7", b"another bundle")
        with self.assertRaisesRegex(module.SafeFailure, "refuse_rotation"):
            module.publish("lab-project", self.directory, initialize=True, api=self.api)
        self.assertEqual(self.api.password_updates, [])
        self.assertEqual(self.api.add_calls, [])

    def test_unknown_add_reply_resolves_by_reading_latest_on_rerun(self):
        self.api.fail_after_add = True
        with self.assertRaisesRegex(module.SafeFailure, "google_api_request_failed"):
            module.publish("lab-project", self.directory, initialize=True, api=self.api)
        self.assertEqual(len(self.api.add_calls), 1)
        result = module.publish("lab-project", self.directory, api=self.api)
        self.assertEqual(len(result["versions_reused"]), 1)
        self.assertEqual(len(self.api.add_calls), 5)
        self.assertEqual(self.api.versions["lab007-auth"][1],
                         (self.directory / "auth.json").read_bytes())

    def test_unknown_password_operation_keeps_pending_state_and_reuses_same_password(self):
        self.api.fail_operation_poll = True
        with self.assertRaisesRegex(module.SafeFailure, "google_api_request_failed"):
            module.publish("lab-project", self.directory, initialize=True, api=self.api)
        state = json.loads((self.directory / module.STATE_NAME).read_text())
        self.assertEqual(state["password_state"], "pending")
        self.assertEqual(self.api.add_calls, [])
        self.api.fail_operation_poll = False
        with patch.object(module.time, "sleep"):
            result = module.publish("lab-project", self.directory, api=self.api)
        self.assertEqual(result["postgres_password"], "initialized")
        self.assertEqual(self.api.password_updates, [PASSWORD, PASSWORD])

    def test_state_binds_same_bundle_and_project(self):
        module.publish("lab-project", self.directory, initialize=True, api=self.api)
        with self.assertRaisesRegex(module.SafeFailure, "bundle_or_project_mismatch"):
            module.publish("other-project", self.directory, api=self.api)
        self.assertEqual(len(self.api.password_updates), 1)

    def test_bundle_directory_and_files_require_private_modes(self):
        os.chmod(self.directory / "auth.json", 0o644)
        with self.assertRaisesRegex(module.SafeFailure, "permissions_invalid"):
            module.validate_bundle(self.directory)
        os.chmod(self.directory / "auth.json", 0o600)
        os.chmod(self.directory, 0o755)
        with self.assertRaisesRegex(module.SafeFailure, "permissions_invalid"):
            module.validate_bundle(self.directory)

    def test_symlink_bundle_file_is_rejected(self):
        target = self.directory / "auth.json"
        target.unlink()
        target.symlink_to(self.directory / "db-bootstrap.json")
        with self.assertRaisesRegex(module.SafeFailure, "private_bundle_invalid"):
            module.validate_bundle(self.directory)

    def test_runtime_database_user_names_match_application_contract(self):
        self.assertEqual(module.DB_USERS["db-worker.json"], "order_worker")
        self.assertEqual(module.DB_USERS["db-portal.json"], "order_api")
        self.assertEqual(module.DB_USERS["db-dispatcher.json"], "outbox_dispatcher")

    def test_wrong_cloud_instance_is_refused(self):
        self.api.wrong_instance = True
        with self.assertRaisesRegex(module.SafeFailure, "does_not_match_lab"):
            module.publish("lab-project", self.directory, initialize=True, api=self.api)
        self.assertEqual(self.api.password_updates, [])

    def test_stdout_contains_no_private_bundle_value(self):
        module.publish("lab-project", self.directory, initialize=True, api=self.api)
        self.api.password_updates.clear()
        stdout = io.StringIO()
        with patch.object(module, "_access_token", return_value="token-never-printed"), \
             patch.object(module, "GoogleAPI", return_value=self.api), \
             contextlib.redirect_stdout(stdout):
            result = module.main(["--project", "lab-project", "--bundle", str(self.directory)])
        self.assertEqual(result, 0)
        self.assertNotIn(PASSWORD, stdout.getvalue())
        self.assertNotIn("token-never-printed", stdout.getvalue())
        self.assertIn("secret_publish_complete", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
