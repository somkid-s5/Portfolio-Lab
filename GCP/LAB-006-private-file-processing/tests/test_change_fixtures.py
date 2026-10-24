import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"app"))
from csv_domain import Rejected, summarize
spec = importlib.util.spec_from_file_location("change_files", LAB/"scripts/create-change-fixtures.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ChangeTests(unittest.TestCase):
    def test_exact_boundary_csv_is_valid_and_deterministic(self):
        one = generator.exact_csv(1048576, 10000)
        self.assertEqual(len(one), 1048576)
        self.assertEqual(one, generator.exact_csv(1048576, 10000))
        result = summarize(one)
        self.assertEqual((result["rows"], result["units"], result["total_satang"]),
                         (10000, 10000, 1000000000000))
        five = generator.exact_csv(5242880, 50000)
        self.assertEqual(len(five), 5242880)
        self.assertEqual(summarize(five, max_bytes=5242880, max_rows=50000)["rows"], 50000)
        with self.assertRaises(Rejected):
            summarize(five)

    def test_generated_cases_isolate_byte_and_row_contracts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"fixtures"
            manifest = generator.generate(path)
            byte_change = (path/"byte-change.csv").read_bytes()
            row_change = (path/"row-change.csv").read_bytes()
            self.assertGreater(len(byte_change), 1048576)
            self.assertLess(len(row_change), 1048576)
            for data, code in [(byte_change,"file_too_large"), (row_change,"too_many_rows")]:
                with self.assertRaises(Rejected) as error:
                    summarize(data)
                self.assertEqual(error.exception.code, code)
                summarize(data, max_bytes=5242880, max_rows=50000)
            with self.assertRaises(Rejected) as error:
                summarize((path/"too-many-rows.csv").read_bytes(),
                          max_bytes=5242880,max_rows=50000)
            self.assertEqual(error.exception.code,"too_many_rows")
            self.assertEqual(manifest["too-large.csv"]["bytes"],5242881)
            with self.assertRaises(FileExistsError):
                generator.generate(path)

    def test_validation_only_is_small_invalid_utf8_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"validation"
            manifest = generator.generate(path, validation_only=True)
            self.assertEqual(set(manifest), {"invalid-utf8.csv"})
            self.assertLess(manifest["invalid-utf8.csv"]["bytes"], 1024)
            with self.assertRaises(Rejected) as error:
                summarize((path/"invalid-utf8.csv").read_bytes())
            self.assertEqual(error.exception.code, "invalid_utf8")
            with self.assertRaises(FileExistsError):
                generator.generate(path, validation_only=True)

    def test_invalid_target_sizes_and_row_counts_are_refused(self):
        for size, rows in [(1,1), (99999999,2), (10000,50001), (1000,True)]:
            with self.subTest(size=size,rows=rows), self.assertRaises(ValueError):
                generator.exact_csv(size, rows)


if __name__ == "__main__":
    unittest.main()
