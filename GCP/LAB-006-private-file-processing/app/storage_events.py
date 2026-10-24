"""Validate binary-mode Storage CloudEvents. This is not caller authentication.
Deploy receiver behind Cloud Run IAM; never trust ce-* headers as auth.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re

EVENT_TYPE = "google.cloud.storage.object.v1.finalized"


class InvalidEvent(ValueError):
    pass


@dataclass(frozen=True)
class StorageEvent:
    event_id: str
    job_id: str
    generation: str
    finalized_at: datetime


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z", value):
        raise InvalidEvent("invalid_timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        raise InvalidEvent("invalid_timestamp") from None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidEvent("duplicate_json_key")
        result[key] = value
    return result


def parse_event(headers, body, expected_bucket):
    """Return event or None for authentic but out-of-scope source/object.
    No URLs from the body are followed and no raw payload enters errors.
    """
    if (not isinstance(expected_bucket, str) or
            not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]", expected_bucket)):
        raise ValueError("invalid_bucket_configuration")
    if not isinstance(body, bytes) or not 1 <= len(body) <= 65536:
        raise InvalidEvent("invalid_body_size")
    lower = {str(key).lower(): value for key, value in headers.items()}
    if lower.get("ce-specversion") != "1.0" or lower.get("ce-type") != EVENT_TYPE:
        raise InvalidEvent("invalid_event_type")
    event_id = lower.get("ce-id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", event_id):
        raise InvalidEvent("invalid_event_id")
    content_type = lower.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise InvalidEvent("invalid_content_type")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              InvalidEvent("invalid_json_constant")))
    except (UnicodeError, ValueError, RecursionError):
        raise InvalidEvent("invalid_json") from None
    if not isinstance(data, dict):
        raise InvalidEvent("invalid_data")
    source = lower.get("ce-source")
    if (data.get("bucket") != expected_bucket or
            source != f"//storage.googleapis.com/projects/_/buckets/{expected_bucket}"):
        return None
    name = data.get("name")
    if not isinstance(name, str):
        raise InvalidEvent("invalid_object_name")
    match = re.fullmatch(r"incoming/([a-f0-9]{32})/source\.csv", name)
    if match is None:
        return None
    if lower.get("ce-subject") != f"objects/{name}":
        raise InvalidEvent("subject_mismatch")
    generation = data.get("generation")
    if not isinstance(generation, str) or not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
        raise InvalidEvent("invalid_generation")
    # timeCreated describes this object generation; delivery time is not upload time.
    finalized_at = _timestamp(data.get("timeCreated"))
    return StorageEvent(event_id, match.group(1), generation, finalized_at)
