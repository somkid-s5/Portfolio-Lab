"""Bounded adapters for Cloud Run Jobs v2 and Pub/Sub report-ready messages."""
from datetime import date, datetime, timezone
import json
import re

from app.schedule import BUSINESS_TZ

PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REGION_RE = re.compile(r"^[a-z]+(?:-[a-z0-9]+)+[0-9]$")
JOB_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
GENERATION_RE = re.compile(r"^[1-9][0-9]{0,29}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
CORRECTION_RE = re.compile(
    r"^incoming/business_date=(\d{4}-\d{2}-\d{2})/corrections/[A-Za-z0-9_-]{1,64}\.csv$"
)
REPORT_RE = re.compile(r"^reports/business_date=(\d{4}-\d{2}-\d{2})/summary\.json$")


class JobRequestError(RuntimeError):
    """Stable, non-sensitive Cloud Run Jobs API error."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class PublishUncertain(RuntimeError):
    """Publish failed or timed out; retry with the same report_id."""

    def __init__(self):
        super().__init__("publish_uncertain")


def _business_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("invalid_business_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid_business_date") from exc
    if parsed.isoformat() != value:
        raise ValueError("invalid_business_date")
    return parsed


class CloudRunJobRunner:
    """Calls the v2 run method with only the bounded argument overrides."""

    def __init__(self, session, *, project: str, region: str, job: str,
                 timeout_seconds: int = 10, clock=None):
        if (not isinstance(project, str) or not PROJECT_RE.fullmatch(project) or
                not isinstance(region, str) or not REGION_RE.fullmatch(region) or
                not isinstance(job, str) or not JOB_RE.fullmatch(job) or
                type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30):
            raise ValueError("invalid_job_runner_config")
        self.session = session
        self.project = project
        self.region = region
        self.job = job
        self.timeout_seconds = timeout_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def job_resource(self) -> str:
        return f"projects/{self.project}/locations/{self.region}/jobs/{self.job}"

    @property
    def run_url(self) -> str:
        return f"https://run.googleapis.com/v2/{self.job_resource}:run"

    def run_scheduled(self, business_date: str) -> str:
        _business_date(business_date)
        return self._run([f"--business-date={business_date}"])

    def run_operator_backfill(self, business_date: str, *,
                              source_object: str | None = None,
                              source_generation: str | None = None) -> str:
        target = _business_date(business_date)
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware_clock_required")
        local_today = now.astimezone(BUSINESS_TZ).date()
        if target >= local_today or target < local_today.fromordinal(local_today.toordinal() - 7):
            raise ValueError("backfill_outside_seven_day_window")
        if (source_object is None) != (source_generation is None):
            raise ValueError("correction_source_pair_required")
        args = ["--mode=operator-backfill", f"--business-date={business_date}"]
        if source_object is not None:
            match = CORRECTION_RE.fullmatch(source_object)
            if not match or match.group(1) != business_date:
                raise ValueError("invalid_correction_source")
            if not isinstance(source_generation, str) or not GENERATION_RE.fullmatch(source_generation):
                raise ValueError("invalid_source_generation")
            args.extend([f"--source-object={source_object}",
                         f"--source-generation={source_generation}"])
        return self._run(args)

    def _run(self, args: list[str]) -> str:
        body = {"overrides": {"containerOverrides": [{"args": args}]}}
        try:
            response = self.session.post(self.run_url, json=body,
                                         timeout=self.timeout_seconds)
            response.raise_for_status()
            result = response.json()
        except Exception as exc:
            raise JobRequestError("RUN_API_UNAVAILABLE") from exc
        if not isinstance(result, dict):
            raise JobRequestError("RUN_API_INVALID_RESPONSE")
        operation = result.get("name")
        expected_prefix = (
            f"projects/{self.project}/locations/{self.region}/operations/"
        )
        if not isinstance(operation, str) or not operation.startswith(expected_prefix):
            raise JobRequestError("RUN_API_INVALID_RESPONSE")
        return operation


class ReportReadyPublisher:
    """Publishes a small stable-identity event; consumers deduplicate by report_id."""

    def __init__(self, publisher, *, topic: str, timeout_seconds: int = 10):
        match = re.fullmatch(
            r"projects/([a-z][a-z0-9-]{4,28}[a-z0-9])/topics/([A-Za-z][A-Za-z0-9._~+%-]{2,254})",
            topic if isinstance(topic, str) else "",
        )
        if not match or type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 30:
            raise ValueError("invalid_pubsub_config")
        self.publisher = publisher
        self.topic = topic
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _event(report: dict) -> tuple[bytes, dict[str, str]]:
        if not isinstance(report, dict):
            raise ValueError("invalid_report_event")
        required = {"object", "generation", "sha256", "report_id",
                    "source_generation", "source_sha256"}
        if set(report) != required:
            raise ValueError("invalid_report_event")
        object_match = REPORT_RE.fullmatch(report["object"]) if isinstance(report["object"], str) else None
        if (not object_match or not isinstance(report["generation"], str) or
                not GENERATION_RE.fullmatch(report["generation"]) or
                not isinstance(report["source_generation"], str) or
                not GENERATION_RE.fullmatch(report["source_generation"]) or
                any(not isinstance(report[key], str) or not HASH_RE.fullmatch(report[key])
                    for key in ("sha256", "report_id", "source_sha256"))):
            raise ValueError("invalid_report_event")
        business_date = object_match.group(1)
        event = {
            "schema_version": 1,
            "event_type": "report.ready",
            "event_id": report["report_id"],
            "business_date": business_date,
            "report": {
                "object": report["object"],
                "generation": report["generation"],
                "sha256": report["sha256"],
            },
            "source": {
                "generation": report["source_generation"],
                "sha256": report["source_sha256"],
            },
        }
        attributes = {
            "event_type": "report.ready",
            "event_id": report["report_id"],
            "business_date": business_date,
            "report_generation": report["generation"],
            "report_sha256": report["sha256"],
        }
        payload = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        return payload, attributes

    def publish(self, report: dict) -> str:
        payload, attributes = self._event(report)
        try:
            future = self.publisher.publish(self.topic, payload, **attributes)
            message_id = future.result(timeout=self.timeout_seconds)
        except Exception as exc:
            raise PublishUncertain() from exc
        if not isinstance(message_id, str) or not message_id:
            raise PublishUncertain()
        return message_id
