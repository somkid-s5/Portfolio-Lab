"""IAP-protected staff booking API and browser UI."""
import hashlib
import json
import os
import re
import time
import uuid
from datetime import date

from flask import Flask, Response, g, jsonify, render_template, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import HTTPException

from app.database import create_pool

_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,80}$")
_SLOT = re.compile(r"^[a-z0-9-]{3,48}$")
_REPORT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Problem(Exception):
    def __init__(self, status, code):
        self.status = status
        self.code = code


def verify_iap_identity():
    if os.getenv("APP_LOCAL_TEST") == "1" and not os.getenv("K_SERVICE"):
        email = request.headers.get("X-Test-User", "tester@example.invalid")
        return email if "@" in email else None

    assertion = request.headers.get("X-Goog-IAP-JWT-Assertion", "")
    audience = os.getenv("IAP_AUDIENCE", "")
    if not assertion or not audience:
        return None
    try:
        claims = id_token.verify_token(
            assertion,
            google_requests.Request(),
            audience=audience,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
    except Exception:
        return None
    if claims.get("iss") != "https://cloud.google.com/iap":
        return None
    email = claims.get("email")
    return email if isinstance(email, str) and "@" in email else None


def create_app(engine=None, publisher=None, storage=None, identity_resolver=None):
    app = Flask(__name__)
    app.extensions["db"] = engine or create_pool()
    app.extensions["publisher"] = publisher
    app.extensions["storage"] = storage
    app.extensions["identity_resolver"] = identity_resolver or verify_iap_identity
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.config["ENVIRONMENT"] = os.getenv("ENVIRONMENT", "local")
    app.config["REPORT_BUCKET"] = os.getenv("REPORT_BUCKET", "")
    app.config["REPORT_TOPIC"] = os.getenv("REPORT_TOPIC", "")
    app.config["GOOGLE_CLOUD_PROJECT"] = os.getenv("GOOGLE_CLOUD_PROJECT", "")

    def database():
        return app.extensions["db"]

    def get_publisher():
        client = app.extensions["publisher"]
        if client is None:
            from google.cloud import pubsub_v1

            client = pubsub_v1.PublisherClient()
            app.extensions["publisher"] = client
        return client

    def get_storage():
        client = app.extensions["storage"]
        if client is None:
            from google.cloud import storage as storage_module

            client = storage_module.Client()
            app.extensions["storage"] = client
        return client

    @app.before_request
    def request_context():
        g.request_id = uuid.uuid4().hex
        g.started = time.monotonic()
        if request.path in ("/healthz", "/livez") or request.path.startswith("/static/"):
            return
        identity = app.extensions["identity_resolver"]()
        if not identity:
            raise Problem(401, "iap_identity_required")
        g.actor = identity
        g.actor_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    @app.after_request
    def log_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        )
        print(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": getattr(g, "request_id", ""),
                    "path": request.path,
                    "method": request.method,
                    "status": response.status_code,
                    "actor_hash": (
                        hashlib.sha256(g.actor.encode("utf-8")).hexdigest()[:16]
                        if getattr(g, "actor", None)
                        else "health-check"
                    ),
                    "revision": os.getenv("K_REVISION", "local"),
                    "duration_ms": round(
                        (time.monotonic() - getattr(g, "started", time.monotonic())) * 1000,
                        2,
                    ),
                }
            ),
            flush=True,
        )
        return response

    @app.errorhandler(Problem)
    def expected_error(error):
        return jsonify(error=error.code, request_id=getattr(g, "request_id", "")), error.status

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        print(
            json.dumps(
                {
                    "event": "database_unavailable",
                    "request_id": getattr(g, "request_id", ""),
                    "error_type": type(error).__name__,
                }
            ),
            flush=True,
        )
        return jsonify(error="database_unavailable", request_id=g.request_id), 503

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.name.lower().replace(" ", "_")), error.code

    @app.get("/")
    def home():
        return render_template("index.html", environment=app.config["ENVIRONMENT"])

    @app.get("/livez")
    def livez():
        return jsonify(alive=True, environment=app.config["ENVIRONMENT"])

    @app.get("/healthz")
    def healthz():
        with database().connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify(ready=True, environment=app.config["ENVIRONMENT"])

    @app.get("/api/slots")
    def slots():
        with database().connect() as connection:
            rows = connection.execute(
                text("SELECT slot_id, label, starts_at, capacity, booked FROM slots ORDER BY starts_at")
            ).mappings().all()
        return jsonify(slots=[dict(row) for row in rows])

    @app.get("/api/bookings")
    def bookings():
        with database().connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT booking_id, slot_id, status, created_at "
                    "FROM bookings WHERE created_by=:actor ORDER BY created_at DESC LIMIT 100"
                ),
                {"actor": g.actor},
            ).mappings().all()
        return jsonify(bookings=[dict(row) for row in rows])

    @app.post("/api/bookings")
    def create_booking():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"slot_id"}:
            raise Problem(400, "invalid_booking")
        slot_id = payload.get("slot_id")
        key = request.headers.get("Idempotency-Key", "")
        if not isinstance(slot_id, str) or not _SLOT.fullmatch(slot_id) or not _KEY.fullmatch(key):
            raise Problem(400, "invalid_booking")
        booking_id = uuid.uuid4().hex
        try:
            with database().begin() as connection:
                existing = connection.execute(
                    text(
                        "SELECT booking_id, slot_id, status FROM bookings "
                        "WHERE created_by=:actor AND idempotency_key=:key"
                    ),
                    {"actor": g.actor, "key": key},
                ).mappings().first()
                if existing:
                    if existing["slot_id"] != slot_id:
                        raise Problem(409, "idempotency_key_conflict")
                    return jsonify(booking=dict(existing), replayed=True), 200
                result = connection.execute(
                    text(
                        "UPDATE slots SET booked=booked+1 "
                        "WHERE slot_id=:slot AND booked<capacity"
                    ),
                    {"slot": slot_id},
                )
                if result.rowcount != 1:
                    exists = connection.execute(
                        text("SELECT 1 FROM slots WHERE slot_id=:slot"), {"slot": slot_id}
                    ).first()
                    raise Problem(409 if exists else 404, "slot_full" if exists else "slot_not_found")
                connection.execute(
                    text(
                        "INSERT INTO bookings(booking_id, created_by, slot_id, idempotency_key, status) "
                        "VALUES (:id, :actor, :slot, :key, 'confirmed')"
                    ),
                    {"id": booking_id, "actor": g.actor, "slot": slot_id, "key": key},
                )
        except IntegrityError:
            with database().connect() as connection:
                existing = connection.execute(
                    text(
                        "SELECT booking_id, slot_id, status FROM bookings "
                        "WHERE created_by=:actor AND idempotency_key=:key"
                    ),
                    {"actor": g.actor, "key": key},
                ).mappings().first()
            if existing and existing["slot_id"] == slot_id:
                return jsonify(booking=dict(existing), replayed=True), 200
            raise Problem(409, "idempotency_key_conflict")
        print(
            json.dumps(
                {
                    "event": "booking_created",
                    "request_id": g.request_id,
                    "booking_id": booking_id,
                    "slot_id": slot_id,
                    "actor_hash": hashlib.sha256(g.actor.encode("utf-8")).hexdigest()[:16],
                }
            ),
            flush=True,
        )
        return jsonify(
            booking={"booking_id": booking_id, "slot_id": slot_id, "status": "confirmed"},
            replayed=False,
        ), 201

    @app.post("/api/bookings/<booking_id>/cancel")
    def cancel_booking(booking_id):
        if not re.fullmatch(r"[a-f0-9]{32}", booking_id):
            raise Problem(404, "booking_not_found")
        with database().begin() as connection:
            row = connection.execute(
                text(
                    "SELECT slot_id, status FROM bookings "
                    "WHERE booking_id=:id AND created_by=:actor"
                ),
                {"id": booking_id, "actor": g.actor},
            ).mappings().first()
            if not row:
                raise Problem(404, "booking_not_found")
            if row["status"] == "cancelled":
                return jsonify(cancelled=True, replayed=True), 200
            changed = connection.execute(
                text(
                    "UPDATE bookings SET status='cancelled' "
                    "WHERE booking_id=:id AND created_by=:actor AND status='confirmed'"
                ),
                {"id": booking_id, "actor": g.actor},
            )
            if changed.rowcount == 1:
                connection.execute(
                    text("UPDATE slots SET booked=booked-1 WHERE slot_id=:slot AND booked>0"),
                    {"slot": row["slot_id"]},
                )
        return jsonify(cancelled=True, replayed=False), 200

    @app.post("/api/reports")
    def request_report():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) != {"report_date"}:
            raise Problem(400, "invalid_report_request")
        report_date = payload.get("report_date")
        key = request.headers.get("Idempotency-Key", "")
        if not isinstance(report_date, str) or not _REPORT_DATE.fullmatch(report_date):
            raise Problem(400, "invalid_report_date")
        try:
            date.fromisoformat(report_date)
        except ValueError:
            raise Problem(400, "invalid_report_date")
        if not _KEY.fullmatch(key):
            raise Problem(400, "invalid_idempotency_key")
        report_id = uuid.uuid4().hex
        replayed = False
        status = "queued"
        with database().begin() as connection:
            existing = connection.execute(
                text(
                    "SELECT report_id, report_date, status FROM report_jobs "
                    "WHERE requested_by=:actor AND idempotency_key=:key"
                ),
                {"actor": g.actor, "key": key},
            ).mappings().first()
            if existing:
                if existing["report_date"] != report_date:
                    raise Problem(409, "idempotency_key_conflict")
                report_id = existing["report_id"]
                replayed = True
                status = existing["status"]
                should_publish = status in ("queued", "failed")
            else:
                connection.execute(
                    text(
                        "INSERT INTO report_jobs(report_id, requested_by, report_date, status, idempotency_key) "
                        "VALUES (:id, :actor, :date, 'queued', :key)"
                    ),
                    {"id": report_id, "actor": g.actor, "date": report_date, "key": key},
                )
                should_publish = True
        if should_publish:
            message = json.dumps(
                {"schema_version": 1, "report_id": report_id, "report_date": report_date}
            ).encode("utf-8")
            topic = (
                f"projects/{app.config['GOOGLE_CLOUD_PROJECT']}/topics/"
                f"{app.config['REPORT_TOPIC']}"
            )
            try:
                get_publisher().publish(topic, data=message).result(timeout=8)
            except Exception as error:
                print(
                    json.dumps(
                        {
                            "event": "report_publish_failed",
                            "request_id": g.request_id,
                            "report_id": report_id,
                            "error_type": type(error).__name__,
                        }
                    ),
                    flush=True,
                )
                return jsonify(error="report_queue_unavailable", report_id=report_id), 503
        return jsonify(report_id=report_id, status=status, replayed=replayed), 202

    @app.get("/api/reports/<report_id>")
    def report_status(report_id):
        with database().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT report_id, report_date, status, created_at "
                    "FROM report_jobs WHERE report_id=:id AND requested_by=:actor"
                ),
                {"id": report_id, "actor": g.actor},
            ).mappings().first()
        if not row:
            raise Problem(404, "report_not_found")
        return jsonify(report=dict(row))

    @app.get("/api/reports/<report_id>/download")
    def download_report(report_id):
        with database().connect() as connection:
            row = connection.execute(
                text(
                    "SELECT object_name, status FROM report_jobs "
                    "WHERE report_id=:id AND requested_by=:actor"
                ),
                {"id": report_id, "actor": g.actor},
            ).mappings().first()
        if not row:
            raise Problem(404, "report_not_found")
        if row["status"] != "ready" or not row["object_name"]:
            raise Problem(409, "report_not_ready")
        blob = get_storage().bucket(app.config["REPORT_BUCKET"]).blob(row["object_name"])
        content = blob.download_as_bytes()
        return Response(
            content,
            status=200,
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.csv"'},
        )

    return app


app = create_app()
