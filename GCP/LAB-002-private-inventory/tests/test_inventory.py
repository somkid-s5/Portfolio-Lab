"""Real PostgreSQL integration tests, no GCP provisioning."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import uuid
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
READER = 'ci-reader-' + uuid.uuid4().hex
OPERATOR = 'ci-operator-' + uuid.uuid4().hex

class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('PGDATABASE') != 'lab002_ci':
            raise RuntimeError('Tests require dedicated disposable PGDATABASE=lab002_ci')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        tokens = cls.work / 'tokens.json'
        tokens.write_text(json.dumps({r:hashlib.sha256(t.encode()).hexdigest()
                                     for r,t in [('reader',READER),('operator',OPERATOR)]}))
        with psycopg2.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((ROOT / 'db/schema.sql').read_text())
                cur.execute("DO $ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='inventory_app') THEN CREATE ROLE inventory_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD 'disposable-app-ci'; END IF; END $;")
                cur.execute((ROOT / 'db/grants.sql').read_text())
        cls.processes, cls.urls = [], []
        for backend in ['app-a','app-b']:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0))
                port = listener.getsockname()[1]
            cls.urls.append(f'http://127.0.0.1:{port}')
            cls.processes.append(subprocess.Popen(
                [sys.executable,str(ROOT / 'app/server.py')],
                env={**os.environ,'PORT':str(port),'TOKEN_HASH_FILE':str(tokens),'BACKEND_ID':backend,'PGUSER':'inventory_app','PGPASSWORD':'disposable-app-ci'},
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for url in cls.urls:
            for _ in range(100):
                try:
                    with urlopen(url+'/livez',timeout=.2) as response:
                        if response.status==200:
                            break
                except OSError:
                    time.sleep(.05)
            else:
                cls.tearDownClass()
                raise RuntimeError('App process not ready')

    @classmethod
    def tearDownClass(cls):
        for process in cls.processes:
            process.terminate()
            process.wait(timeout=10)
        cls.tmp.cleanup()

    def setUp(self):
        with psycopg2.connect() as conn:
            with conn.cursor() as cur:
                cur.execute('TRUNCATE movements,stock,products RESTART IDENTITY CASCADE')
                cur.execute((ROOT / 'db/seed.sql').read_text())

    def call(self, path, token=READER, data=None, key=None, backend=0):
        headers = {}
        if token is not None:
            headers['Authorization']='Bearer '+token
        if key:
            headers['Idempotency-Key']=key
        payload = None if data is None else json.dumps(data).encode()
        request = Request(self.urls[backend]+path,data=payload,headers=headers)
        try:
            response = urlopen(request,timeout=6)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status,json.load(response)

    def test_read_and_shared_data(self):
        code,body=self.call('/api/products')
        self.assertEqual(code,200)
        self.assertEqual(len(body['products']),5)
        code,movement=self.call('/api/movements',OPERATOR,
                    {'sku':'PEN-01','delta':3,'note':'receive'},'receive-key-01')
        self.assertEqual(code,201)
        code,body=self.call('/api/products?q=PEN-01',backend=1)
        self.assertEqual(body['backend'],'app-b')
        self.assertEqual(body['products'][0]['quantity'],23)

    def test_roles_and_validation(self):
        self.assertEqual(self.call('/api/products',None)[0],401)
        self.assertEqual(self.call('/api/products','wrong')[0],401)
        movement={'sku':'PEN-01','delta':-1}
        self.assertEqual(self.call('/api/movements',READER,movement,'reader-key-01')[0],403)
        for delta in [0,True,1001,-1001,1.5]:
            self.assertEqual(self.call('/api/movements',OPERATOR,
                          {'sku':'PEN-01','delta':delta},'invalid-key-01')[0],400)
        self.assertEqual(self.call('/api/movements',OPERATOR,movement,'short')[0],400)
        self.assertEqual(self.call('/api/movements',OPERATOR,
                     {'sku':'UNKNOWN','delta':1},'unknown-key-01')[0],404)

    def test_replay_and_payload_conflict(self):
        movement={'sku':'PEN-01','delta':-2,'note':'test'}
        first=self.call('/api/movements',OPERATOR,movement,'same-key-001')
        second=self.call('/api/movements',OPERATOR,movement,'same-key-001',backend=1)
        self.assertEqual(first[0],201)
        self.assertEqual(second[0],200)
        self.assertEqual(first[1]['movement_id'],second[1]['movement_id'])
        self.assertTrue(second[1]['replayed'])
        self.assertEqual(self.call('/api/movements',OPERATOR,
            {'sku':'PEN-01','delta':-3},'same-key-001')[0],409)

    def test_concurrent_unique_keys_never_overdraw(self):
        def withdraw(i):
            return self.call('/api/movements',OPERATOR,
                  {'sku':'PEN-01','delta':-7},f'parallel-key-{i}',backend=i%2)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses=list(pool.map(withdraw,range(4)))
        self.assertEqual(sorted(statuses),[201,201,409,409])
        body=self.call('/api/products?q=PEN-01')[1]
        self.assertEqual(body['products'][0]['quantity'],6)
        with psycopg2.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((ROOT/'db/check-invariants.sql').read_text())
                self.assertEqual(cur.fetchall(),[])

    def test_concurrent_duplicate_key_across_apps(self):
        def withdraw(i):
            return self.call('/api/movements',OPERATOR,
                {'sku':'PEN-01','delta':-4},'duplicate-key-001',backend=i%2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(withdraw,range(4)))
        self.assertEqual(sorted(r[0] for r in results),[200,200,200,201])
        self.assertEqual(len({r[1]['movement_id'] for r in results}),1)
        self.assertEqual(self.call('/api/products?q=PEN-01')[1]['products'][0]['quantity'],16)

    def test_seed_is_non_destructive(self):
        self.call('/api/movements',OPERATOR,{'sku':'PEN-01','delta':-1},'seed-test-key')
        with psycopg2.connect() as conn:
            with conn.cursor() as cur:
                cur.execute((ROOT/'db/seed.sql').read_text())
        self.assertEqual(self.call('/api/products?q=PEN-01')[1]['products'][0]['quantity'],19)

    def test_runtime_role_cannot_administer_or_rewrite_ledger(self):
        env={**os.environ,'PGUSER':'inventory_app','PGPASSWORD':'disposable-app-ci'}
        conn=psycopg2.connect(host=env['PGHOST'],dbname=env['PGDATABASE'],
                             user=env['PGUSER'],password=env['PGPASSWORD'])
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')
                self.assertEqual(cur.fetchone(),(False,False,False))
            for statement in ['CREATE TABLE forbidden(id int)', 'DELETE FROM movements',
                              "UPDATE products SET name='tampered'"]:
                with self.assertRaises(psycopg2.errors.InsufficientPrivilege):
                    with conn.cursor() as cur:
                        cur.execute(statement)
                conn.rollback()
        finally:
            conn.close()

    def test_health_and_search_injection(self):
        self.assertEqual(self.call('/healthz',None)[0],200)
        self.assertEqual(self.call('/api/products?q=%27%20OR%201%3D1--')[1]['products'],[])
        self.assertEqual(self.call('/api/movements')[0],200)

if __name__=='__main__':
    unittest.main(verbosity=2)
