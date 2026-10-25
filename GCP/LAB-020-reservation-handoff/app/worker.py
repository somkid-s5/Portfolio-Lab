"""OIDC-authenticated Pub/Sub push worker for bounded CSV reports."""
import base64
import csv
import io
import json
import os
import re
import time
from datetime import date

from flask import Flask, jsonify, request
from sqlalchemy import text

from app.database import create_pool


def create_app(engine=None, storage=None):
    app = Flask(__name__)
    app.extensions["db"] = engine or create_pool()
    app.extensions["storage"] = storage
    app.config["REPORT_BUCKET"] = os.getenv("REPORT_BUCKET", "")
    app.config["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "local")
    app.config["WORKER_FAULT_MODE"] = os.getenv("WORKER_FAULT_MODE", "none")

    def get_storage():
        client = app.extensions["storage"]
        if client is None:
            from google.cloud import storage as storage_module

            client = storage_module.Client()
            app.extensions["storage"] = client
        return client

    @app.get("/healthz")
    def healthz():
        with app.extensions["db"].connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify(ready=True, environment=app.config["ENVIRONMENT"])

    @app.post("/events/reports")
    def report_event():
        started = time.monotonic()
        envelope = request.get_json(silent=True)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("message"), dict):
            return jsonify(error="invalid_pubsub_envelope"), 400
        try:
            raw = base64.b64decode(envelope["message"].get("data", ""), validate=True)
            payload = json.loads(raw)
        except Exception:
            return jsonify(error="invalid_pubsub_data"), 400
        if not isinstance(payload, dict):
            return jsonify(error="invalid_report_message"), 400
        if payload.get("schema_version") != 1:
            return jsonify(error="unsupported_schema_version"), 400
        report_id = payload.get("report_id")
        report_date = payload.get("report_date")
        if (
            not isinstance(report_id, str)
            or not re.fullmatch(r"[a-f0-9]{32}", report_id)
            or not isinstance(report_date, str)
        ):
            return jsonify(error="invalid_report_message"), 400
        try:
            date.fromisoformat(report_date)
        except ValueError:
            return jsonify(error="invalid_report_date"), 400
        if app.config["WORKER_FAULT_MODE"] == "503":
            print(json.dumps({"event": "worker_fault", "report_id": report_id}), flush=True)
            return jsonify(error="temporary_worker_fault"), 503

        with app.extensions["db"].begin() as connection:
            row = connection.execute(
                text(
                    "SELECT report_id, report_date, status, object_name "
                    "FROM report_jobs WHERE report_id=:id"
                ),
                {"id": report_id},
            ).mappings().first()
            if not row:
                print(json.dumps({"event": "report_not_found", "report_id": report_id}), flush=True)
                return "", 204
            if row["status"] == "ready" and row["object_name"]:
                return "", 204
            connection.execute(
                text(
                    "UPDATE report_jobs SET status='running', updated_at=CURRENT_TIMESTAMP "
                    "WHERE report_id=:id"
                ),
                {"id": report_id},
            )

        try:
            with app.extensions["db"].connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT booking_id, slot_id, status, created_at "
                        "FROM bookings WHERE substr(created_at, 1, 10)=:report_date "
                        "ORDER BY created_at ASC LIMIT 5001"
                    ),
                    {"report_date": report_date},
                ).mappings().all()
            if len(rows) > 5000:
                with app.extensions["db"].begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE report_jobs SET status='failed', updated_at=CURRENT_TIMESTAMP "
                            "WHERE report_id=:id"
                        ),
                        {"id": report_id},
                    )
                print(json.dumps({"event": "report_row_limit", "report_id": report_id}), flush=True)
                return "", 204
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(["booking_id", "slot_id", "status", "created_at"])
            for item in rows:
                writer.writerow(
                    [item["booking_id"], item["slot_id"], item["status"], item["created_at"]]
                )
            object_name = f"{app.config['ENVIRONMENT']}/reports/{report_id}.csv"
            blob = get_storage().bucket(app.config["REPORT_BUCKET"]).blob(object_name)
            try:
                blob.upload_from_string(
                    output.getvalue(),
                    content_type="text/csv; charset=utf-8",
                    if_generation_match=0,
                )
            except Exception as error:
                from google.api_core.exceptions import PreconditionFailed

                if not isinstance(error, PreconditionFailed):
                    raise
                blob.reload()
            with app.extensions["db"].begin() as connection:
                connection.execute(
                    text(
                        "UPDATE report_jobs SET status='ready', object_name=:object, "
                        "updated_at=CURRENT_TIMESTAMP WHERE report_id=:id"
                    ),
                    {"object": object_name, "id": report_id},
                )
            print(
                json.dumps(
                    {
                        "event": "report_ready",
                        "report_id": report_id,
                        "object_name": object_name,
                        "row_count": len(rows),
                        "duration_ms": round((time.monotonic() - started) * 1000, 2),
                    }
                ),
                flush=True,
            )
            return "", 204
        except Exception as error:
            with app.extensions["db"].begin() as connection:
                connection.execute(
                    text(
                        "UPDATE report_jobs SET status='queued', updated_at=CURRENT_TIMESTAMP "
                        "WHERE report_id=:id AND status!='ready'"
                    ),
                    {"id": report_id},
                )
            print(
                json.dumps(
                    {
                        "event": "report_retryable_error",
                        "report_id": report_id,
                        "error_type": type(error).__name__,
                    }
                ),
                flush=True,
            )
            return jsonify(error="report_retryable_error"), 503

    return app


app = create_app()
