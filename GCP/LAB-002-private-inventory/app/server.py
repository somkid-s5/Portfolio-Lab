"""Private Inventory demo. Use only synthetic data on a sandbox private network."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import psycopg2
from psycopg2.extras import RealDictCursor

BACKEND = os.environ.get('BACKEND_ID', socket.gethostname())
TOKENS = json.loads(Path(os.environ['TOKEN_HASH_FILE']).read_text())
if set(TOKENS) != {'reader', 'operator'} or any(not re.fullmatch('[a-f0-9]{64}', v) for v in TOKENS.values()):
    raise ValueError('Expected reader/operator SHA256 token hashes')
SLOTS = threading.BoundedSemaphore(8)
PAGE = (Path(__file__).with_name('index.html')).read_bytes()

def database():
    return psycopg2.connect(connect_timeout=3,
        options='-c statement_timeout=3000 -c lock_timeout=2000',
        application_name='lab002-inventory')

def role_for(header):
    if not header.startswith('Bearer '):
        return None
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    for role, expected in TOKENS.items():
        if hmac.compare_digest(digest, expected):
            return role
    return None

class Problem(Exception):
    def __init__(self, status, error):
        self.status, self.error = status, error

def move(conn, data, key, actor):
    if (not isinstance(data, dict) or not isinstance(data.get('sku'), str)
        or not re.fullmatch('[A-Z0-9-]{1,32}', data['sku'])
        or type(data.get('delta')) is not int
        or not -1000 <= data['delta'] <= 1000 or data['delta'] == 0
        or not isinstance(data.get('note', ''), str) or len(data.get('note', '')) > 200):
        raise Problem(400, 'invalid_movement')
    if not re.fullmatch('[A-Za-z0-9_-]{8,80}', key):
        raise Problem(400, 'invalid_idempotency_key')
    sku, delta, note = data['sku'], data['delta'], data.get('note', '')
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Serialize duplicate keys even if two app processes receive different SKUs.
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (key,))
        cur.execute('SELECT id,sku,delta,note,actor,quantity_after FROM movements WHERE request_key=%s', (key,))
        old = cur.fetchone()
        if old:
            if (old['sku'],old['delta'],old['note'],old['actor']) != (sku,delta,note,actor):
                raise Problem(409, 'idempotency_conflict')
            return 200, {'movement_id':old['id'],'quantity_after':old['quantity_after'],'replayed':True}
        cur.execute('SELECT quantity FROM stock WHERE sku=%s FOR UPDATE', (sku,))
        row = cur.fetchone()
        if not row:
            raise Problem(404, 'sku_not_found')
        quantity = row['quantity'] + delta
        if quantity < 0:
            raise Problem(409, 'insufficient_stock')
        cur.execute('UPDATE stock SET quantity=%s WHERE sku=%s', (quantity,sku))
        cur.execute('INSERT INTO movements(request_key,sku,delta,quantity_after,actor,note) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id',
                    (key,sku,delta,quantity,actor,note))
        return 201, {'movement_id':cur.fetchone()['id'],'quantity_after':quantity,'replayed':False}

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def respond(self, status, payload, mime='application/json'):
        if mime == 'application/json':
            payload = json.dumps({**payload,'backend':BACKEND,'request_id':self.request_id}).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Lab-Backend', BACKEND)
        self.send_header('X-Request-ID', self.request_id)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)
        print(json.dumps({'event':'http_request','request_id':self.request_id,
              'backend':BACKEND,'method':self.command,'path':urlsplit(self.path).path,
              'status':status,'duration_ms':round((time.monotonic()-self.started)*1000,2)}), flush=True)

    def dispatch(self):
        self.request_id, self.started = uuid.uuid4().hex, time.monotonic()
        route = urlsplit(self.path).path
        if self.command == 'GET' and route == '/':
            return self.respond(200, PAGE, 'text/html')
        if self.command == 'GET' and route == '/livez':
            return self.respond(200, {'alive':True})
        if not SLOTS.acquire(blocking=False):
            return self.respond(503, {'error':'busy'})
        conn = None
        try:
            if self.command == 'GET' and route == '/healthz':
                conn = database()
                with conn.cursor() as cur:
                    cur.execute('SELECT quantity FROM stock LIMIT 1')
                return self.respond(200, {'ready':True})
            role = role_for(self.headers.get('Authorization',''))
            if role is None:
                raise Problem(401, 'unauthorized')
            if self.command == 'POST' and role != 'operator':
                raise Problem(403, 'forbidden')
            if self.command == 'GET' and route == '/api/products':
                conn = database()
                query = parse_qs(urlsplit(self.path).query).get('q',[''])[0][:64]
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute('SELECT p.sku,p.name,s.quantity FROM products p JOIN stock s USING(sku) WHERE p.sku ILIKE %s OR p.name ILIKE %s ORDER BY p.sku LIMIT 100',
                                ('%'+query+'%','%'+query+'%'))
                    return self.respond(200, {'products':list(cur.fetchall()),'role':role})
            if self.command == 'GET' and route == '/api/movements':
                conn = database()
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute('SELECT id,sku,delta,quantity_after,actor,note,created_at::text FROM movements ORDER BY id DESC LIMIT 20')
                    return self.respond(200, {'movements':list(cur.fetchall())})
            if self.command == 'POST' and route == '/api/movements':
                try:
                    length = int(self.headers.get('Content-Length','0'))
                    if not 1 <= length <= 4096:
                        raise ValueError()
                    data = json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError):
                    raise Problem(400, 'invalid_body')
                conn = database()
                with conn:
                    status, result = move(conn,data,self.headers.get('Idempotency-Key',''),role)
                return self.respond(status, result)
            raise Problem(404, 'not_found')
        except Problem as exc:
            if conn:
                conn.rollback()
            return self.respond(exc.status, {'error':exc.error})
        except psycopg2.Error as exc:
            if conn:
                conn.rollback()
            print(json.dumps({'event':'database_unavailable','request_id':self.request_id,
                              'sqlstate':exc.pgcode}), flush=True)
            return self.respond(503, {'error':'database_unavailable'})
        finally:
            if conn:
                conn.close()
            SLOTS.release()

    do_GET = dispatch
    do_POST = dispatch

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler).serve_forever()
