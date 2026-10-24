import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from storage_events import InvalidEvent, parse_event

BUCKET = "lab006-test-incoming"
NAME = "incoming/" + "a"*32 + "/source.csv"


class EventTests(unittest.TestCase):
    def setUp(self):
        self.headers = {"ce-specversion": "1.0",
                        "ce-type": "google.cloud.storage.object.v1.finalized",
                        "ce-id": "event-123",
                        "ce-source": f"//storage.googleapis.com/projects/_/buckets/{BUCKET}",
                        "ce-subject": f"objects/{NAME}",
                        "content-type": "application/json; charset=utf-8"}
        self.data = {"bucket": BUCKET, "name": NAME, "generation": "123",
                     "timeCreated": "2026-01-01T00:00:00.123456789Z",
                     "mediaLink": "https://untrusted.invalid/never-follow"}

    def parse(self):
        return parse_event(self.headers, json.dumps(self.data).encode(), BUCKET)

    def test_binary_event_is_bound_to_job_and_original_generation(self):
        event = self.parse()
        self.assertEqual((event.job_id, event.generation), ("a"*32, "123"))
        self.assertEqual(event.finalized_at.utcoffset().total_seconds(), 0)
        self.assertEqual(event.finalized_at.microsecond, 123456)

    def test_wrong_bucket_source_or_object_namespace_are_ignored(self):
        for field, value in [("bucket", "other-bucket"), ("name", "../secret"),
                             ("name", "results/a/summary.json")]:
            old = dict(self.data)
            self.data[field] = value
            with self.subTest(field=field):
                self.assertIsNone(self.parse())
            self.data = old
        self.headers["ce-source"] = "//untrusted"
        self.assertIsNone(self.parse())

    def test_invalid_generation_subject_and_timestamp_are_not_processed(self):
        for field, value in [("generation", 123), ("generation", "0"),
                             ("timeCreated", "2026-01-01"),
                             ("timeCreated", "2026-13-01T00:00:00Z")]:
            old = dict(self.data)
            self.data[field] = value
            with self.subTest(field=field), self.assertRaises(InvalidEvent):
                self.parse()
            self.data = old
        self.headers["ce-subject"] = "objects/something-else"
        with self.assertRaises(InvalidEvent):
            self.parse()

    def test_envelope_json_and_body_limits_fail_closed(self):
        for body in [b"", b"x"*65537, b"\xff", b"[]", b'{"bucket":NaN}',
                     b'{"bucket":"a","bucket":"b"}']:
            with self.subTest(body=body[:30]), self.assertRaises(InvalidEvent):
                parse_event(self.headers, body, BUCKET)
        for header, value in [("ce-id", "bad\nid"), ("ce-type", "different"),
                              ("ce-specversion", "0.3"), ("content-type", "text/html")]:
            old = dict(self.headers)
            self.headers[header] = value
            with self.subTest(header=header), self.assertRaises(InvalidEvent):
                self.parse()
            self.headers = old

    def test_event_id_is_not_the_business_deduplication_key(self):
        first = self.parse()
        self.headers["ce-id"] = "event-456"
        second = self.parse()
        self.assertNotEqual(first.event_id, second.event_id)
        self.assertEqual((first.job_id, first.generation),
                         (second.job_id, second.generation))


if __name__ == "__main__":
    unittest.main()
