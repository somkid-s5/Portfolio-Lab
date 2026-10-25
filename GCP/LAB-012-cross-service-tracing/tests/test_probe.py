"""Bounds and report tests for the HTTPS probe without contacting GCP."""
import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from checkout_probe import parse_args


class ProbeTests(unittest.TestCase):
    def arguments(self, *extra):
        return ["--host", "checkout.lab.local", "--ip", "203.0.113.10", "--ca", "/tmp/lab.crt", *extra]

    def test_default_probe_is_bounded(self):
        with patch("sys.argv", ["checkout_probe.py", *self.arguments()]):
            args = parse_args()
        self.assertEqual(args.requests, 12)
        self.assertEqual(args.workers, 2)

    def test_request_limit_cannot_exceed_60(self):
        with patch("sys.argv", ["checkout_probe.py", *self.arguments("--requests", "61")]):
            with self.assertRaises(SystemExit):
                parse_args()

    def test_worker_and_timeout_limits_are_enforced(self):
        for extra in (
            ("--workers", "5"),
            ("--requests", "2", "--workers", "3"),
            ("--timeout", "11"),
            ("--ip", "not-an-ip"),
        ):
            with patch("sys.argv", ["checkout_probe.py", *self.arguments(*extra)]):
                with self.assertRaises(SystemExit):
                    parse_args()


if __name__ == "__main__":
    unittest.main()
