"""Daily report orchestration over source-pinned storage and transactional ledger."""
from datetime import date, datetime, timedelta, timezone

from app.domain import InputError, build_report
from app.ledger_state import StateConflict
from app.schedule import BUSINESS_TZ
from app.storage import (ArtifactConflict, InvalidSource, SourceChanged,
                         SourceMissing)
from app.integrations import PublishUncertain


class WorkerFailure(RuntimeError):
    """Safe worker failure code; the original dependency error is never rendered."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class DailyReportWorker:
    def __init__(self, *, ledger, objects, publisher, clock=None,
                 after_report_recorded=None):
        self.ledger = ledger
        self.objects = objects
        self.publisher = publisher
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.after_report_recorded = after_report_recorded

    def run(self, *, business_date: str, execution: str, task_attempt: int,
            mode: str = "scheduled", source_object: str | None = None,
            source_generation: str | None = None) -> dict:
        target = _parse_date(business_date)
        operator = mode == "operator-backfill"
        if mode not in {"scheduled", "operator-backfill"}:
            raise ValueError("invalid_run_mode")
        if not operator and (source_object is not None or source_generation is not None):
            raise ValueError("scheduled_source_override_forbidden")
        if (source_object is None) != (source_generation is None):
            raise ValueError("correction_source_pair_required")
        if operator:
            _check_backfill_window(target, self.clock())
        explicit_source = source_object is not None
        source_object = source_object or self.objects.default_source(business_date)

        if source_generation is None:
            try:
                source_generation = self.objects.source_generation(
                    source_object, business_date=business_date)
            except SourceMissing:
                if explicit_source:
                    raise WorkerFailure("correction_source_missing")
                _, disposition = self.ledger.mark_missing_input(business_date)
                return {"status": disposition, "business_date": business_date}

        try:
            record, disposition, token = self.ledger.claim(
                business_date=business_date, execution=execution,
                task_attempt=task_attempt, source_object=source_object,
                source_generation=source_generation,
                operator_backfill=operator,
            )
        except StateConflict as exc:
            raise WorkerFailure(exc.code) from exc
        if disposition != "claimed":
            return {"status": disposition, "business_date": business_date}

        try:
            source_bytes = self.objects.read_source(
                source_object, source_generation, business_date=business_date)
            report = build_report(source_bytes, business_date=business_date,
                                  source_generation=source_generation)
        except (InvalidSource, InputError) as exc:
            code = exc.code
            try:
                self.ledger.block_invalid_source(business_date, token, code=code)
            except StateConflict as transition_error:
                raise WorkerFailure(transition_error.code) from transition_error
            return {"status": "blocked", "business_date": business_date,
                    "reason": "invalid_source", "validation_code": code}
        except (SourceMissing, SourceChanged) as exc:
            self._release(business_date, token, "dependency_failure")
            raise WorkerFailure("source_generation_unavailable") from exc

        try:
            artifact = self.objects.create_report(
                business_date, report.canonical_json,
                source_generation=report.source_generation,
                source_sha256=report.source_sha256,
                report_id=report.report_id,
            )
        except ArtifactConflict as exc:
            self._release(business_date, token, "output_integrity")
            raise WorkerFailure("output_integrity") from exc
        except Exception as exc:
            self._release(business_date, token, "dependency_failure")
            raise WorkerFailure("report_storage_unavailable") from exc

        try:
            record = self.ledger.record_report(
                business_date, token, report=artifact)
            if self.after_report_recorded is not None:
                self.after_report_recorded(dict(artifact))
            record = self.ledger.mark_notification_pending(
                business_date, token, report_id=report.report_id)
        except StateConflict as exc:
            raise WorkerFailure(exc.code) from exc

        try:
            self.publisher.publish(artifact)
        except Exception as exc:
            try:
                self.ledger.release_attempt(
                    business_date, token, reason="transient_publish")
            except StateConflict as transition_error:
                raise WorkerFailure(transition_error.code) from transition_error
            if isinstance(exc, PublishUncertain):
                raise WorkerFailure("notification_publish_uncertain") from exc
            raise WorkerFailure("notification_publish_uncertain") from exc

        try:
            self.ledger.mark_succeeded(
                business_date, token, report_id=report.report_id)
        except StateConflict as exc:
            # A published event can be repeated after lease recovery; report_id remains stable.
            raise WorkerFailure(exc.code) from exc
        return {
            "status": "succeeded",
            "business_date": business_date,
            "report_id": report.report_id,
            "report_generation": artifact["generation"],
            "source_generation": report.source_generation,
            "source_sha256": report.source_sha256,
            "report_sha256": artifact["sha256"],
        }

    def _release(self, business_date, token, reason):
        try:
            self.ledger.release_attempt(business_date, token, reason=reason)
        except StateConflict as exc:
            raise WorkerFailure(exc.code) from exc


def _parse_date(value: str) -> date:
    if not isinstance(value, str):
        raise ValueError("invalid_business_date")
    try:
        target = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid_business_date") from exc
    if target.isoformat() != value:
        raise ValueError("invalid_business_date")
    return target


def _check_backfill_window(target: date, now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware_clock_required")
    local_today = now.astimezone(BUSINESS_TZ).date()
    if target >= local_today or target < local_today - timedelta(days=7):
        raise ValueError("backfill_outside_seven_day_window")
