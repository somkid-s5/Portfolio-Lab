from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from werkzeug.security import generate_password_hash
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from portal_http import create_app
from job_state import new_job

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
JOB_ID = "a"*32


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth = {"session_key": "s"*64, "users": {
            name: {"password_hash": generate_password_hash("demo-pass"), "role": role}
            for name, role in [("alice", "customer"), ("bob", "customer"),
                               ("operator", "operator")]}}

    def setUp(self):
        self.jobs, self.access, self.logs = Mock(), Mock(), []
        self.app = create_app(self.jobs, self.access, self.auth,
                              clock=lambda: NOW, emit=self.logs.append)
        self.client = self.app.test_client()
        self.csrf = self.get("/api/session").json["csrf"]

    def get(self, path):
        return self.client.get(path, base_url="https://localhost")

    def post(self, path, data, **headers):
        return self.client.post(path, json=data, base_url="https://localhost",
                                headers={"X-CSRF-Token": self.csrf, **headers})

    def login(self, name="alice"):
        response = self.post("/api/login", {"username": name, "password": "demo-pass"})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json["csrf"]
        return response

    def test_login_csrf_rotation_cookie_flags_and_logout(self):
        old = self.csrf
        response = self.login()
        self.assertNotEqual(self.csrf, old)
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)
        self.assertEqual(self.get("/api/session").json["user"], "alice")
        self.assertEqual(self.post("/api/logout", {}).status_code, 200)
        self.assertIsNone(self.get("/api/session").json["user"])

    def test_anonymous_missing_csrf_and_bad_credentials(self):
        self.assertEqual(self.get("/api/jobs/"+JOB_ID).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={}, base_url="https://localhost")
                         .status_code, 403)
        response = self.post("/api/login", {"username": "alice", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.jobs.create.assert_not_called()

    def test_create_uses_session_owner_and_forbids_client_owner(self):
        self.login()
        job = new_job(JOB_ID, "alice", NOW)
        self.jobs.create.return_value = {"job": job, "replayed": False}
        response = self.post("/api/jobs", {"display_name": "sales.csv"},
                             **{"Idempotency-Key": "some-key-123"})
        self.assertEqual(response.status_code, 201)
        self.jobs.create.assert_called_once_with("alice", "some-key-123", "sales.csv",
                                                 max_bytes=1048576, max_rows=10000)
        self.assertEqual(self.post("/api/jobs", {"owner": "bob", "display_name": "x"})
                         .status_code, 400)
        self.jobs.create.return_value["replayed"] = True
        self.assertEqual(self.post("/api/jobs", {"display_name": "sales.csv"},
                                  **{"Idempotency-Key": "some-key-123"}).status_code, 200)

    def test_other_owner_is_404_and_status_does_not_expose_storage_fields(self):
        self.login("bob")
        self.jobs.read_owned.side_effect = KeyError("job_not_found")
        self.assertEqual(self.get("/api/jobs/"+JOB_ID).status_code, 404)
        self.jobs.read_owned.assert_called_with(JOB_ID, "bob")
        self.jobs.read_owned.side_effect = None
        self.jobs.read_owned.return_value = new_job(JOB_ID, "bob", NOW)
        result = self.get("/api/jobs/"+JOB_ID).json
        for field in ("object_name", "attempt_token", "output_name", "owner"):
            self.assertNotIn(field, result)

    def test_link_routes_bind_owner_do_not_log_bearer_capabilities(self):
        self.login()
        self.access.upload_policy.return_value = {
            "url": "https://storage.googleapis.com/private", "fields": {"policy": "secret-policy"}}
        self.assertEqual(self.post(f"/api/jobs/{JOB_ID}/upload-policy", {}).status_code, 200)
        self.access.upload_policy.assert_called_once_with(JOB_ID, "alice")
        self.access.download_link.return_value = {"url": "https://storage.googleapis.com/?secret"}
        self.assertEqual(self.post(f"/api/jobs/{JOB_ID}/download-link", {}).status_code, 200)
        self.access.download_link.assert_called_once_with(JOB_ID, "alice")
        self.assertNotIn("secret", str(self.logs))
        self.access.download_link.side_effect = KeyError("not_found")
        self.assertEqual(self.post(f"/api/jobs/{JOB_ID}/download-link", {}).status_code, 404)

    def test_operator_cannot_create_customer_job_and_errors_are_sanitized(self):
        self.login("operator")
        self.assertEqual(self.post("/api/jobs", {"display_name": "sales.csv"},
                                  **{"Idempotency-Key": "some-key-123"}).status_code, 403)
        self.jobs.read_owned.side_effect = RuntimeError("token=never-log-this")
        result = self.get("/api/jobs/"+JOB_ID)
        self.assertEqual(result.status_code, 503)
        self.assertNotIn("never-log-this", result.get_data(as_text=True))
        self.assertNotIn("never-log-this", str(self.logs))



    def test_list_uses_session_owner_bounded_page_and_public_fields(self):
        self.login("bob")
        job = new_job(JOB_ID, "bob", NOW)
        job["attempt_token"] = "must-not-leak"
        self.jobs.list_owned.return_value = {"jobs": [job], "next_cursor": JOB_ID}
        response = self.get("/api/jobs?limit=2")
        self.assertEqual(response.status_code, 200)
        self.jobs.list_owned.assert_called_once_with("bob", limit=2, cursor=None)
        self.assertEqual(response.json["next_cursor"], JOB_ID)
        self.assertNotIn("attempt_token", response.json["jobs"][0])
        for query in ("owner=alice", "limit=21", "limit=0", "limit=2&limit=3"):
            self.assertEqual(self.get("/api/jobs?"+query).status_code, 400)



    def test_operator_routes_deny_customer_and_project_only_safe_metadata(self):
        self.login("alice")
        self.assertEqual(self.get("/api/operator/jobs").status_code, 403)
        self.assertEqual(self.get("/api/operator/jobs/"+JOB_ID).status_code, 403)
        self.jobs.list_operator.assert_not_called()
        self.jobs.read_operator.assert_not_called()
        self.post("/api/logout", {})
        self.csrf = self.get("/api/session").json["csrf"]
        self.login("operator")
        item = new_job(JOB_ID, "alice", NOW)
        item["history"] = [{"time": NOW, "state": "failed", "epoch": 0,
                            "attempt": 5, "reason": "retry_budget"}]
        item["output_name"] = "never-expose-object-path"
        self.jobs.list_operator.return_value = {"jobs": [item], "next_cursor": None}
        self.jobs.read_operator.return_value = item
        result = self.get("/api/operator/jobs")
        self.assertEqual(result.status_code, 200)
        detail = self.get("/api/operator/jobs/"+JOB_ID)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json["history"][0]["reason"], "retry_budget")
        self.assertNotIn("never-expose", detail.get_data(as_text=True))
        self.access.download_link.assert_not_called()



    def test_operator_retry_is_durable_before_dispatch_and_timeout_is_unconfirmed(self):
        dispatch = Mock(side_effect=TimeoutError("no business outcome known"))
        self.app = create_app(self.jobs, self.access, self.auth, clock=lambda: NOW,
                              retry_dispatch=dispatch, emit=self.logs.append)
        self.client = self.app.test_client()
        self.csrf = self.get("/api/session").json["csrf"]
        self.login("alice")
        url = f"/api/operator/jobs/{JOB_ID}/retry"
        self.assertEqual(self.post(url, {"request_key": "retry-request-1"}).status_code, 403)
        self.jobs.prepare_operator_retry.assert_not_called()
        self.post("/api/logout", {})
        self.csrf = self.get("/api/session").json["csrf"]
        self.login("operator")
        self.jobs.prepare_operator_retry.return_value = {"epoch": 1, "replayed": False}
        response = self.post(url, {"request_key": "retry-request-1"})
        self.assertEqual((response.status_code, response.json["dispatch"]),
                         (202, "unconfirmed"))
        self.jobs.prepare_operator_retry.assert_called_once_with(
            JOB_ID, "operator", "retry-request-1")
        dispatch.assert_called_once_with(JOB_ID, 1)
        self.jobs.prepare_operator_retry.return_value = {"epoch": 1, "replayed": True}
        dispatch.side_effect = None
        dispatch.return_value = True
        replay = self.post(url, {"request_key": "retry-request-1"})
        self.assertEqual((replay.json["epoch"], replay.json["replayed"],
                          replay.json["dispatch"]), (1, True, "acknowledged"))


if __name__ == "__main__":
    unittest.main()
