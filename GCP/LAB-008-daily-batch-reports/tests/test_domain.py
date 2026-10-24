"""Pure contracts for Daily Sales Close; no Cloud APIs or credentials."""
from pathlib import Path
import json
import unittest

from app.domain import COLUMNS, MAX_DATA_ROWS, MAX_INPUT_BYTES, InputError, build_report
from app.schedule import ScheduleRequestError, logical_business_date, scheduler_business_date

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / "fixtures" / "transactions.csv").read_bytes()
DATE = "2026-10-23"
JOB = "projects/lab-project/locations/asia-southeast1/jobs/daily-report"


def csv_bytes(rows, header=",".join(COLUMNS)):
    return (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")


def row(tx="TX-1", sold="2026-10-23T09:00:00+07:00", sku="A-1",
        qty="1", price="100", currency="THB"):
    return ",".join((tx, sold, sku, qty, price, currency))


class DomainTests(unittest.TestCase):
    def test_fixture_reconciles_expected_totals_and_sku_order(self):
        report = build_report(FIXTURE, business_date=DATE, source_generation="1700000000000000")
        data = json.loads(report.canonical_json)
        self.assertEqual((data["row_count"], data["total_quantity"],
                          data["total_amount_minor"]), (4, 7, 79000))
        self.assertEqual([item["sku"] for item in data["by_sku"]],
                         ["COFFEE-01", "MEAL-01", "TEA-02"])

    def test_identical_pinned_bytes_are_canonical_and_stable(self):
        args = {"business_date": DATE, "source_generation": "1700000000000000"}
        first = build_report(FIXTURE, **args)
        self.assertEqual(first, build_report(FIXTURE, **args))
        self.assertTrue(first.canonical_json.endswith(b"\n"))

    def test_source_generation_is_part_of_report_identity(self):
        first = build_report(FIXTURE, business_date=DATE, source_generation="1")
        second = build_report(FIXTURE, business_date=DATE, source_generation="2")
        self.assertNotEqual(first.report_id, second.report_id)

    def test_business_date_uses_bangkok_local_calendar_day(self):
        utc = csv_bytes([row(sold="2026-10-23T17:00:00Z")])
        self.assertEqual(build_report(utc, business_date="2026-10-24",
                                      source_generation="1").business_date, "2026-10-24")
        with self.assertRaisesRegex(InputError, "BUSINESS_DATE_MISMATCH"):
            build_report(utc, business_date=DATE, source_generation="1")

    def test_rejects_timezone_naive_timestamp(self):
        with self.assertRaisesRegex(InputError, "TIMEZONE_REQUIRED"):
            build_report(csv_bytes([row(sold="2026-10-23T09:00:00")]),
                         business_date=DATE, source_generation="1")

    def test_requires_exact_header_and_column_order(self):
        with self.assertRaisesRegex(InputError, "INVALID_HEADER"):
            build_report(csv_bytes([row()], header="sku,transaction_id,sold_at,quantity,unit_price_minor,currency"),
                         business_date=DATE, source_generation="1")

    def test_rejects_extra_or_missing_cells(self):
        with self.assertRaisesRegex(InputError, "INVALID_ROW_SHAPE"):
            build_report(csv_bytes([row() + ",unexpected"]), business_date=DATE,
                         source_generation="1")
        with self.assertRaisesRegex(InputError, "INVALID_ROW_SHAPE"):
            build_report(csv_bytes([row().rsplit(",", 1)[0]]), business_date=DATE,
                         source_generation="1")

    def test_rejects_duplicate_transaction_ids(self):
        with self.assertRaisesRegex(InputError, "DUPLICATE_TRANSACTION_ID"):
            build_report(csv_bytes([row(), row(sku="B-1")]), business_date=DATE,
                         source_generation="1")

    def test_rejects_bad_sku_id_currency_and_integer_fields(self):
        cases = [(row(currency="USD"), "UNSUPPORTED_CURRENCY"),
                 (row(sku="lowercase"), "INVALID_SKU"),
                 (row(tx="contains space"), "INVALID_TRANSACTION_ID"),
                 (row(qty="1.5"), "INVALID_QUANTITY"),
                 (row(qty="0"), "INVALID_QUANTITY"),
                 (row(price="-1"), "INVALID_UNIT_PRICE")]
        for item, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(InputError, code):
                build_report(csv_bytes([item]), business_date=DATE, source_generation="1")

    def test_rejects_non_utf8_and_malformed_csv(self):
        with self.assertRaisesRegex(InputError, "INVALID_UTF8"):
            build_report(b"\xff", business_date=DATE, source_generation="1")
        malformed = b'transaction_id,sold_at,sku,quantity,unit_price_minor,currency\n"unterminated'
        with self.assertRaisesRegex(InputError, "MALFORMED_CSV"):
            build_report(malformed, business_date=DATE, source_generation="1")

    def test_rejects_empty_report_bad_date_and_bad_generation(self):
        with self.assertRaisesRegex(InputError, "EMPTY_REPORT"):
            build_report((",".join(COLUMNS) + "\n").encode(), business_date=DATE,
                         source_generation="1")
        for generation in ("0", "-1", "not-a-generation"):
            with self.subTest(generation=generation), self.assertRaisesRegex(
                    InputError, "INVALID_SOURCE_GENERATION"):
                build_report(csv_bytes([row()]), business_date=DATE,
                             source_generation=generation)
        with self.assertRaisesRegex(InputError, "INVALID_BUSINESS_DATE"):
            build_report(csv_bytes([row()]), business_date="2026-2-3",
                         source_generation="1")

    def test_enforces_byte_and_row_limits(self):
        with self.assertRaisesRegex(InputError, "INPUT_TOO_LARGE"):
            build_report(b"x" * (MAX_INPUT_BYTES + 1), business_date=DATE,
                         source_generation="1")
        rows = [row(tx=f"TX-{n}") for n in range(MAX_DATA_ROWS + 1)]
        with self.assertRaisesRegex(InputError, "TOO_MANY_ROWS"):
            build_report(csv_bytes(rows), business_date=DATE, source_generation="1")


class ScheduleContractTests(unittest.TestCase):
    def test_schedule_time_becomes_previous_local_business_date(self):
        self.assertEqual(logical_business_date("2026-10-24T01:15:00+07:00"), DATE)
        self.assertEqual(logical_business_date("2026-10-23T18:15:00Z"), DATE)
        self.assertEqual(logical_business_date("2026-01-01T01:15:00+07:00"), "2025-12-31")

    def test_rejects_bad_or_timezone_naive_schedule_time(self):
        for value in ("", "2026-10-24T01:15:00", "not-time", "2026-02-30T01:15:00Z"):
            with self.subTest(value=value), self.assertRaises(ScheduleRequestError):
                logical_business_date(value)

    def test_scheduler_headers_are_case_insensitive_and_job_must_match(self):
        headers = {"X-CloudScheduler": "true", "X-CloudScheduler-JobName": JOB,
                   "X-CloudScheduler-ScheduleTime": "2026-10-24T01:15:00+07:00"}
        self.assertEqual(scheduler_business_date(headers, expected_job_name=JOB), DATE)
        bad = dict(headers)
        bad["x-cloudscheduler-jobname"] = "other"
        with self.assertRaisesRegex(ScheduleRequestError, "UNEXPECTED_SCHEDULER_JOB"):
            scheduler_business_date(bad, expected_job_name=JOB)

    def test_rejects_missing_scheduler_marker_and_schedule_time(self):
        headers = {"X-CloudScheduler": "false", "X-CloudScheduler-JobName": JOB,
                   "X-CloudScheduler-ScheduleTime": "2026-10-24T01:15:00+07:00"}
        with self.assertRaisesRegex(ScheduleRequestError, "NOT_SCHEDULER_REQUEST"):
            scheduler_business_date(headers, expected_job_name=JOB)
        headers["X-CloudScheduler"] = "true"
        headers.pop("X-CloudScheduler-ScheduleTime")
        with self.assertRaisesRegex(ScheduleRequestError, "MISSING_SCHEDULE_TIME"):
            scheduler_business_date(headers, expected_job_name=JOB)


if __name__ == "__main__":
    unittest.main()
