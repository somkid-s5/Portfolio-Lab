"""Offline checks for the safe, deterministic synthetic CSV generator."""
import csv
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "scripts"))
from generate_input import COLUMNS, generate_input


class GenerateInputTests(unittest.TestCase):
    def test_generated_file_is_schema_valid_deterministic_and_source_date_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "transactions.csv"
            first_path, first_digest = generate_input("2026-10-23", path)
            first_bytes = first_path.read_bytes()
            self.assertEqual(first_digest, hashlib.sha256(first_bytes).hexdigest())
            with first_path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(tuple(reader.fieldnames or ()), COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(row["sold_at"].startswith("2026-10-23T09:00:00+07:00")
                                for row in rows))
            self.assertEqual(sum(int(row["quantity"]) for row in rows), 4)
            self.assertEqual(sum(int(row["quantity"]) * int(row["unit_price_minor"])
                                 for row in rows), 79_000)
            with self.assertRaises(FileExistsError):
                generate_input("2026-10-23", path)
            self.assertEqual(path.read_bytes(), first_bytes)

    def test_noncanonical_or_impossible_date_is_rejected_without_output(self):
        for value in ("2026-2-03", "2026-02-30", "tomorrow"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "transactions.csv"
                with self.assertRaises(ValueError):
                    generate_input(value, path)
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
