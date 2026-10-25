"""Portal API with session/CSRF/owner boundaries. No credentials in responses/logs."""
from datetime import datetime, timedelta, timezone
import hmac
import json
import secrets
import uuid
from flask import Flask, g, jsonify, request, session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash
from job_state import Conflict


def create_app(jobs, access, auth, *, clock=None, metadata_health=None,
               limits=(1048576, 10000), retry_dispatch=None, emit=None):
    key = auth.get("session_key")
    users = auth.get("users")
    if (not isinstance(key, str) or len(key) < 64 or not isinstance(users, dict) or
            not users or limits not in ((1048576, 10000), (5242880, 50000))):
        raise ValueError("invalid_portal_configuration")
    for name, user in users.items():
        if (not isinstance(name, str) or not isinstance(user, dict) or
                user.get("role") not in ("customer", "operator") or
                not isinstance(user.get("password_hash"), str)):
            raise ValueError("invalid_user_configuration")
    app = Flask(__name__, static_folder="static")
    app.config.update(SECRET_KEY=key, MAX_CONTENT_LENGTH=4096,
                      SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(minutes=30))
    clock = clock or (lambda: datetime.now(timezone.utc))
    emit = emit or (lambda record: print(json.dumps(record, sort_keys=True), flush=True))
    dummy_hash = generate_password_hash(secrets.token_hex(32))

    def csrf():
        if "csrf" not in session:
            session["csrf"] = secrets.token_hex(32)
            session.permanent = True
        return session["csrf"]

    def identity():
        name = session.get("user")
        return name if name in users else None

    def body(required):
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or set(value) != set(required):
            raise ValueError("invalid_input")
        return value

    @app.before_request
    def guard():
        g.request_id = uuid.uuid4().hex
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            supplied = request.headers.get("X-CSRF-Token", "")
            expected = session.get("csrf")
            if (not isinstance(expected, str) or not isinstance(supplied, str) or
                    not hmac.compare_digest(supplied, expected)):
                return jsonify(error="csrf_required"), 403
        if (request.path.startswith("/api/") and
                request.path not in ("/api/session", "/api/login") and
                identity() is None):
            return jsonify(error="login_required"), 401

    @app.after_request
    def complete(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = g.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self' https://storage.googleapis.com; "
            "frame-ancestors 'none'; base-uri 'none'")
        response.headers["Referrer-Policy"] = "no-referrer"
        emit({"event": "portal_http", "request_id": g.request_id,
              "endpoint": request.endpoint, "status": response.status_code})
        return response

    @app.errorhandler(Conflict)
    def conflict(_):
        return jsonify(error="job_conflict"), 409

    @app.errorhandler(ValueError)
    def invalid(_):
        return jsonify(error="invalid_input"), 400

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error="request_rejected"), exc.code

    @app.errorhandler(Exception)
    def unavailable(_):
        return jsonify(error="temporary_dependency_failure"), 503

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/session")
    def status():
        name = identity()
        return jsonify(user=name, role=users[name]["role"] if name else None,
                       csrf=csrf(), max_bytes=limits[0], max_rows=limits[1])

    @app.post("/api/login")
    def login():
        data = body(("username", "password"))
        name, password = data["username"], data["password"]
        if (not isinstance(name, str) or len(name) > 64 or
                not isinstance(password, str) or not 1 <= len(password) <= 256):
            raise ValueError("invalid_login")
        user = users.get(name)
        valid = check_password_hash(user["password_hash"] if user else dummy_hash,
                                    password)
        if not user or not valid:
            return jsonify(error="invalid_login"), 401
        session.clear()
        session["user"] = name
        session.permanent = True
        return jsonify(user=name, role=user["role"], csrf=csrf())

    @app.post("/api/logout")
    def logout():
        session.clear()
        return jsonify(user=None, csrf=csrf())

    @app.post("/api/jobs")
    def create_job():
        data = body(("display_name",))
        if users[identity()]["role"] != "customer":
            return jsonify(error="customer_required"), 403
        result = jobs.create(identity(), request.headers.get("Idempotency-Key", ""),
                             data["display_name"], max_bytes=limits[0], max_rows=limits[1])
        return jsonify(job_id=result["job"]["job_id"], replayed=result["replayed"]), (
            200 if result["replayed"] else 201)

    def public_job(item):
        fields = ("job_id", "display_name", "state", "safe_reason", "processor_version",
                  "max_bytes", "max_rows", "attempt_epoch", "attempt_count")
        result = {key: item[key] for key in fields if key in item}
        if clock() >= item["expires_at"]:
            result["state"] = "expired"
        result["expires_at"] = item["expires_at"].isoformat()
        return result

    @app.get("/api/jobs")
    def list_jobs():
        if (set(request.args) - {"limit", "cursor"} or
                any(len(request.args.getlist(key)) != 1 for key in request.args)):
            raise ValueError("invalid_query")
        raw_limit = request.args.get("limit", "20")
        if not raw_limit.isascii() or not raw_limit.isdigit():
            raise ValueError("invalid_limit")
        limit = int(raw_limit)
        if not 1 <= limit <= 20:
            raise ValueError("invalid_limit")
        result = jobs.list_owned(identity(), limit=limit,
                                 cursor=request.args.get("cursor"))
        return jsonify(jobs=[public_job(item) for item in result["jobs"]],
                       next_cursor=result["next_cursor"])

    @app.get("/api/jobs/<job_id>")
    def read_job(job_id):
        try:
            item = jobs.read_owned(job_id, identity())
        except KeyError:
            return jsonify(error="job_not_found"), 404
        return jsonify(public_job(item))

    def operator_allowed():
        return users[identity()]["role"] == "operator"

    @app.get("/api/operator/jobs")
    def operator_list():
        if not operator_allowed():
            return jsonify(error="operator_required"), 403
        if (set(request.args) - {"limit", "cursor"} or
                any(len(request.args.getlist(key)) != 1 for key in request.args)):
            raise ValueError("invalid_query")
        raw_limit = request.args.get("limit", "20")
        if not raw_limit.isascii() or not raw_limit.isdigit():
            raise ValueError("invalid_limit")
        limit = int(raw_limit)
        if not 1 <= limit <= 20:
            raise ValueError("invalid_limit")
        result = jobs.list_operator(limit=limit, cursor=request.args.get("cursor"))
        return jsonify(jobs=[public_job(item) for item in result["jobs"]],
                       next_cursor=result["next_cursor"])

    @app.get("/api/operator/jobs/<job_id>")
    def operator_read(job_id):
        if not operator_allowed():
            return jsonify(error="operator_required"), 403
        try:
            item = jobs.read_operator(job_id)
        except KeyError:
            return jsonify(error="job_not_found"), 404
        result = public_job(item)
        result["history"] = [
            {"time": entry["time"].isoformat(), "state": entry["state"],
             "epoch": entry["epoch"], "attempt": entry["attempt"],
             "reason": entry.get("reason")}
            for entry in item.get("history", [])[-100:]]
        result["history_truncated"] = item.get("history_truncated", False)
        return jsonify(result)

    @app.post("/api/operator/jobs/<job_id>/retry")
    def operator_retry(job_id):
        if not operator_allowed():
            return jsonify(error="operator_required"), 403
        data = body(("request_key",))
        if retry_dispatch is None:
            return jsonify(error="retry_unavailable"), 503
        try:
            prepared = jobs.prepare_operator_retry(job_id, identity(), data["request_key"])
        except KeyError:
            return jsonify(error="job_not_found"), 404
        # The epoch is durable before network I/O. Unknown delivery is not business failure.
        delivery = "unconfirmed"
        try:
            if retry_dispatch(job_id, prepared["epoch"]):
                delivery = "acknowledged"
        except Exception:
            pass
        return jsonify(job_id=job_id, epoch=prepared["epoch"],
                       replayed=prepared["replayed"], dispatch=delivery), 202

    @app.post("/api/jobs/<job_id>/upload-policy")
    def upload(job_id):
        body(())
        try:
            return jsonify(access.upload_policy(job_id, identity()))
        except KeyError:
            return jsonify(error="job_not_found"), 404

    @app.post("/api/jobs/<job_id>/download-link")
    def download(job_id):
        body(())
        try:
            return jsonify(access.download_link(job_id, identity()))
        except KeyError:
            return jsonify(error="job_not_found"), 404

    @app.get("/livez")
    def live():
        return jsonify(alive=True, tier="portal")

    @app.get("/healthz")
    def health():
        if metadata_health:
            metadata_health()
        return jsonify(ready=True, tier="portal")

    return app
