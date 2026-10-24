"""Pure Firestore-ledger state transitions for daily report runs.

All persistence is performed by firestore_ledger.py in transactions. This module
contains no I/O, random token generation, or wall-clock reads.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import re

LEASE = timedelta(minutes=15)
MAX_TASK_ATTEMPT = 1
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENERATION_RE = re.compile(r"^[1-9][0-9]{0,29}$")
EXECUTION_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
REPORT_PATH_RE = re.compile(r"^reports/business_date=(\d{4}-\d{2}-\d{2})/summary\.json$")
SOURCE_RE = re.compile(
    r"^incoming/business_date=(\d{4}-\d{2}-\d{2})/(?:transactions\.csv|corrections/[A-Za-z0-9_-]{1,64}\.csv)$"
)
INVALID_SOURCE_CODES = {
    "INVALID_UTF8", "INPUT_TOO_LARGE", "INVALID_HEADER", "INVALID_ROW_SHAPE",
    "MALFORMED_CSV", "EMPTY_REPORT", "INVALID_TRANSACTION_ID",
    "DUPLICATE_TRANSACTION_ID", "INVALID_TIMESTAMP", "TIMEZONE_REQUIRED",
    "BUSINESS_DATE_MISMATCH", "INVALID_SKU", "INVALID_QUANTITY",
    "INVALID_UNIT_PRICE", "UNSUPPORTED_CURRENCY", "TOO_MANY_ROWS",
    "INVALID_ENCODING", "INVALID_CONTENT_TYPE",
}


class StateConflict(ValueError):
    """A safe state-machine conflict with a stable code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _date(value: str) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise StateConflict("invalid_business_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise StateConflict("invalid_business_date") from exc
    if parsed.isoformat() != value:
        raise StateConflict("invalid_business_date")
    return value


def _utc(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise StateConflict("utc_time_required")


def _source(business_date: str, object_name: str, generation: str) -> None:
    match = SOURCE_RE.fullmatch(object_name) if isinstance(object_name, str) else None
    if not match or match.group(1) != business_date:
        raise StateConflict("invalid_source_object")
    if not isinstance(generation, str) or not GENERATION_RE.fullmatch(generation):
        raise StateConflict("invalid_source_generation")


def new_record(business_date: str, now: datetime) -> dict:
    business_date = _date(business_date)
    _utc(now)
    return {
        "business_date": business_date,
        "status": "not_started",
        "fence": 0,
        "attempt_count": 0,
        "owner_execution": None,
        "task_attempt": None,
        "last_execution": None,
        "last_task_attempt": None,
        "lease_until": None,
        "source_object": None,
        "source_generation": None,
        "source_sha256": None,
        "report_object": None,
        "report_generation": None,
        "report_sha256": None,
        "report_id": None,
        "notification_state": "not_started",
        "safe_reason": None,
        "validation_code": None,
        "history_count": 0,
        "history_truncated": False,
        "history": [],
        "created_at": now,
        "updated_at": now,
    }


def _event(record: dict, now: datetime, event: str, reason: str | None = None) -> None:
    record["updated_at"] = now
    record["history_count"] = record.get("history_count", 0) + 1
    history = list(record.get("history", []))
    history.append({
        "at": now,
        "event": event,
        "status": record["status"],
        "fence": record["fence"],
        "task_attempt": record.get("task_attempt"),
        "source_generation": record.get("source_generation"),
        "reason": reason,
    })
    if len(history) > 100:
        record["history_truncated"] = True
        history = history[-100:]
    record["history"] = history


def claim(existing: dict | None, *, business_date: str, now: datetime,
          execution: str, task_attempt: int, source_object: str,
          source_generation: str, operator_backfill: bool = False):
    """Claim a source-bound execution, returning (record, disposition, fence token)."""
    business_date = _date(business_date)
    _utc(now)
    if not isinstance(execution, str) or not EXECUTION_RE.fullmatch(execution):
        raise StateConflict("invalid_execution")
    if type(task_attempt) is not int or not 0 <= task_attempt <= MAX_TASK_ATTEMPT:
        raise StateConflict("invalid_task_attempt")
    _source(business_date, source_object, source_generation)

    record = new_record(business_date, now) if existing is None else deepcopy(existing)
    if record.get("business_date") != business_date:
        raise StateConflict("ledger_date_mismatch")
    if record["status"] == "succeeded":
        return record, "succeeded", None

    candidate = (source_object, source_generation)
    current = (record.get("source_object"), record.get("source_generation"))
    replacing_source = current[0] is not None and current != candidate
    if replacing_source:
        correction = "/corrections/" in source_object
        permitted = (
            operator_backfill and correction and record["status"] == "blocked" and
            record.get("safe_reason") == "invalid_source" and
            record.get("report_generation") is None and
            record.get("notification_state") == "not_started"
        )
        if not permitted:
            raise StateConflict("source_binding_conflict")
        record.update(source_object=source_object, source_generation=source_generation,
                      source_sha256=None, status="not_started", safe_reason=None,
                      validation_code=None)
        _event(record, now, "operator_source_correction")

    if record.get("source_object") is None:
        record.update(source_object=source_object, source_generation=source_generation)
    elif (record["source_object"], record["source_generation"]) != candidate:
        raise StateConflict("source_binding_conflict")

    if record["status"] == "blocked":
        return record, "blocked", None
    if record["status"] == "failed" and not operator_backfill:
        same_run_retry = (
            record.get("last_execution") == execution and
            record.get("last_task_attempt") is not None and
            task_attempt > record["last_task_attempt"]
        )
        if not same_run_retry:
            return record, "needs_operator", None

    lease_until = record.get("lease_until")
    lease_active = lease_until is not None and now < lease_until
    is_retry = (
        record.get("last_execution") == execution and
        record.get("last_task_attempt") is not None and
        task_attempt > record["last_task_attempt"]
    )
    if lease_active and not is_retry:
        return record, "busy", None
    if record["status"] not in {
        "not_started", "missing_input", "running", "report_written",
        "notification_pending", "failed"
    }:
        raise StateConflict("invalid_transition")

    previous_status = record["status"]
    record["fence"] += 1
    record["attempt_count"] = (
        record.get("attempt_count", 0) + 1 if record.get("last_execution") == execution
        else 1
    )
    record.update(
        owner_execution=execution,
        task_attempt=task_attempt,
        last_execution=execution,
        last_task_attempt=task_attempt,
        lease_until=now + LEASE,
        safe_reason=None,
        validation_code=None,
    )
    if previous_status in {"not_started", "missing_input", "failed"}:
        record["status"] = "running"
    _event(record, now, "task_retry" if is_retry else "claimed")
    token = {"execution": execution, "task_attempt": task_attempt,
             "fence": record["fence"]}
    return record, "claimed", token


def mark_missing_input(existing: dict | None, *, business_date: str, now: datetime):
    business_date = _date(business_date)
    _utc(now)
    record = new_record(business_date, now) if existing is None else deepcopy(existing)
    if record.get("business_date") != business_date:
        raise StateConflict("ledger_date_mismatch")
    if record["status"] == "succeeded":
        return record, "succeeded"
    lease_until = record.get("lease_until")
    if lease_until is not None and now < lease_until:
        return record, "busy"
    if record.get("source_object") is not None:
        return record, "source_already_bound"
    record.update(status="missing_input", safe_reason="missing_input",
                  owner_execution=None, task_attempt=None, lease_until=None)
    _event(record, now, "missing_input", "missing_input")
    return record, "missing_input"


def _owned(record: dict, token: dict, now: datetime) -> None:
    _utc(now)
    if (record.get("owner_execution") != token.get("execution") or
            record.get("task_attempt") != token.get("task_attempt") or
            record.get("fence") != token.get("fence") or
            record.get("lease_until") is None or now >= record["lease_until"]):
        raise StateConflict("stale_fence")
    if record["status"] not in {"running", "report_written", "notification_pending"}:
        raise StateConflict("invalid_transition")


def block_invalid_source(record: dict, token: dict, *, now: datetime, code: str):
    if code not in INVALID_SOURCE_CODES:
        raise StateConflict("unsafe_validation_code")
    _owned(record, token, now)
    item = deepcopy(record)
    item.update(status="blocked", safe_reason="invalid_source",
                validation_code=code, owner_execution=None, task_attempt=None,
                lease_until=None)
    _event(item, now, "blocked", "invalid_source")
    return item


def record_report(record: dict, token: dict, *, now: datetime, report: dict):
    _owned(record, token, now)
    required = {"object", "generation", "sha256", "report_id",
                "source_generation", "source_sha256"}
    if set(report) != required:
        raise StateConflict("invalid_report_metadata")
    expected_name = f"reports/business_date={record['business_date']}/summary.json"
    if (report["object"] != expected_name or
            not isinstance(report["generation"], str) or
            not GENERATION_RE.fullmatch(report["generation"]) or
            report["source_generation"] != record["source_generation"] or
            not isinstance(report["sha256"], str) or not HASH_RE.fullmatch(report["sha256"]) or
            not isinstance(report["source_sha256"], str) or
            not HASH_RE.fullmatch(report["source_sha256"]) or
            not isinstance(report["report_id"], str) or not HASH_RE.fullmatch(report["report_id"])):
        raise StateConflict("report_binding_mismatch")
    item = deepcopy(record)
    if item["status"] in {"report_written", "notification_pending"}:
        previous = {
            "object": item.get("report_object"),
            "generation": item.get("report_generation"),
            "sha256": item.get("report_sha256"),
            "report_id": item.get("report_id"),
            "source_generation": item.get("source_generation"),
            "source_sha256": item.get("source_sha256"),
        }
        expected = dict(report)
        if previous != expected:
            raise StateConflict("report_integrity_conflict")
        return item
    if item["status"] != "running":
        raise StateConflict("invalid_transition")
    item.update(status="report_written", report_object=report["object"],
                report_generation=report["generation"], report_sha256=report["sha256"],
                report_id=report["report_id"], source_sha256=report["source_sha256"])
    _event(item, now, "report_written")
    return item


def mark_notification_pending(record: dict, token: dict, *, now: datetime,
                              report_id: str):
    _owned(record, token, now)
    if record.get("report_id") != report_id:
        raise StateConflict("notification_report_mismatch")
    if record["status"] == "notification_pending":
        return deepcopy(record)
    if record["status"] != "report_written":
        raise StateConflict("invalid_transition")
    item = deepcopy(record)
    item.update(status="notification_pending", notification_state="pending")
    _event(item, now, "notification_pending")
    return item


def mark_succeeded(record: dict, token: dict, *, now: datetime, report_id: str):
    _owned(record, token, now)
    if record["status"] == "succeeded":
        return deepcopy(record)
    if record["status"] != "notification_pending" or record.get("report_id") != report_id:
        raise StateConflict("notification_not_pending")
    item = deepcopy(record)
    item.update(status="succeeded", notification_state="published",
                owner_execution=None, task_attempt=None, lease_until=None,
                safe_reason=None)
    _event(item, now, "succeeded")
    return item


def release_attempt(record: dict, token: dict, *, now: datetime, reason: str):
    if reason not in {"dependency_failure", "transient_publish", "output_integrity"}:
        raise StateConflict("unsafe_failure_reason")
    _owned(record, token, now)
    item = deepcopy(record)
    if item["status"] == "running":
        item["status"] = "failed"
    item.update(safe_reason=reason, owner_execution=None, task_attempt=None,
                lease_until=None)
    _event(item, now, "attempt_released", reason)
    return item
