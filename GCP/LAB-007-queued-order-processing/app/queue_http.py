"""IAM-protected Cloud Run receiver factories. Headers/JSON are not caller auth.
Local HTTP tests exercise contracts only; deploy worker/dispatcher with no public
invoker. All stdout records use an explicit safe field set.
"""
import json
import re
import time
import uuid

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from order_domain import Rejected, parse_push, read_json
from orders import Conflict, IntegrityFailure

EVENT_ERRORS = {
    "invalid_body_size","invalid_json","invalid_json_object","json_too_deep",
    "invalid_identifier","invalid_event_fields","unsupported_schema_version",
    "invalid_fingerprint","invalid_push_fields","unexpected_subscription",
    "invalid_message","conflicting_message_id","conflicting_publish_time",
    "invalid_message_id","invalid_attributes","invalid_event_size","invalid_base64",
    "invalid_delivery_attempt",
}
DISPATCH_REASONS = {
    "batch_limit","budget","empty","claim_unconfirmed","invalid_claim",
    "publish_unconfirmed","stale_claim","release_unconfirmed","finish_unconfirmed",
}


def _base(component, database_health, body_limit):
    if not callable(database_health):
        raise ValueError("database_health_required")
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=body_limit, JSON_SORT_KEYS=True)

    @app.before_request
    def start():
        g.request_id = uuid.uuid4().hex
        g.started = time.monotonic()
        g.outcome = "request_rejected"
        g.identifiers = {}

    @app.after_request
    def finish(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Request-ID"] = g.request_id
        fields = {"component":component,"request_id":g.request_id,
                  "route":request.url_rule.rule if request.url_rule else "unmatched",
                  "status":response.status_code,"outcome":g.outcome,
                  "elapsed_ms":max(0,int((time.monotonic()-g.started)*1000))}
        fields.update(g.identifiers)
        print(json.dumps(fields,sort_keys=True),flush=True)
        return response

    def error(code, status):
        g.outcome = code
        return jsonify(error=code,request_id=g.request_id),status

    @app.errorhandler(Exception)
    def safe_error(exc):
        if isinstance(exc,HTTPException):
            status = exc.code if exc.code in (400,404,405,413,415) else 503
            return error("request_rejected" if status < 500 else "dependency_unavailable",status)
        return error("dependency_unavailable",503)

    @app.get("/livez")
    def live():
        g.outcome = "live"
        return jsonify(status="live")

    @app.get("/healthz")
    def health():
        try:
            database_health()
        except Exception:
            return error("metadata_unavailable",503)
        g.outcome = "healthy"
        return jsonify(status="healthy")

    return app,error


def create_worker(repository, expected_subscription, *, database_health, fault_mode="off"):
    if fault_mode not in ("off", "retryable_503"):
        raise ValueError("invalid_worker_fault_mode")
    if not isinstance(expected_subscription,str) or not re.fullmatch(
            r"projects/[a-z0-9-]{6,63}/subscriptions/[A-Za-z][A-Za-z0-9._~-]{2,254}",
            expected_subscription):
        raise ValueError("invalid_subscription_configuration")
    app,error = _base("lab007-worker",database_health,65536)

    @app.post("/events/orders")
    def process():
        if request.mimetype != "application/json":
            return error("invalid_content_type",400)
        try:
            delivery = parse_push(request.get_data(cache=False),expected_subscription)
        except Rejected as exc:
            return error(str(exc) if str(exc) in EVENT_ERRORS else "invalid_event",400)
        g.identifiers = {"event_id":delivery.event.event_id,
                         "order_id":delivery.event.order_id,
                         "message_id":delivery.message_id}
        if fault_mode == "retryable_503":
            return error("lab_fault_retryable", 503)
        try:
            result = repository.process(delivery.event)
        except Conflict as exc:
            code = str(exc)
            return error(code if code in ("unknown_order","event_binding_mismatch")
                         else "event_conflict",400)
        except IntegrityFailure:
            return error("integrity_unavailable",503)
        state,disposition = result.get("state"),result.get("disposition")
        if state not in ("confirmed","rejected") or disposition not in ("processed","duplicate"):
            return error("outcome_unconfirmed",503)
        g.outcome = state+"_"+disposition
        return "",204

    return app


def create_dispatcher(dispatcher, *, database_health):
    app,error = _base("lab007-dispatcher",database_health,1024)

    @app.post("/internal/outbox/drain")
    def drain():
        if request.mimetype != "application/json":
            return error("invalid_content_type",400)
        body = request.get_data(cache=False)
        try:
            if body and read_json(body,limit=1024) != {}:
                return error("invalid_drain_request",400)
        except Rejected:
            return error("invalid_drain_request",400)
        result = dispatcher.drain()
        reason,status = result.get("reason"),result.get("status")
        if reason not in DISPATCH_REASONS or status not in (200,503):
            return error("outcome_unconfirmed",503)
        summary = {"reason":reason,"request_id":g.request_id}
        for field in ("claimed","publish_acks","finished","exhausted","integrity_blocked"):
            value=result.get(field)
            if type(value) is not int or not 0 <= value <= 20:
                return error("outcome_unconfirmed",503)
            summary[field]=value
        # Per-event correlation excludes tokens, payloads and arbitrary strings.
        g.identifiers.update({field:summary[field] for field in
                              ("claimed","publish_acks","finished","exhausted","integrity_blocked")})
        records=result.get("events",[])
        if not isinstance(records,list) or len(records)>20:
            return error("outcome_unconfirmed",503)
        for record in records:
            if not isinstance(record,dict):
                return error("outcome_unconfirmed",503)
            fields={"component":"lab007-dispatch-event","request_id":g.request_id}
            for key in ("event_id","order_id"):
                value=record.get(key)
                if isinstance(value,str) and re.fullmatch(r"[a-f0-9]{32}",value):
                    fields[key]=value
            for key,ceiling in (("epoch",2),("attempts",10)):
                value=record.get(key)
                if type(value) is int and 0 <= value <= ceiling:
                    fields[key]=value
            for key,allowed in (
                    ("outcome",{"exhausted","integrity_blocked"}),
                    ("publish_ack",{"accepted","unconfirmed"}),
                    ("finish",{"pending","stale","unconfirmed","published"})):
                if record.get(key) in allowed:
                    fields[key]=record[key]
            print(json.dumps(fields,sort_keys=True),flush=True)
        g.outcome=reason
        return jsonify(summary),status

    return app
