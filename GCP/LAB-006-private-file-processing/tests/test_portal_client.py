import contextlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
import sys
import tempfile
import threading
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"scripts"))
from portal_client import Client, origin, read_logins


class Handler(BaseHTTPRequestHandler):
    calls = []
    def log_message(self, *args):
        pass
    def send_json(self, value, status=200, cookie=False):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", "session=ci-cookie; HttpOnly; Path=/")
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        type(self).calls.append(self.path)
        if self.path == "/api/session":
            self.send_json({"csrf": "anonymous-csrf"}, cookie=True)
        elif self.path == "/api/redirect":
            self.send_response(302)
            self.send_header("Location", "/api/should-not-be-called")
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
        elif self.path == "/api/huge":
            self.send_json({"payload": "x"*65537})
        else:
            self.send_json({})
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/login":
            valid = (data == {"username": "alice", "password": "private-demo"} and
                     self.headers.get("X-CSRF-Token") == "anonymous-csrf" and
                     "ci-cookie" in self.headers.get("Cookie", ""))
            self.send_json({"user": "alice", "csrf": "rotated-csrf"} if valid else {},
                           200 if valid else 403)
        else:
            self.send_json({"csrf_seen": self.headers.get("X-CSRF-Token")})


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_real_http_login_cookie_and_csrf_rotation_without_stdout(self):
        client = Client(self.url, loopback_test=True)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            client.login("alice", "private-demo")
            status, value = client.call("/api/jobs", data={}, key="request-key-123")
        self.assertEqual((status, value["csrf_seen"]), (200, "rotated-csrf"))
        self.assertEqual(client.calls, 3)
        self.assertEqual(output.getvalue(), "")

    def test_origin_redirect_response_size_and_request_budget(self):
        for url in (self.url, "https://user:password@example.com",
                    "https://example.com/path", "https://example.com/?secret=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                origin(url)
        with self.assertRaises(ValueError):
            origin("http://example.com", loopback_test=True)
        self.assertEqual(origin("https://portal.run.app/"), "https://portal.run.app")
        client = Client(self.url, loopback_test=True)
        Handler.calls.clear()
        self.assertEqual(client.call("/api/redirect")[0], 302)
        self.assertNotIn("/api/should-not-be-called", Handler.calls)
        with self.assertRaises(ValueError):
            client.call("/api/huge")
        client.calls = 30
        with self.assertRaises(ValueError):
            client.call("/api/jobs")
        with self.assertRaises(ValueError):
            client.call("//other.invalid/api/jobs")

    def test_private_file_permissions_symlink_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"logins.json"
            path.write_text('{"alice":{"password":"private-demo"}}')
            os.chmod(path, 0o600)
            self.assertEqual(read_logins(path)["alice"]["password"], "private-demo")
            os.chmod(path, 0o644)
            with self.assertRaises(ValueError):
                read_logins(path)
            os.chmod(path, 0o600)
            alias = Path(folder)/"alias"
            alias.symlink_to(path)
            with self.assertRaises(ValueError):
                read_logins(alias)
            path.write_bytes(b"x"*65537)
            with self.assertRaises(ValueError):
                read_logins(path)


if __name__ == "__main__":
    unittest.main()
