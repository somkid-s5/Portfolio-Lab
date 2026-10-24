"""SDK contract tests with mocked transport; never call real GCS."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, create_autospec

from google.cloud.storage import Blob
from google.api_core.exceptions import PreconditionFailed
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from gcs_objects import CappedBuffer, Objects, _raw_read
from csv_domain import Rejected
from processor import IntegrityFailure

NAME = "results/" + "a"*32 + "/123/v1/summary.json"
SOURCE = "incoming/" + "a"*32 + "/source.csv"


def blob(data=b"abc", generation=123, content_type="text/csv"):
    item = create_autospec(Blob, instance=True)
    item.generation = generation
    item.size = len(data)
    item.content_encoding = None
    item.content_type = content_type
    item.metadata = {}
    def download(sink, **kwargs):
        sink.write(data)
    item.download_to_file.side_effect = download
    return item


class GcsTests(unittest.TestCase):
    def setup_objects(self):
        client = Mock()
        client.bucket.side_effect = [Mock(), Mock()]
        return Objects(client, "incoming-test", "results-test")

    def test_read_pins_generation_bounds_range_and_disables_transcoding(self):
        objects = self.setup_objects()
        source = blob()
        objects.incoming.blob.return_value = source
        self.assertEqual(objects.read_source(SOURCE, "123", 10), b"abc")
        objects.incoming.blob.assert_called_once_with(SOURCE, generation=123)
        source.reload.assert_called_once_with(if_generation_match=123, timeout=5, retry=None)
        kwargs = source.download_to_file.call_args.kwargs
        self.assertEqual((kwargs["start"], kwargs["end"]), (0, 10))
        self.assertTrue(kwargs["raw_download"])
        self.assertEqual(kwargs["if_generation_match"], 123)
        self.assertIsNone(kwargs["retry"])

    def test_metadata_size_stops_download_and_buffer_catches_oversized_response(self):
        source = blob(b"x"*11)
        with self.assertRaises(Rejected):
            _raw_read(source, 10)
        source.download_to_file.assert_not_called()
        source = blob(b"x"*20)
        source.size = 10  # Simulate contradictory transport metadata.
        with self.assertRaises(Rejected):
            _raw_read(source, 10)
        capped = CappedBuffer(5)
        with self.assertRaises(Rejected):
            capped.write(b"x"*6)
        self.assertEqual(capped.getvalue(), b"")

    def test_encoded_mime_and_truncated_source_are_rejected(self):
        for mutation in ["encoding", "mime", "size"]:
            objects = self.setup_objects()
            source = blob()
            if mutation == "encoding":
                source.content_encoding = "gzip"
            elif mutation == "mime":
                source.content_type = "text/html"
            else:
                source.size = 4
            objects.incoming.blob.return_value = source
            with self.subTest(mutation=mutation), self.assertRaises(Rejected):
                objects.read_source(SOURCE, "123", 10)

    def test_new_result_is_create_only_and_has_safe_metadata(self):
        objects = self.setup_objects()
        target = blob(generation=456)
        objects.results.blob.return_value = target
        result = objects.create_or_verify(NAME, b"{}", input_sha256="b"*64,
                                          processor_version="v1")
        self.assertEqual(result, "456")
        call = target.upload_from_string.call_args
        self.assertEqual(call.args, (b"{}",))
        self.assertEqual(call.kwargs["if_generation_match"], 0)
        self.assertIsNone(call.kwargs["retry"])
        self.assertEqual(target.metadata["output_sha256"], hashlib.sha256(b"{}").hexdigest())

    def test_existing_result_is_pinned_and_verified_before_reuse(self):
        objects = self.setup_objects()
        target = blob()
        target.upload_from_string.side_effect = PreconditionFailed("exists")
        current = blob(generation=456)
        pinned = blob(b"{}", generation=456, content_type="application/json")
        pinned.metadata = {"input_sha256": "b"*64, "processor_version": "v1",
                           "output_sha256": hashlib.sha256(b"{}").hexdigest()}
        objects.results.blob.side_effect = [target, current, pinned]
        self.assertEqual(objects.create_or_verify(NAME, b"{}", input_sha256="b"*64,
                                                  processor_version="v1"), "456")
        self.assertEqual(objects.results.blob.call_args.kwargs, {"generation": 456})
        pinned.upload_from_string.assert_not_called()

    def test_existing_result_mismatch_is_not_overwritten(self):
        objects = self.setup_objects()
        target = blob()
        target.upload_from_string.side_effect = PreconditionFailed("exists")
        current = blob(generation=456)
        pinned = blob(b"evil", generation=456, content_type="application/json")
        objects.results.blob.side_effect = [target, current, pinned]
        with self.assertRaises(IntegrityFailure):
            objects.create_or_verify(NAME, b"{}", input_sha256="b"*64,
                                      processor_version="v1")
        pinned.upload_from_string.assert_not_called()

    def test_invalid_paths_and_limits_do_not_reach_transport(self):
        objects = self.setup_objects()
        for name, generation, limit in [("../secret", "123", 10),
                                         (SOURCE, "0", 10), (SOURCE, "123", True)]:
            with self.subTest(name=name, generation=generation), self.assertRaises(ValueError):
                objects.read_source(name, generation, limit)
        objects.incoming.blob.assert_not_called()
        with self.assertRaises(ValueError):
            objects.create_or_verify(NAME, b"{}", input_sha256="bad",
                                      processor_version="v1")


if __name__ == "__main__":
    unittest.main()
