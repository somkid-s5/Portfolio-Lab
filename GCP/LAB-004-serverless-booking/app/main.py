"""Sandbox Booking UI/API. App identity is separate from Cloud Run IAM."""
from datetime import timedelta
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
import uuid
from flask import Flask, g, jsonify, request, session, render_template
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as PoolTimeout
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash
from database import create_pool

class Problem(Exception):
    def __init__(self,status,error):
        self.status,self.error=status,error

def create_app(engine=None,auth_config=None):
    auth=auth_config or json.loads(Path(os.environ['AUTH_CONFIG_FILE']).read_text())
    if len(auth.get('session_key',''))<64 or not auth.get('users'):
        raise ValueError('Expected generated session key and hashed demo users')
    local=os.environ.get('APP_LOCAL_TEST')=='1'
    if local and (os.environ.get('K_SERVICE') or os.environ.get('CLOUD_RUN_JOB')):
        raise ValueError('Insecure test cookies are not allowed on Cloud Run')
    app=Flask(__name__)
    app.config.update(SECRET_KEY=auth['session_key'],SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=not local,SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=10),MAX_CONTENT_LENGTH=4096)
    app.extensions['db']=engine if engine is not None else create_pool()
    version=os.environ.get('APP_VERSION','v1')
    users=auth['users']
    dummy=next(iter(users.values()))['password_hash']

    def db():
        return app.extensions['db']

    def signed_in():
        username=session.get('username')
        if username not in users:
            raise Problem(401,'login_required')
        return username

    def body():
        data=request.get_json(silent=True)
        if not isinstance(data,dict):
            raise Problem(400,'invalid_json')
        return data

    @app.before_request
    def context():
        g.request_id=uuid.uuid4().hex
        g.started=time.monotonic()
        if request.method in ('POST','PUT','PATCH','DELETE'):
            expected=session.get('csrf','')
            supplied=request.headers.get('X-CSRF-Token','')
            if not expected or not hmac.compare_digest(expected.encode(),supplied.encode()):
                raise Problem(403,'csrf_required')

    @app.after_request
    def response_meta(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Request-ID']=getattr(g,'request_id','')
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'"
        print(json.dumps({'event':'http_request','request_id':getattr(g,'request_id',''),
            'path':request.path,'method':request.method,'status':response.status_code,
            'revision':os.environ.get('K_REVISION',version),
            'duration_ms':round((time.monotonic()-getattr(g,'started',time.monotonic()))*1000,2)}),flush=True)
        return response

    @app.errorhandler(Problem)
    def expected_error(exc):
        return jsonify(error=exc.error,request_id=getattr(g,'request_id','')),exc.status

    @app.errorhandler(SQLAlchemyError)
    def database_error(exc):
        print(json.dumps({'event':'database_unavailable','request_id':getattr(g,'request_id',''),
                          'error_type':type(exc).__name__}),flush=True)
        return jsonify(error='database_unavailable',request_id=getattr(g,'request_id','')),503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name.lower().replace(' ','_'),request_id=getattr(g,'request_id','')),exc.code

    @app.get('/')
    def home():
        return render_template('index.html',version=version)

    @app.get('/livez')
    def live():
        return jsonify(alive=True,version=version)

    @app.get('/healthz')
    def health():
        with db().connect() as conn:
            conn.execute(text('SELECT id FROM slots LIMIT 1'))
        return jsonify(ready=True,version=version)

    @app.get('/api/session')
    def current_session():
        session.setdefault('csrf',secrets.token_urlsafe(24))
        username=session.get('username')
        return jsonify(username=username,role=users.get(username,{}).get('role'),
                       csrf=session['csrf'],version=version)

    @app.post('/api/login')
    def login():
        data=body()
        username,password=data.get('username'),data.get('password')
        if not isinstance(username,str) or not isinstance(password,str) or len(password)>256:
            raise Problem(400,'invalid_login')
        user=users.get(username)
        good=check_password_hash(user['password_hash'] if user else dummy,password)
        if not user or not good:
            raise Problem(401,'invalid_credentials')
        session.clear()
        session.permanent=True
        session.update(username=username,csrf=secrets.token_urlsafe(24))
        return jsonify(username=username,role=user['role'],csrf=session['csrf'],version=version)

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(logged_out=True)

    @app.get('/api/slots')
    def slots():
        signed_in()
        with db().connect() as conn:
            rows=conn.execute(text('SELECT id,label,capacity,booked FROM slots ORDER BY id')).mappings().all()
        return jsonify(slots=[dict(row) for row in rows],version=version)

    @app.get('/api/bookings')
    def own_bookings():
        username=signed_in()
        with db().connect() as conn:
            rows=conn.execute(text("SELECT id::text,slot_id,status,created_at::text FROM bookings WHERE username=:u ORDER BY created_at DESC LIMIT 100"),{'u':username}).mappings().all()
        return jsonify(bookings=[dict(row) for row in rows],version=version)

    @app.get('/api/bookings/<uuid:booking_id>')
    def booking(booking_id):
        username=signed_in()
        with db().connect() as conn:
            row=conn.execute(text("SELECT id::text,slot_id,status FROM bookings WHERE id=CAST(:id AS uuid) AND username=:u"),
                             {'id':str(booking_id),'u':username}).mappings().first()
        if not row:
            raise Problem(404,'booking_not_found')
        return jsonify(booking=dict(row),version=version)

    @app.get('/api/operator/bookings')
    def operator_bookings():
        username=signed_in()
        if users[username]['role']!='operator':
            raise Problem(403,'operator_required')
        with db().connect() as conn:
            rows=conn.execute(text("SELECT id::text,username,slot_id,status FROM bookings ORDER BY created_at DESC LIMIT 100")).mappings().all()
        return jsonify(bookings=[dict(row) for row in rows],version=version)

    @app.post('/api/bookings')
    def reserve():
        username=signed_in()
        data=body()
        slot,key=data.get('slot_id'),request.headers.get('Idempotency-Key','')
        if type(slot) is not int or not re.fullmatch('[A-Za-z0-9_-]{8,80}',key):
            raise Problem(400,'invalid_booking')
        with db().begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:k,0))'),{'k':username+':'+key})
            old=conn.execute(text('SELECT id::text,slot_id,status FROM bookings WHERE username=:u AND request_key=:k'),
                             {'u':username,'k':key}).mappings().first()
            if old:
                if old['slot_id']!=slot:
                    raise Problem(409,'idempotency_conflict')
                return jsonify(booking=dict(old),replayed=True,version=version),200
            row=conn.execute(text('SELECT id,capacity,booked FROM slots WHERE id=:s FOR UPDATE'),{'s':slot}).mappings().first()
            if not row:
                raise Problem(404,'slot_not_found')
            if conn.execute(text("SELECT 1 FROM bookings WHERE username=:u AND slot_id=:s AND status='confirmed'"),
                            {'u':username,'s':slot}).first():
                raise Problem(409,'already_booked')
            if row['booked']>=row['capacity']:
                raise Problem(409,'slot_full')
            booking_id=str(uuid.uuid4())
            conn.execute(text('UPDATE slots SET booked=booked+1 WHERE id=:s'),{'s':slot})
            conn.execute(text("INSERT INTO bookings(id,username,slot_id,request_key,status) VALUES(CAST(:id AS uuid),:u,:s,:k,'confirmed')"),
                         {'id':booking_id,'u':username,'s':slot,'k':key})
            conn.execute(text("INSERT INTO booking_events(booking_id,event,actor) VALUES(CAST(:id AS uuid),'reserved',:u)"),
                         {'id':booking_id,'u':username})
        return jsonify(booking={'id':booking_id,'slot_id':slot,'status':'confirmed'},replayed=False,version=version),201

    @app.post('/api/bookings/<uuid:booking_id>/cancel')
    def cancel(booking_id):
        username=signed_in()
        with db().begin() as conn:
            original=conn.execute(text('SELECT slot_id FROM bookings WHERE id=CAST(:id AS uuid) AND username=:u'),
                                  {'id':str(booking_id),'u':username}).first()
            if not original:
                raise Problem(404,'booking_not_found')
            slot=original[0]
            conn.execute(text('SELECT id FROM slots WHERE id=:s FOR UPDATE'),{'s':slot})
            row=conn.execute(text('SELECT status FROM bookings WHERE id=CAST(:id AS uuid) FOR UPDATE'),{'id':str(booking_id)}).first()
            if row[0]=='cancelled':
                return jsonify(cancelled=True,replayed=True,version=version)
            conn.execute(text("UPDATE bookings SET status='cancelled',cancelled_at=now() WHERE id=CAST(:id AS uuid)"),
                         {'id':str(booking_id)})
            conn.execute(text('UPDATE slots SET booked=booked-1 WHERE id=:s'),{'s':slot})
            conn.execute(text("INSERT INTO booking_events(booking_id,event,actor) VALUES(CAST(:id AS uuid),'cancelled',:u)"),
                         {'id':str(booking_id),'u':username})
        return jsonify(cancelled=True,replayed=False,version=version)

    return app
