"""GCS adapter: pinned generations, bounded raw reads and create-only results."""
import hashlib
import io
import re
from google.api_core.exceptions import PreconditionFailed
from csv_domain import Rejected
from processor import IntegrityFailure

MAX_OUTPUT = 8 * 1024 * 1024 - 1


class CappedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise Rejected("file_too_large")
        return super().write(data)


def _generation(value):
    value = str(value)
    if not re.fullmatch(r"[1-9][0-9]{0,29}", value):
        raise ValueError("invalid_generation")
    return int(value)


def _raw_read(blob, limit):
    # Metadata and byte request address the same immutable generation.
    generation = _generation(blob.generation)
    blob.reload(if_generation_match=generation, timeout=5, retry=None)
    if blob.content_encoding:
        raise IntegrityFailure("encoded_object_not_allowed")
    if blob.size is None or int(blob.size) > limit:
        raise Rejected("file_too_large")
    buffer = CappedBuffer(limit + 1)
    blob.download_to_file(buffer, start=0, end=limit, raw_download=True,
                          if_generation_match=generation, timeout=5,
                          retry=None, checksum="auto", single_shot_download=False)
    data = buffer.getvalue()
    if len(data) > limit:
        raise Rejected("file_too_large")
    if len(data) != int(blob.size):
        raise IntegrityFailure("size_mismatch")
    return data


class Objects:
    def __init__(self, client, incoming_bucket, results_bucket):
        if incoming_bucket == results_bucket:
            raise ValueError("separate_buckets_required")
        self.incoming = client.bucket(incoming_bucket)
        self.results = client.bucket(results_bucket)

    def read_source(self, name, generation, max_bytes):
        if (not re.fullmatch(r"incoming/[a-f0-9]{32}/source\.csv", name) or
                type(max_bytes) is not int or not 1 <= max_bytes <= 5242880):
            raise ValueError("invalid_source_contract")
        blob = self.incoming.blob(name, generation=_generation(generation))
        try:
            data = _raw_read(blob, max_bytes)
        except IntegrityFailure:
            # Compressed/contradictory source is invalid input, not a report corruption.
            raise Rejected("malformed_csv") from None
        if blob.content_type != "text/csv":
            raise Rejected("malformed_csv")
        return data

    def create_or_verify(self, name, body, *, input_sha256, processor_version):
        if (not re.fullmatch(
                r"results/[a-f0-9]{32}/[1-9][0-9]{0,29}/[A-Za-z0-9_-]{1,32}/summary\.json",
                name) or not isinstance(body, bytes) or not 1 <= len(body) <= MAX_OUTPUT or
                not re.fullmatch(r"[a-f0-9]{64}", input_sha256) or
                not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", processor_version) or
                name.split("/")[-2] != processor_version):
            raise ValueError("invalid_result_contract")
        metadata = {"input_sha256": input_sha256,
                    "processor_version": processor_version,
                    "output_sha256": hashlib.sha256(body).hexdigest()}
        blob = self.results.blob(name)
        blob.metadata = metadata
        blob.cache_control = "no-store"
        blob.content_disposition = 'attachment; filename="summary.json"'
        try:
            blob.upload_from_string(body, content_type="application/json",
                                    if_generation_match=0, timeout=5,
                                    retry=None, checksum="crc32c")
            return str(_generation(blob.generation))
        except PreconditionFailed:
            # Discover current generation once, then pin both metadata and bytes.
            existing = self.results.blob(name)
            existing.reload(timeout=5, retry=None)
            pinned = self.results.blob(name, generation=_generation(existing.generation))
            try:
                previous = _raw_read(pinned, MAX_OUTPUT)
            except Rejected:
                raise IntegrityFailure("existing_result_too_large") from None
            if (previous != body or pinned.metadata != metadata or
                    pinned.content_type != "application/json"):
                raise IntegrityFailure("existing_result_mismatch")
            return str(_generation(pinned.generation))
