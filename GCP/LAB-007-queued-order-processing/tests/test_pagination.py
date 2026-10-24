import base64
from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import unittest

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from order_domain import Rejected,canonical
from pagination import encode_cursor,decode_cursor,page_limit,page

ID="a"*32


class CursorTests(unittest.TestCase):
    def test_timezone_normalizes_and_roundtrips_exact_microseconds(self):
        instant=datetime(2026,10,24,10,11,12,123456,tzinfo=timezone(timedelta(hours=7)))
        cursor=encode_cursor(instant,ID)
        self.assertLess(len(cursor),256)
        self.assertEqual(decode_cursor(cursor),(instant.astimezone(timezone.utc),ID))
        self.assertIsNone(decode_cursor(None))
        with self.assertRaises(ValueError):
            encode_cursor(instant.replace(tzinfo=None),ID)

    def test_invalid_cursor_bounds_encoding_schema_and_date(self):
        for value in ["", "x"*257,"!",True,1]:
            with self.assertRaises(Rejected):
                decode_cursor(value)
        for value in [
                {"v":True,"id":ID,"created_at":"2026-10-24T00:00:00Z"},
                {"v":1,"id":ID,"created_at":"2026-99-24T00:00:00Z"},
                {"v":1,"id":"bad","created_at":"2026-10-24T00:00:00Z"},
                {"v":1,"id":ID,"created_at":"2026-10-24T00:00:00+07:00"},
                {"v":1,"id":ID,"created_at":"2026-10-24T00:00:00Z","owner":"bob"}]:
            encoded=base64.urlsafe_b64encode(canonical(value)).decode().rstrip("=")
            with self.assertRaises(Rejected):
                decode_cursor(encoded)

    def test_page_limit_and_extra_row_do_not_skip_visible_items(self):
        for value in [0,21,True,1.0,"2",None]:
            with self.assertRaises(Rejected):
                page_limit(value)
        rows=[{"order_id":str(i)*32,"created_at":datetime(2026,10,24,tzinfo=timezone.utc)}
              for i in range(1,4)]
        result=page(rows,2,"order_id")
        self.assertEqual(result["items"],rows[:2])
        self.assertEqual(decode_cursor(result["next_cursor"])[1],rows[1]["order_id"])
        self.assertIsNone(page(rows[:2],2,"order_id")["next_cursor"])


if __name__=="__main__":
    unittest.main()
