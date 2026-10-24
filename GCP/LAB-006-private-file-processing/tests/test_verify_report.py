import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"app"))
from csv_domain import summarize
spec = importlib.util.spec_from_file_location("verify_report", LAB/"scripts/verify-report.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class ReportTests(unittest.TestCase):
    def test_exact_business_report_and_source_hash(self):
        source = LAB/"fixtures/valid-sales.csv"
        report = summarize(source.read_bytes())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.json"
            path.write_text(json.dumps(report))
            result = verifier.verify(source, path)
        self.assertEqual((result["rows"], result["units"], result["total_satang"]),
                         (3, 6, 72400))

    def test_wrong_total_source_hash_and_extra_fields_are_not_accepted(self):
        source = LAB/"fixtures/valid-sales.csv"
        original = summarize(source.read_bytes())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.json"
            for key, value in [("total_satang", 1), ("input_sha256", "a"*64),
                               ("unexpected", True)]:
                report = dict(original)
                report[key] = value
                path.write_text(json.dumps(report))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    verifier.verify(source, path)

    def test_duplicate_keys_nan_and_oversized_report_fail_closed(self):
        source = LAB/"fixtures/valid-sales.csv"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"report.json"
            for body in (b'{"rows":1,"rows":2}', b'{"rows":NaN}', b"x"*8388609):
                path.write_bytes(body)
                with self.assertRaises(ValueError):
                    verifier.verify(source, path)


if __name__ == "__main__":
    unittest.main()
