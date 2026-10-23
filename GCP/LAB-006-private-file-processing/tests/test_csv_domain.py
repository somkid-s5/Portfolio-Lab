import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "app"))
from csv_domain import Rejected, bounded_read, canonical_bytes, summarize

HEADER = b"sale_id,sku,quantity,unit_price_satang\n"
GOOD = HEADER + b"S001,BOOK-01,2,12500\nS002,USB-01,1,9900\nS003,BOOK-01,3,12500\n"


class DomainTests(unittest.TestCase):
    def reject(self, data, code, **kwargs):
        with self.assertRaises(Rejected) as caught:
            summarize(data, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def test_fixture_exact_business_totals_and_original_hash(self):
        data = (LAB / "fixtures/valid-sales.csv").read_bytes()
        result = summarize(data)
        expected = json.loads((LAB / "fixtures/valid-sales.expected.json").read_text())
        self.assertEqual({k: v for k, v in result.items() if k != "input_sha256"},
                         expected)
        self.assertEqual(result["input_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(canonical_bytes(result), canonical_bytes(summarize(data)))

    def test_bom_crlf_and_quoted_fields_are_explicitly_supported(self):
        data = b"\xef\xbb\xbf" + HEADER.replace(b"\n", b"\r\n") + b'"S1","BOOK-01",1,0\r\n'
        result = summarize(data)
        self.assertEqual((result["rows"], result["total_satang"]), (1, 0))
        self.assertEqual(result["input_sha256"], hashlib.sha256(data).hexdigest())

    def test_size_and_row_boundaries(self):
        self.assertEqual(summarize(GOOD, max_bytes=len(GOOD), max_rows=3)["rows"], 3)
        self.reject(GOOD, "file_too_large", max_bytes=len(GOOD) - 1)
        self.reject(GOOD, "too_many_rows", max_rows=2)
        self.reject(HEADER, "no_data_rows")
        self.reject(b"", "empty_file")

    def test_headers_columns_encoding_nulls_and_blank_lines(self):
        for data, code in [
            (b"sku,sale_id,quantity,unit_price_satang\n", "invalid_header"),
            (HEADER + b"S1,BOOK-01,1,0,extra\n", "invalid_columns"),
            (HEADER + b"\xff", "invalid_utf8"),
            (HEADER + b"S1,BOOK-01,1,\x00\n", "null_byte"),
            (HEADER + b"\n", "invalid_columns"),
            (HEADER + b'"S1\nS2",BOOK-01,1,0\n', "multiline_record"),
            (HEADER + b'"S1,BOOK-01,1,0\n', "malformed_csv"),
        ]:
            with self.subTest(code=code):
                self.reject(data, code)

    def test_duplicate_ids_and_identifier_allowlists(self):
        self.reject((LAB / "fixtures/duplicate-sale-id.csv").read_bytes(),
                    "duplicate_sale_id")
        for sale, sku, code in [
            ("=FORMULA", "BOOK-01", "invalid_sale_id"),
            ("S1", "<script>", "invalid_sku"),
            ("S1", "lower", "invalid_sku"),
            ("S1", "A" * 129, "field_too_long"),
        ]:
            with self.subTest(sale=sale, sku=sku):
                self.reject(HEADER + f"{sale},{sku},1,0\n".encode(), code)

    def test_numbers_never_accept_float_sign_whitespace_or_exponents(self):
        for quantity, price, code in [
            ("0", "1", "integer_out_of_range"),
            ("1000001", "1", "integer_out_of_range"),
            ("1", "100000001", "integer_out_of_range"),
            ("-1", "1", "invalid_integer"),
            ("1.5", "1", "invalid_integer"),
            ("1", "NaN", "invalid_integer"),
            ("1e3", "1", "invalid_integer"),
            (" 1", "1", "invalid_integer"),
            ("01", "1", "invalid_integer"),
            ("True", "1", "invalid_integer"),
        ]:
            with self.subTest(quantity=quantity, price=price):
                self.reject(HEADER + f"S1,BOOK-01,{quantity},{price}\n".encode(), code)

    def test_change_contract_handles_larger_fixture_but_baseline_rejects(self):
        data = HEADER + b"".join(f"S{i},BOOK-01,1,100\n".encode()
                                 for i in range(10001))
        self.reject(data, "too_many_rows")
        result = summarize(data, max_bytes=5242880, max_rows=50000)
        self.assertEqual((result["rows"], result["total_satang"]), (10001, 1000100))
        big = HEADER + b"".join(f"S{i},BOOK-01,1000000,100000000\n".encode()
                                for i in range(40000))
        self.reject(big, "file_too_large")
        self.assertEqual(summarize(big, max_bytes=5242880, max_rows=50000)
                         ["total_satang"], 4000000000000000000)

    def test_bounded_stream_never_reads_past_limit_plus_one(self):
        class Counting(io.BytesIO):
            consumed = 0
            def read(self, size=-1):
                self.assertion = size
                if size < 0:
                    raise AssertionError("unbounded read")
                chunk = super().read(size)
                self.consumed += len(chunk)
                return chunk
        exact = Counting(GOOD)
        self.assertEqual(bounded_read(exact, len(GOOD)), GOOD)
        oversized = Counting(b"x" * 10000)
        with self.assertRaises(Rejected):
            bounded_read(oversized, 100)
        self.assertEqual(oversized.consumed, 101)

    def test_invalid_configuration_and_input_types_fail_closed(self):
        for args in [{"max_bytes": True}, {"max_rows": 0},
                     {"max_rows": 50001}, {"max_bytes": 5242881},
                     {"processor_version": "../v1"}]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                summarize(GOOD, **args)
        with self.assertRaises(TypeError):
            summarize("not bytes")
        with self.assertRaises(TypeError):
            bounded_read(io.StringIO("not binary"), 100)

    def test_output_is_canonical_sorted_and_has_no_runtime_fields(self):
        result = summarize(GOOD, processor_version="v2")
        self.assertEqual([g["sku"] for g in result["by_sku"]], ["BOOK-01", "USB-01"])
        self.assertEqual(set(result), {"schema_version", "processor_version",
                                     "input_sha256", "rows", "units",
                                     "total_satang", "by_sku"})
        self.assertEqual(json.loads(canonical_bytes(result)), result)


if __name__ == "__main__":
    unittest.main()
