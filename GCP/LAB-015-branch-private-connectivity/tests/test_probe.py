from __future__ import annotations

import unittest

from scripts import probe


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.body


class ProbeHelperTests(unittest.TestCase):
    def test_authenticated_request_uses_serverless_header(self):
        request = probe.build_request("http://inventory.lab.internal/v1/items", "jwt.value")
        self.assertEqual(request.get_header("X-serverless-authorization"), "Bearer jwt.value")
        self.assertIsNone(request.get_header("Authorization"))

    def test_unauthenticated_request_has_no_auth_header(self):
        request = probe.build_request("http://inventory.lab.internal/healthz", None)
        self.assertIsNone(request.get_header("X-serverless-authorization"))

    def test_metadata_token_request_sets_required_header_and_audience(self):
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["header"] = request.get_header("Metadata-flavor")
            captured["timeout"] = timeout
            return FakeResponse(b"header.payload.signature")

        token = probe.get_id_token("https://service.example", opener=opener)
        self.assertEqual(token, "header.payload.signature")
        self.assertIn("audience=https%3A%2F%2Fservice.example", captured["url"])
        self.assertEqual(captured["header"], "Google")
        self.assertEqual(captured["timeout"], 5)


if __name__ == "__main__":
    unittest.main()
