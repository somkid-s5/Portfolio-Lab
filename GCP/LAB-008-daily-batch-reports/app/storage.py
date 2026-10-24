"""Generation-pinned Cloud Storage adapter with create-only report artifacts."""
from hashlib import sha256
import io
import re

from google.api_core.exceptions import NotFound, PreconditionFailed

from app.domain import MAX_INPUT_BYTES

SOURCE_RE = re.compile(
    r"^incoming/business_date=(\d{4}-\d{2}-\d{2})/(?:transactions\.csv|corrections/[A-Za-z0-9_-]{1,64}\.csv)$"
)
REPORT_RE = re.compile(r"^reports/business_date=(\d{4}-\d{2}-\d{2})/summary\.json$")
GENERATION_RE = re.compile(r"^[1-9][0-9]{0,29}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
MAX_REPORT_BYTES = 2 * 1024 * 1024


class SourceMissing(Exception):
    pass


class SourceChanged(Exception):
    pass


class InvalidSource(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ArtifactConflict(Exception):
    pass


class CappedBuffer(io.BytesIO):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit

    def write(self, data):
        if self.tell() + len(data) > self.limit:
            raise InvalidSource("INPUT_TOO_LARGE")
        return super().write(data)


def _generation(value):
    value = str(value)
    if not GENERATION_RE.fullmatch(value):
        raise ValueError("invalid_generation")
    return int(value)


def _date_object(pattern, name, business_date=None):
    match = pattern.fullmatch(name) if isinstance(name, str) else None
    if not match or (business_date is not None and match.group(1) != business_date):
        raise ValueError("invalid_object_name")
    return match.group(1)


def _read_raw(blob, limit, generation):
    try:
        blob.reload(if_generation_match=generation, timeout=5, retry=None)
    except NotFound as exc:
        raise SourceMissing() from exc
    except PreconditionFailed as exc:
        raise SourceChanged() from exc
    if str(blob.generation) != str(generation):
        raise SourceChanged()
    if blob.content_encoding:
        raise InvalidSource("INVALID_ENCODING")
    if blob.size is None or int(blob.size) > limit:
        raise InvalidSource("INPUT_TOO_LARGE")
    buffer = CappedBuffer(limit)
    try:
        blob.download_to_file(buffer, start=0, end=limit - 1, raw_download=True,
                              if_generation_match=generation, timeout=5, retry=None,
                              checksum="auto", single_shot_download=False)
    except NotFound as exc:
        raise SourceMissing() from exc
    except PreconditionFailed as exc:
        raise SourceChanged() from exc
    data = buffer.getvalue()
    if len(data) != int(blob.size):
        raise SourceChanged()
    return data


class GCSObjects:
    def __init__(self, client, source_bucket: str, report_bucket: str):
        if (not isinstance(source_bucket, str) or not source_bucket or
                not isinstance(report_bucket, str) or not report_bucket or
                source_bucket == report_bucket):
            raise ValueError("separate_buckets_required")
        self.source = client.bucket(source_bucket)
        self.report = client.bucket(report_bucket)
        self.source_bucket = source_bucket
        self.report_bucket = report_bucket

    @staticmethod
    def default_source(business_date: str) -> str:
        return f"incoming/business_date={business_date}/transactions.csv"

    @staticmethod
    def report_name(business_date: str) -> str:
        return f"reports/business_date={business_date}/summary.json"

    def source_generation(self, object_name: str, *, business_date: str) -> str:
        _date_object(SOURCE_RE, object_name, business_date)
        blob = self.source.blob(object_name)
        try:
            blob.reload(timeout=5, retry=None)
        except NotFound as exc:
            raise SourceMissing() from exc
        if blob.size is None:
            raise InvalidSource("INPUT_TOO_LARGE")
        return str(_generation(blob.generation))

    def read_source(self, object_name: str, generation: str, *, business_date: str) -> bytes:
        _date_object(SOURCE_RE, object_name, business_date)
        generation_int = _generation(generation)
        blob = self.source.blob(object_name, generation=generation_int)
        if blob.content_type not in (None, "text/csv"):
            # Reload pinned metadata first; some SDK instances do not populate it until reload.
            try:
                blob.reload(if_generation_match=generation_int, timeout=5, retry=None)
            except NotFound as exc:
                raise SourceMissing() from exc
        data = _read_raw(blob, MAX_INPUT_BYTES, generation_int)
        if blob.content_type != "text/csv":
            raise InvalidSource("INVALID_CONTENT_TYPE")
        return data

    def _read_report(self, object_name: str, generation: str):
        _date_object(REPORT_RE, object_name)
        generation_int = _generation(generation)
        blob = self.report.blob(object_name, generation=generation_int)
        data = _read_raw(blob, MAX_REPORT_BYTES, generation_int)
        if blob.content_type != "application/json":
            raise ArtifactConflict("report_content_type_mismatch")
        return blob, data

    def create_report(self, business_date: str, body: bytes, *, source_generation: str,
                      source_sha256: str, report_id: str) -> dict:
        name = self.report_name(business_date)
        _date_object(REPORT_RE, name, business_date)
        _generation(source_generation)
        if (not isinstance(body, bytes) or not 1 <= len(body) <= MAX_REPORT_BYTES or
                not HASH_RE.fullmatch(source_sha256) or not HASH_RE.fullmatch(report_id)):
            raise ValueError("invalid_report_contract")
        output_sha256 = sha256(body).hexdigest()
        metadata = {"source_generation": source_generation,
                    "source_sha256": source_sha256, "report_id": report_id,
                    "output_sha256": output_sha256}
        blob = self.report.blob(name)
        blob.metadata = metadata
        blob.cache_control = "no-store"
        blob.content_disposition = 'attachment; filename="summary.json"'
        try:
            blob.upload_from_string(body, content_type="application/json",
                                    if_generation_match=0, timeout=5,
                                    retry=None, checksum="crc32c")
            generation = str(_generation(blob.generation))
        except PreconditionFailed:
            try:
                existing = self.report.blob(name)
                existing.reload(timeout=5, retry=None)
                generation = str(_generation(existing.generation))
                pinned, previous = self._read_report(name, generation)
            except (NotFound, SourceMissing) as exc:
                raise ArtifactConflict("existing_report_unreadable") from exc
            if (previous != body or pinned.metadata != metadata or
                    pinned.content_type != "application/json"):
                raise ArtifactConflict("existing_report_mismatch")
        return {"object": name, "generation": generation,
                "sha256": output_sha256, "report_id": report_id,
                "source_generation": source_generation,
                "source_sha256": source_sha256}

    def verify_report(self, object_name: str, generation: str, *,
                      expected_sha256: str, expected_metadata: dict | None = None) -> bytes:
        if not HASH_RE.fullmatch(expected_sha256):
            raise ValueError("invalid_expected_report_hash")
        try:
            blob, data = self._read_report(object_name, generation)
        except SourceMissing as exc:
            raise
        digest = sha256(data).hexdigest()
        if digest != expected_sha256 or blob.metadata is None:
            raise ArtifactConflict("report_hash_mismatch")
        if blob.metadata.get("output_sha256") != digest:
            raise ArtifactConflict("report_metadata_hash_mismatch")
        if expected_metadata is not None:
            for key, value in expected_metadata.items():
                if blob.metadata.get(key) != value:
                    raise ArtifactConflict("report_binding_mismatch")
        return data
