"""Secret version reader contract tests use a client double only."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from google.api_core.exceptions import FailedPrecondition, NotFound, PermissionDenied

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.secret_manager import SecretConfigurationError, SecretVersionReader


NAME = "projects/demo-lab009/secrets/partner-a-hmac/versions/1"


class FakeSecretClient:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def access_secret_version(self, *, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return SimpleNamespace(payload=SimpleNamespace(data=b"x" * 32))


class SecretManagerTests(unittest.TestCase):
    def test_reads_only_pinned_version_with_explicit_timeout(self):
        client = FakeSecretClient()
        self.assertEqual(SecretVersionReader(client)(NAME), b"x" * 32)
        self.assertEqual(client.calls, [({"name": NAME}, 5.0)])

    def test_missing_disabled_or_forbidden_version_is_configuration_failure(self):
        for error in (NotFound("missing"), PermissionDenied("denied"), FailedPrecondition("disabled")):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(SecretConfigurationError):
                    SecretVersionReader(FakeSecretClient(error))(NAME)

    def test_invalid_or_unpinned_secret_resource_is_rejected_before_rpc(self):
        client = FakeSecretClient()
        with self.assertRaises(ValueError):
            SecretVersionReader(client)("projects/demo-lab009/secrets/key/versions/latest")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
