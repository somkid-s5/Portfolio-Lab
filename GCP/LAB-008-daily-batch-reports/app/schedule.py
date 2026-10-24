"""Validation of Cloud Scheduler's authenticated request metadata."""
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo

BUSINESS_TZ = ZoneInfo("Asia/Bangkok")
RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class ScheduleRequestError(ValueError):
    """Safe coordinator input error suitable for a stable HTTP response."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def logical_business_date(schedule_time: str) -> str:
    if not isinstance(schedule_time, str) or not RFC3339.fullmatch(schedule_time):
        raise ScheduleRequestError("INVALID_SCHEDULE_TIME")
    try:
        parsed = datetime.fromisoformat(schedule_time.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleRequestError("INVALID_SCHEDULE_TIME") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ScheduleRequestError("INVALID_SCHEDULE_TIME")
    return (parsed.astimezone(BUSINESS_TZ).date() - timedelta(days=1)).isoformat()


def scheduler_business_date(headers: dict[str, str], *, expected_job_name: str) -> str:
    normalized = {str(key).lower(): str(value).strip() for key, value in headers.items()}
    if normalized.get("x-cloudscheduler", "").lower() != "true":
        raise ScheduleRequestError("NOT_SCHEDULER_REQUEST")
    if normalized.get("x-cloudscheduler-jobname") != expected_job_name:
        raise ScheduleRequestError("UNEXPECTED_SCHEDULER_JOB")
    schedule_time = normalized.get("x-cloudscheduler-scheduletime")
    if not schedule_time:
        raise ScheduleRequestError("MISSING_SCHEDULE_TIME")
    return logical_business_date(schedule_time)
