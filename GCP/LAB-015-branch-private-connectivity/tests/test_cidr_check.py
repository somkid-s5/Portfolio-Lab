from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cidr_check.py"


class CidrPreflightTests(unittest.TestCase):
    def run_check(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=False)

    def test_default_and_approved_change_prefix_pass(self):
        self.assertEqual(self.run_check().returncode, 0)
        self.assertEqual(self.run_check("--additional", "10.70.1.0/24").returncode, 0)

    def test_overlapping_prefix_is_rejected_before_apply(self):
        result = self.run_check("--additional", "10.60.0.128/25")
        self.assertEqual(result.returncode, 2)
        self.assertIn("CONFLICT:", result.stderr)
        self.assertIn("overlaps", result.stderr)
        self.assertIn("hub", result.stderr)

    def test_noncanonical_and_ipv6_prefixes_are_rejected(self):
        self.assertEqual(self.run_check("--additional", "10.70.1.1/24").returncode, 2)
        self.assertEqual(self.run_check("--additional", "2001:db8::/64").returncode, 2)


if __name__ == "__main__":
    unittest.main()
