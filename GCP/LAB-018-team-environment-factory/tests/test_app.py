from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "main.py"


class StatusAppTests(unittest.TestCase):
    def setUp(self):
        self.port = self._free_port()
        env = os.environ.copy()
        env.update(PORT=str(self.port), ENVIRONMENT="test", APP_VERSION="ci")
        self.process = subprocess.Popen(
            [sys.executable, str(APP)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(50):
            try:
                urllib.request.urlopen(self.base + "/healthz", timeout=0.2).close()
                break
            except (urllib.error.URLError, TimeoutError):
                if self.process.poll() is not None:
                    self.fail("Status API exited before it became ready")
                time.sleep(0.05)
        else:
            self.fail("Status API did not become ready")

    @staticmethod
    def _free_port():
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def tearDown(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        if self.process.stdout:
            self.process.stdout.close()
        if self.process.stderr:
            self.process.stderr.close()

    def test_health_endpoint_returns_environment_and_status(self):
        with urllib.request.urlopen(self.base + "/healthz", timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(body["environment"], "test")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], "ci")

    def test_root_endpoint_is_a_small_status_summary(self):
        with urllib.request.urlopen(self.base + "/", timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
        self.assertEqual(response.status, 200)
        self.assertEqual(body["service"], "lab18-status-api")

    def test_unknown_route_is_not_found(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.base + "/not-a-route", timeout=2)
        self.assertEqual(raised.exception.code, 404)

    def test_unknown_route_log_does_not_echo_path_or_client_details(self):
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.base + "/not-a-route", timeout=2)
        self.assertEqual(raised.exception.code, 404)
        self.process.terminate()
        output, _ = self.process.communicate(timeout=3)
        self.assertNotIn("not-a-route", output)
        self.assertNotIn("127.0.0.1", output)
        json_lines = [line for line in output.splitlines() if line.startswith("{")]
        self.assertTrue(json_lines)
        event = json.loads(json_lines[-1])
        self.assertEqual(event["route"], "other")
        self.assertEqual(event["status_code"], 404)


if __name__ == "__main__":
    unittest.main()
