"""Shared container entrypoint stays within the four fixed service roles."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.entrypoint import SERVICE_MODULES, build_command


class EntrypointTests(unittest.TestCase):
    def test_each_role_maps_only_to_its_fixed_wsgi_module(self):
        for role, module in SERVICE_MODULES.items():
            with self.subTest(role=role):
                command = build_command(role)
                self.assertEqual(command[-1], module)
                self.assertIn("0.0.0.0:8080", command)
                self.assertEqual(command[command.index("--workers") + 1], "1")

    def test_port_is_checked_and_never_used_as_shell_text(self):
        self.assertIn("0.0.0.0:9090", build_command("worker", 9090))
        for invalid in ("0", "65536", "8080;id", "-1", True):
            with self.subTest(port=invalid):
                with self.assertRaises(ValueError):
                    build_command("worker", invalid)

    def test_arbitrary_module_or_role_cannot_be_selected(self):
        for invalid in ("", "app.anything:app", "worker;sh"):
            with self.subTest(role=invalid):
                with self.assertRaises(ValueError):
                    build_command(invalid)


if __name__ == "__main__":
    unittest.main()
