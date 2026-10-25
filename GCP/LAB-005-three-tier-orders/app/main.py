"""Orders API only; static UI belongs to the separate Web tier."""
from datetime import timedelta
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
import uuid
from flask import Flask,g,jsonify,request,session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash
from database import create_pool
from orders import Orders,Problem

def create_app(engine=None,auth_config=None):
    auth=auth_config or json.loads(Path(os.environ['AUTH_CONFIG_FILE']).read_text())
    users=auth.get('users',{})
    if len(auth.get('session_key',''))<64 or not users:
        raise ValueError('Expected generated session key and hashed demo users')
    for name,user in users.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}',name) or user.get('role') not in ('customer','operator') or not user.get('password_hash'):
            raise ValueError('Invalid demo authentication configuration')
    version=os.environ.get('APP_VERSION','v1')
    if version not in ('v1','v2'):
        raise ValueError('Unsupported release version; startup must fail rather than serve unknown code')
    if os.environ.get('APP_LOCAL_TEST')=='1' and os.environ.get('DEPLOYMENT_TARGET')=='gce':
        raise ValueError('Insecure test cookies are forbidden on deployed GCE')
    app=Flask(__name__,static_folder=None)
    app.config.update(SECRET_KEY=auth['session_key'],SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=os.environ.get('APP_LOCAL_TEST')!='1',SESSION_COOKIE_SAMESITE='Lax',
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=10),MAX_CONTENT_LENGTH=4096)
    pool=engine if engine is not None else create_pool()
    domain=Orders(pool)
    app.extensions['db']=pool
    app.extensions['orders']=domain
    backend=socket.gethostname()
    dummy=next(iter(users.values()))['password_hash']

    def owner():
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
            supplied=request.headers.get('X-CSRF-Token','')
            expected=session.get('csrf','')
            if not expected or not hmac.compare_digest(expected.encode(),supplied.encode()):
                raise Problem(403,'csrf_required')

    @app.after_request
    def metadata(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Request-ID']=getattr(g,'request_id','')
        response.headers['X-Backend-ID']=backend
        response.headers['X-Content-Type-Options']='nosniff'
        print(json.dumps({'event':'http_request','request_id':getattr(g,'request_id',''),
            'method':request.method,'path':request.path,'status':response.status_code,
            'backend':backend,'version':version,
            'duration_ms':round((time.monotonic()-getattr(g,'started',time.monotonic()))*1000,2)}),flush=True)
        return response

    @app.errorhandler(Problem)
    def expected_error(exc):
        return jsonify(error=exc.error,request_id=getattr(g,'request_id','')),exc.status

    @app.errorhandler(SQLAlchemyError)
    def dependency_error(exc):
        print(json.dumps({'event':'database_unavailable','request_id':getattr(g,'request_id',''),
                          'error_type':type(exc).__name__,'backend':backend}),flush=True)
        return jsonify(error='database_unavailable',request_id=getattr(g,'request_id','')),503

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name.lower().replace(' ','_'),request_id=getattr(g,'request_id','')),exc.code

    @app.get('/livez')
    def live():
        return jsonify(alive=True,version=version,backend=backend)

    @app.get('/healthz')
    def health():
        with pool.connect() as conn:
            conn.execute(text('SELECT sku FROM products LIMIT 1'))
        return jsonify(ready=True,version=version,backend=backend)

    @app.get('/api/session')
    def current_session():
        session.setdefault('csrf',secrets.token_urlsafe(24))
        username=session.get('username')
        return jsonify(username=username,role=users.get(username,{}).get('role'),
                       csrf=session['csrf'],version=version,backend=backend)

    @app.post('/api/login')
    def login():
        data=body()
        username,password=data.get('username'),data.get('password')
        if not isinstance(username,str) or not isinstance(password,str) or len(password)>256 or len(username)>32:
            raise Problem(400,'invalid_login')
        user=users.get(username)
        good=check_password_hash(user['password_hash'] if user else dummy,password)
        if not user or not good:
            raise Problem(401,'invalid_credentials')
        session.clear()
        session.permanent=True
        session.update(username=username,csrf=secrets.token_urlsafe(24))
        return jsonify(username=username,role=user['role'],csrf=session['csrf'],version=version,backend=backend)

    @app.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(logged_out=True)

    @app.get('/api/products')
    def products():
        owner()
        rows=domain.products()
        if version=='v2':
            for row in rows:
                row['low_stock']=row['available']<=2
        return jsonify(products=rows,version=version,backend=backend)

    @app.get('/api/orders')
    def own_orders():
        return jsonify(orders=domain.list(owner()),version=version,backend=backend)

    @app.get('/api/orders/<uuid:order_id>')
    def get_order(order_id):
        return jsonify(order=domain.get(owner(),order_id),version=version,backend=backend)

    @app.post('/api/orders')
    def place():
        username=owner()
        data=body()
        if set(data)!={'items'}:
            raise Problem(400,'invalid_order')
        order,replayed=domain.place(username,request.headers.get('Idempotency-Key'),data['items'])
        return jsonify(order=order,replayed=replayed,version=version,backend=backend),200 if replayed else 201

    @app.post('/api/orders/<uuid:order_id>/cancel')
    def cancel(order_id):
        order,replayed=domain.cancel(owner(),order_id)
        return jsonify(order=order,replayed=replayed,version=version,backend=backend)

    @app.get('/api/operator/orders')
    def operator_orders():
        username=owner()
        if users[username]['role']!='operator':
            raise Problem(403,'operator_required')
        with pool.connect() as conn:
            rows=conn.execute(text('SELECT id::text,username,status,total_satang,created_at::text FROM orders ORDER BY created_at DESC,id LIMIT 100')).mappings()
            return jsonify(orders=[dict(row) for row in rows],version=version,backend=backend)

    return app
