from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT
PATCH = LAB / "change-requests" / "CR-20-01-booking-source.patch"


class ChangeRequestPatchTests(unittest.TestCase):
    def test_change_request_patch_applies_and_regression_suite_passes(self):
        with tempfile.TemporaryDirectory(prefix="lab020-cr-") as temp:
            target = Path(temp) / "lab"
            target.mkdir()
            for name in ("app", "tests"):
                shutil.copytree(LAB / name, target / name)
            result = subprocess.run(
                ["git", "apply", str(PATCH)],
                cwd=target,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            environment = os.environ.copy()
            environment["DATABASE_URL"] = "sqlite+pysqlite:///" + str(target / "global.db")
            environment["APP_LOCAL_TEST"] = "1"
            environment.pop("TEST_DATABASE_URL", None)
            tested = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_app.py", "-v"],
                cwd=target,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)


if __name__ == "__main__":
    unittest.main()
