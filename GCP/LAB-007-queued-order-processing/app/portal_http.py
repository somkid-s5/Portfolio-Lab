"""Same-origin Portal API. Sessions identify users; DB role is service-level."""
from datetime import datetime,timedelta,timezone
import hmac
import json
import re
import secrets
import uuid

from flask import Flask,g,jsonify,request,session
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash,generate_password_hash

from auth_config import HASH_METHOD,validate_auth
from order_domain import Rejected,create_order,identifier,read_json
from orders import Conflict,IntegrityFailure
from pagination import decode_cursor
from replay import replay_request


def create_app(orders,outbox,auth,*,database_health,emit=None,replay=None):
    auth=validate_auth(auth)
    users=auth["users"]
    if not callable(database_health):
        raise ValueError("database_health_required")
    app=Flask(__name__,static_folder="static")
    app.config.update(SECRET_KEY=auth["session_key"],MAX_CONTENT_LENGTH=4096,
        SESSION_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),SESSION_REFRESH_EACH_REQUEST=False)
    dummy_hash=generate_password_hash(secrets.token_hex(32),method=HASH_METHOD,salt_length=16)
    emit=emit or (lambda record:print(json.dumps(record,sort_keys=True),flush=True))

    def csrf():
        if "csrf" not in session:
            session["csrf"]=secrets.token_hex(32)
            session.permanent=True
        return session["csrf"]

    def identity():
        value=session.get("user")
        return value if isinstance(value,str) and value in users else None

    def role():
        name=identity()
        return users[name]["role"] if name else None

    def error(code,status):
        return jsonify(error=code,request_id=g.request_id),status

    def body(fields):
        if request.mimetype!="application/json":
            raise Rejected("invalid_content_type")
        value=read_json(request.get_data(cache=False))
        if set(value)!=set(fields):
            raise Rejected("invalid_input")
        return value

    @app.before_request
    def guard():
        g.request_id=uuid.uuid4().hex
        g.identifiers={}
        if len(request.query_string)>1024:
            return error("invalid_query",400)
        if request.method in ("POST","PUT","PATCH","DELETE"):
            supplied=request.headers.get("X-CSRF-Token","")
            expected=session.get("csrf")
            if (not isinstance(expected,str) or not re.fullmatch(r"[a-f0-9]{64}",expected) or
                    not re.fullmatch(r"[a-f0-9]{64}",supplied) or
                    not hmac.compare_digest(supplied,expected)):
                return error("csrf_required",403)
        if (request.path.startswith("/api/") and
                request.path not in ("/api/session","/api/login") and identity() is None):
            return error("login_required",401)

    @app.after_request
    def complete(response):
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Request-ID"]=g.request_id
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Content-Security-Policy"]=(
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'")
        response.headers["Referrer-Policy"]="no-referrer"
        emit({"component":"lab007-portal","request_id":g.request_id,
              "endpoint":request.endpoint,"status":response.status_code,**g.identifiers})
        return response

    @app.errorhandler(Conflict)
    def conflict(exc):
        if request.endpoint=="operator_replay":
            safe={"replay_key_conflict","unknown_event","dispatch_in_flight","replay_budget_exhausted"}
            code=str(exc)
            return error(code if code in safe else "replay_conflict",409)
        return error("order_conflict",409)

    @app.errorhandler(IntegrityFailure)
    def integrity(_):
        return error("temporary_dependency_failure",503)

    @app.errorhandler(Rejected)
    @app.errorhandler(ValueError)
    def invalid(_):
        return error("invalid_input",400)

    @app.errorhandler(HTTPException)
    def http_error(exc):
        status=exc.code if exc.code and 400<=exc.code<500 else 503
        return error("request_rejected" if status<500 else "temporary_dependency_failure",status)

    @app.errorhandler(Exception)
    def unavailable(_):
        return error("temporary_dependency_failure",503)

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/session")
    def current_session():
        return jsonify(user=identity(),role=role(),csrf=csrf(),max_items=2,max_quantity=3)

    @app.post("/api/login")
    def login():
        data=body(("username","password"))
        name,password=data["username"],data["password"]
        if (not isinstance(name,str) or not 1<=len(name)<=64 or
                not isinstance(password,str) or not 1<=len(password)<=256):
            raise Rejected("invalid_login")
        user=users.get(name)
        matched=check_password_hash(user["password_hash"] if user else dummy_hash,password)
        if not user or not matched:
            return error("invalid_login",401)
        session.clear()
        session["user"]=name
        session.permanent=True
        return jsonify(user=name,role=user["role"],csrf=csrf())

    @app.post("/api/logout")
    def logout():
        body(())
        session.clear()
        return jsonify(user=None,role=None,csrf=csrf())

    def project(item,fields):
        result={}
        for field in fields:
            if field not in item:
                continue
            value=item[field]
            if isinstance(value,datetime):
                if value.tzinfo is None:
                    raise IntegrityFailure("invalid_timestamp")
                value=value.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
            result[field]=value
        return result

    def public_order(item):
        result=project(item,("order_id","owner","state","safe_reason","total_satang",
                             "created_at","finished_at"))
        if "items" in item:
            if not isinstance(item["items"],list) or not 1<=len(item["items"])<=2:
                raise IntegrityFailure("invalid_order_items")
            result["items"]=[project(i,("sku","quantity","unit_price_satang")) for i in item["items"]]
        if "dispatch" in item:
            if not isinstance(item["dispatch"],dict):
                raise IntegrityFailure("missing_outbox")
            result["dispatch"]=project(item["dispatch"],("event_id","state","epoch",
                "attempts","last_outcome","published_at"))
        return result

    def public_outbox(item):
        return project(item,("event_id","order_id","state","epoch","attempts","last_outcome",
            "created_at","published_at","lease_until","payload_sha256","order_state",
            "owner","order_fingerprint"))

    def query():
        if (set(request.args)-{"limit","cursor"} or
                any(len(request.args.getlist(k))!=1 for k in request.args)):
            raise Rejected("invalid_query")
        value=request.args.get("limit","20")
        if not re.fullmatch(r"[0-9]{1,2}",value) or not 1<=int(value)<=20:
            raise Rejected("invalid_limit")
        cursor=request.args.get("cursor")
        decode_cursor(cursor)
        return int(value),cursor

    def public_page(value,limit,projection):
        items=value.get("items")
        if not isinstance(items,list) or len(items)>limit:
            raise IntegrityFailure("invalid_page")
        next_cursor=value.get("next_cursor")
        try:
            decode_cursor(next_cursor)
        except Rejected:
            raise IntegrityFailure("invalid_page") from None
        return {"items":[projection(item) for item in items],"next_cursor":next_cursor}

    @app.get("/api/catalog")
    def catalog():
        values=orders.catalog()
        if not isinstance(values,list) or len(values)>50:
            raise IntegrityFailure("invalid_catalog")
        return jsonify(items=[project(i,("sku","unit_price_satang","available")) for i in values])

    @app.post("/api/orders")
    def new_order():
        if role()!="customer":
            return error("customer_required",403)
        if request.mimetype!="application/json":
            raise Rejected("invalid_content_type")
        raw=request.get_data(cache=False)
        create_order(raw)  # Perimeter validation; repository independently enforces the same contract.
        result=orders.create(identity(),raw)
        g.identifiers["order_id"]=identifier(result["order_id"])
        return jsonify(order_id=result["order_id"],state=result["state"],
                       replayed=result["replayed"]),200 if result["replayed"] else 202

    @app.get("/api/orders")
    def list_orders():
        limit,cursor=query()
        return jsonify(public_page(orders.list_owned(identity(),limit=limit,cursor=cursor),
                                   limit,public_order))

    @app.get("/api/orders/<order_id>")
    def order_detail(order_id):
        try:
            identifier(order_id)
        except Rejected:
            return error("order_not_found",404)
        value=orders.read_owned(identity(),order_id)
        if value is None:
            return error("order_not_found",404)
        g.identifiers["order_id"]=order_id
        return jsonify(public_order(value))

    @app.get("/api/operator/orders")
    def operator_orders():
        if role()!="operator":
            return error("operator_required",403)
        limit,cursor=query()
        return jsonify(public_page(orders.list_operator(limit=limit,cursor=cursor),
                                   limit,public_order))

    @app.get("/api/operator/outbox")
    def operator_outbox():
        if role()!="operator":
            return error("operator_required",403)
        limit,cursor=query()
        return jsonify(public_page(outbox.list_operator(limit=limit,cursor=cursor),
                                   limit,public_outbox))

    @app.get("/api/operator/outbox/<event_id>")
    def operator_event(event_id):
        if role()!="operator":
            return error("operator_required",403)
        try:
            identifier(event_id)
        except Rejected:
            return error("event_not_found",404)
        value=outbox.read_operator(event_id)
        if value is None:
            return error("event_not_found",404)
        g.identifiers["event_id"]=event_id
        return jsonify(public_outbox(value))

    @app.get("/api/operator/outbox/<event_id>/verification")
    def operator_verification(event_id):
        if role()!="operator":
            return error("operator_required",403)
        identifier(event_id)
        if replay is None:
            return error("temporary_dependency_failure",503)
        value=replay.verify(event_id)
        if (value.get("event_id")!=event_id or
                type(value.get("terminal_verified")) is not bool or
                value.get("order_state") not in ("accepted","confirmed","rejected") or
                value["terminal_verified"]!=(value["order_state"] in ("confirmed","rejected"))):
            raise IntegrityFailure("invalid_verification_result")
        identifier(value.get("order_id"))
        for field in ("order_fingerprint","payload_sha256"):
            if not isinstance(value.get(field),str) or not re.fullmatch(r"[a-f0-9]{64}",value[field]):
                raise IntegrityFailure("invalid_verification_result")
        g.identifiers["event_id"]=event_id
        return jsonify(project(value,("event_id","order_id","order_fingerprint","payload_sha256",
                                      "order_state","terminal_verified")))

    @app.post("/api/operator/outbox/<event_id>/replay")
    def operator_replay(event_id):
        if role()!="operator":
            return error("operator_required",403)
        identifier(event_id)
        if request.mimetype!="application/json":
            raise Rejected("invalid_content_type")
        raw=request.get_data(cache=False)
        replay_request(raw)
        if replay is None:
            return error("temporary_dependency_failure",503)
        result=replay.prepare(identity(),event_id,raw)
        if (result.get("event_id")!=event_id or result.get("outcome") not in ("prepared","already_resolved")
                or type(result.get("epoch")) is not int or not 0<=result["epoch"]<=2
                or type(result.get("replayed")) is not bool):
            raise IntegrityFailure("invalid_replay_result")
        g.identifiers["event_id"]=event_id
        return jsonify(project(result,("event_id","source_digest","reason","epoch","outcome","replayed")))

    @app.get("/livez")
    def live():
        return jsonify(status="live")

    @app.get("/healthz")
    def health():
        database_health()
        return jsonify(status="healthy")

    return app
