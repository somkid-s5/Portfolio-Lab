"""Private Cloud Run coordinator routes for Scheduler and read-only watchdog checks."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
from typing import Callable

from flask import Flask, jsonify, make_response, request

from app.schedule import ScheduleRequestError, scheduler_business_date
from app.storage import ArtifactConflict, SourceMissing


@dataclass(frozen=True)
class CoordinatorDependencies:
    runner: object
    ledger: object
    objects: object
    report_job_name: str
    watchdog_job_name: str
    event_sink: Callable[[dict], None] | None = None


def _stdout_event(event: dict) -> None:
    sys.stdout.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def create_app(deps: CoordinatorDependencies) -> Flask:
    """Build the Flask app without initializing credentials or making cloud calls."""
    if (not deps.report_job_name or not deps.watchdog_job_name or
            deps.report_job_name == deps.watchdog_job_name):
        raise ValueError("distinct_scheduler_job_names_required")
    emit = deps.event_sink or _stdout_event
    app = Flask(__name__)

    def scheduler_error(exc: ScheduleRequestError):
        status = 403 if exc.code in {"NOT_SCHEDULER_REQUEST", "UNEXPECTED_SCHEDULER_JOB"} else 400
        return jsonify({"error": exc.code}), status

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True}), 200

    @app.post("/schedule")
    def schedule():
        try:
            business_date = scheduler_business_date(
                request.headers, expected_job_name=deps.report_job_name)
        except ScheduleRequestError as exc:
            return scheduler_error(exc)
        try:
            operation = deps.runner.run_scheduled(business_date)
        except Exception:
            emit({
                "event": "daily_job_start_failed",
                "business_date": business_date,
                "reason": "run_api_unavailable",
            })
            return jsonify({"error": "RUN_API_UNAVAILABLE"}), 503
        return jsonify({
            "accepted": True,
            "business_date": business_date,
            "operation": operation,
        }), 202

    @app.post("/watchdog")
    def watchdog():
        try:
            business_date = scheduler_business_date(
                request.headers, expected_job_name=deps.watchdog_job_name)
        except ScheduleRequestError as exc:
            return scheduler_error(exc)

        try:
            record = deps.ledger.read(business_date)
            if record is None:
                emit({
                    "event": "daily_report_not_ready",
                    "business_date": business_date,
                    "status": "not_started",
                    "reason": "ledger_not_found",
                })
                return make_response("", 204)
            status = record.get("status")
            if status != "succeeded":
                emit({
                    "event": "daily_report_not_ready",
                    "business_date": business_date,
                    "status": status if isinstance(status, str) else "invalid",
                    "reason": record.get("safe_reason") or "run_not_succeeded",
                })
                return make_response("", 204)

            expected = {
                "report_id": record.get("report_id"),
                "source_generation": record.get("source_generation"),
                "source_sha256": record.get("source_sha256"),
            }
            try:
                deps.objects.verify_report(
                    record.get("report_object"),
                    record.get("report_generation"),
                    expected_sha256=record.get("report_sha256"),
                    expected_metadata=expected,
                )
            except SourceMissing:
                emit({
                    "event": "daily_report_not_ready",
                    "business_date": business_date,
                    "status": "succeeded",
                    "reason": "report_missing",
                })
                return make_response("", 204)
            except (ArtifactConflict, ValueError, TypeError):
                emit({
                    "event": "daily_report_not_ready",
                    "business_date": business_date,
                    "status": "succeeded",
                    "reason": "report_integrity",
                })
                return make_response("", 204)

            emit({
                "event": "daily_report_ready_verified",
                "business_date": business_date,
                "report_generation": str(record.get("report_generation")),
                "report_id": record.get("report_id"),
            })
            return make_response("", 204)
        except Exception:
            emit({
                "event": "daily_watchdog_dependency_error",
                "business_date": business_date,
                "reason": "dependency_unavailable",
            })
            return jsonify({"error": "WATCHDOG_DEPENDENCY_UNAVAILABLE"}), 503

    return app
