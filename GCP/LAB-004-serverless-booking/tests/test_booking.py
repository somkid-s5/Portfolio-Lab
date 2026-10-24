from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine,text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from main import create_app
from database import create_pool

class BookingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('PGDATABASE')!='booking_ci':
            raise RuntimeError('Use dedicated disposable PGDATABASE=booking_ci')
        cls.tmp=tempfile.TemporaryDirectory()
        cls.work=Path(cls.tmp.name)
        cls.auth={'session_key':'a'*64,'users':{
            name:{'role':role,'password_hash':generate_password_hash('test-'+name,method='pbkdf2:sha256:1000')}
            for name,role in [('alice','booker'),('bob','booker'),('operator','operator')]}}
        url=URL.create('postgresql+pg8000',username=os.environ['PGUSER'],
            password=os.environ['PGPASSWORD'],host=os.environ['PGHOST'],port=5432,database='booking_ci')
        cls.admin=create_engine(url,hide_parameters=True)
        with cls.admin.begin() as conn:
            for suffix in ['a','b']:
                conn.exec_driver_sql("CREATE ROLE booking_"+suffix+" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD 'disposable-booking-"+suffix+"';")
            for statement in (ROOT/'db/schema.sql').read_text().split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)
            grants=(ROOT/'db/grants.sql').read_text().replace('DATABASE booking TO','DATABASE booking_ci TO')
            for statement in grants.split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)
        cls.configs={}
        for suffix in ['a','b']:
            config=cls.work/('db-'+suffix+'.json')
            config.write_text(json.dumps({'user':'booking_'+suffix,'password':'disposable-booking-'+suffix,
                'database':'booking_ci','host':os.environ['PGHOST'],'port':5432}))
            cls.configs[suffix]=config
        with patch.dict(os.environ,{'DB_MODE':'local','DB_CONFIG_FILE':str(cls.configs['a'])}):
            cls.pool=create_pool()
        cls.app=create_app(cls.pool,cls.auth)
        cls.app.config['TESTING']=True

    @classmethod
    def tearDownClass(cls):
        cls.pool.dispose()
        cls.admin.dispose()
        cls.tmp.cleanup()

    def setUp(self):
        with self.admin.begin() as conn:
            conn.exec_driver_sql('TRUNCATE booking_events,bookings,slots RESTART IDENTITY CASCADE')
            for statement in (ROOT/'db/seed.sql').read_text().split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)

    def tearDown(self):
        self.assertEqual(self.pool.pool.checkedout(),0)
        with self.admin.connect() as conn:
            self.assertEqual(conn.exec_driver_sql((ROOT/'db/check-invariants.sql').read_text()).all(),[])

    def client(self,username=None,app=None):
        client=(app or self.app).test_client()
        csrf=client.get('/api/session',base_url='https://localhost').json['csrf']
        if username:
            response=client.post('/api/login',json={'username':username,'password':'test-'+username},
                   headers={'X-CSRF-Token':csrf},base_url='https://localhost')
            self.assertEqual(response.status_code,200,response.json)
            csrf=response.json['csrf']
        return client,csrf

    def reserve(self,client,csrf,key='booking-key-001',slot=1):
        return client.post('/api/bookings',json={'slot_id':slot},
               headers={'X-CSRF-Token':csrf,'Idempotency-Key':key},base_url='https://localhost')

    def test_session_csrf_cookie_and_auth_boundaries(self):
        client,csrf=self.client()
        self.assertEqual(client.get('/api/slots',base_url='https://localhost').status_code,401)
        self.assertEqual(client.post('/api/login',json={},base_url='https://localhost').status_code,403)
        self.assertEqual(client.post('/api/login',json={'username':'alice','password':'wrong'},
            headers={'X-CSRF-Token':csrf},base_url='https://localhost').status_code,401)
        response=self.app.test_client().get('/api/session',base_url='https://localhost')
        cookie=response.headers.get('Set-Cookie','')
        self.assertIn('Secure',cookie)
        self.assertIn('HttpOnly',cookie)
        self.assertIn('SameSite=Lax',cookie)

    def test_reserve_replay_conflict_and_cancel_once(self):
        client,csrf=self.client('alice')
        first=self.reserve(client,csrf)
        self.assertEqual(first.status_code,201,first.json)
        replay=self.reserve(client,csrf)
        self.assertEqual(replay.status_code,200)
        self.assertEqual(first.json['booking']['id'],replay.json['booking']['id'])
        self.assertEqual(self.reserve(client,csrf,slot=2).status_code,409)
        bid=first.json['booking']['id']
        for expected_replay in [False,True]:
            response=client.post('/api/bookings/'+bid+'/cancel',json={},
                 headers={'X-CSRF-Token':csrf},base_url='https://localhost')
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.json['replayed'],expected_replay)
        with self.admin.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM booking_events WHERE event='cancelled'")).scalar(),1)

    def test_ownership_and_operator_role(self):
        alice,csrf=self.client('alice')
        bid=self.reserve(alice,csrf).json['booking']['id']
        bob,bcsrf=self.client('bob')
        self.assertEqual(bob.get('/api/bookings/'+bid,base_url='https://localhost').status_code,404)
        self.assertEqual(bob.post('/api/bookings/'+bid+'/cancel',json={},
             headers={'X-CSRF-Token':bcsrf},base_url='https://localhost').status_code,404)
        self.assertEqual(bob.get('/api/bookings',base_url='https://localhost').json['bookings'],[])
        self.assertEqual(bob.get('/api/operator/bookings',base_url='https://localhost').status_code,403)
        operator,_=self.client('operator')
        self.assertEqual(len(operator.get('/api/operator/bookings',base_url='https://localhost').json['bookings']),1)

    def test_concurrent_users_cannot_overbook(self):
        with self.admin.begin() as conn:
            conn.execute(text('UPDATE slots SET capacity=1 WHERE id=1'))
        def reserve(username):
            client,csrf=self.client(username)
            return self.reserve(client,csrf,key='concurrent-'+username).status_code
        with ThreadPoolExecutor(max_workers=3) as pool:
            statuses=list(pool.map(reserve,['alice','bob','operator']))
        self.assertEqual(sorted(statuses),[201,409,409])

    def test_concurrent_same_key_creates_one_booking(self):
        def reserve(index):
            client,csrf=self.client('alice')
            return self.reserve(client,csrf)
        with ThreadPoolExecutor(max_workers=3) as pool:
            responses=list(pool.map(reserve,range(3)))
        self.assertEqual(sorted(r.status_code for r in responses),[200,200,201])
        self.assertEqual(len({r.json['booking']['id'] for r in responses}),1)

    def test_v2_and_rollback_keep_data(self):
        client,csrf=self.client('alice')
        bid=self.reserve(client,csrf).json['booking']['id']
        with patch.dict(os.environ,{'APP_VERSION':'v2'}):
            newer=create_app(self.pool,self.auth)
        v2,_=self.client('alice',newer)
        response=v2.get('/api/bookings/'+bid,base_url='https://localhost')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['version'],'v2')
        self.assertEqual(client.get('/api/bookings/'+bid,base_url='https://localhost').status_code,200)


    def test_operations_snapshot_and_retirement_guards(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('booking_ops',ROOT/'scripts/inspect-db.py')
        ops=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ops)
        first=ops.snapshot(self.admin)
        self.assertEqual(first['invariant_violations'],[])
        self.assertEqual(len(first['slots']),5)
        # Existing checked-in pooled A sessions must block retirement.
        held=self.pool.connect()
        try:
            with self.assertRaisesRegex(ValueError,'still has connections'):
                ops.retire_a(self.admin)
        finally:
            held.close()
        self.pool.dispose()
        with self.admin.begin() as conn:
            conn.exec_driver_sql('ALTER ROLE booking_b NOLOGIN')
        try:
            with self.assertRaisesRegex(ValueError,'Login B'):
                ops.retire_a(self.admin)
        finally:
            with self.admin.begin() as conn:
                conn.exec_driver_sql('ALTER ROLE booking_b LOGIN')
        try:
            ops.retire_a(self.admin)
            state=ops.snapshot(self.admin)
            self.assertFalse(next(r for r in state['roles'] if r['rolname']=='booking_a')['rolcanlogin'])
            with self.assertRaises(SQLAlchemyError):
                with self.pool.connect():
                    pass
        finally:
            with self.admin.begin() as conn:
                conn.exec_driver_sql('ALTER ROLE booking_a LOGIN')


    def test_http_probe_journey_read_limits_and_no_secret_output(self):
        import importlib.util
        import threading
        from werkzeug.serving import make_server
        spec=importlib.util.spec_from_file_location('booking_probe',ROOT/'scripts/probe.py')
        probe=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        insecure=create_app(self.pool,self.auth)
        insecure.config['SESSION_COOKIE_SECURE']=False
        server=make_server('127.0.0.1',0,insecure,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        url='http://127.0.0.1:'+str(server.server_port)
        logins={u:'test-'+u for u in self.auth['users']}
        try:
            with self.assertRaises(ValueError):
                probe.Client(url)
            with self.assertRaises(ValueError):
                probe.Client('http://example.com',True)
            with self.assertRaises(ValueError):
                probe.Client('https://example.com/path')
            result=probe.journey(url,logins,True)
            self.assertEqual(result['checks'],'completed')
            serialized=json.dumps(result)
            for password in logins.values():
                self.assertNotIn(password,serialized)
            self.assertNotIn('csrf',serialized.lower())
            raced=probe.capacity_race(url,logins,True)
            self.assertEqual(raced['checks'],'completed')
            loaded=probe.read_load(url,logins,8,2,True)
            self.assertEqual(loaded['sample_count'],8)
            self.assertEqual(loaded['status_counts'],{'200':8})
            for requests,workers in [(201,1),(1,17),(0,1)]:
                with self.assertRaises(ValueError):
                    probe.read_load(url,logins,requests,workers,True)
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


    def test_cloud_connector_api_failure_is_sanitized_and_returns_503(self):
        from unittest.mock import MagicMock
        connector=MagicMock()
        connector.connect.side_effect=RuntimeError('secret-sensitive-upstream-details')
        with patch('google.cloud.sql.connector.Connector',return_value=connector), patch.dict(os.environ,
             {'DB_MODE':'cloud','DB_CONFIG_FILE':str(self.configs['a']),
              'INSTANCE_CONNECTION_NAME':'sandbox:asia-southeast1:missing'}):
            broken=create_pool()
        try:
            with self.assertRaises(SQLAlchemyError) as caught:
                broken.connect()
            self.assertNotIn('secret-sensitive-upstream-details',str(caught.exception))
            app=create_app(broken,self.auth)
            client,_=self.client(app=app)
            self.assertEqual(client.get('/livez',base_url='https://localhost').status_code,200)
            response=client.get('/healthz',base_url='https://localhost')
            self.assertEqual(response.status_code,503)
            self.assertNotIn('secret-sensitive',response.get_data(as_text=True))
        finally:
            broken.dispose()

    def test_runtime_role_is_not_db_admin(self):
        with self.pool.connect() as conn:
            self.assertEqual(tuple(conn.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')).one()),(False,False,False))
        for statement in ['CREATE TABLE forbidden(id int)','DELETE FROM booking_events','UPDATE slots SET capacity=999']:
            with self.assertRaises(SQLAlchemyError):
                with self.pool.begin() as conn:
                    conn.exec_driver_sql(statement)

    def test_health_ui_and_static_assets(self):
        client,_=self.client()
        for route in ['/','/livez','/healthz','/static/app.js','/static/style.css']:
            self.assertEqual(client.get(route,base_url='https://localhost').status_code,200)
        self.assertIn("script-src 'self'",client.get('/',base_url='https://localhost').headers['Content-Security-Policy'])

    def test_pool_exhaustion_fails_bounded_and_recovers(self):
        held=[self.pool.connect() for _ in range(4)]
        try:
            client,_=self.client()
            response=client.get('/healthz',base_url='https://localhost')
            self.assertEqual(response.status_code,503,response.json)
        finally:
            for conn in held:
                conn.close()
        self.assertEqual(client.get('/healthz',base_url='https://localhost').status_code,200)

    def test_private_dependency_config_failure_does_not_break_liveness(self):
        bad=create_engine(URL.create('postgresql+pg8000',username='unreachable',
             password='not-a-real-secret',host='127.0.0.1',port=1,database='booking_ci'),
             connect_args={'timeout':1},hide_parameters=True)
        try:
            broken=create_app(bad,self.auth)
            client,_=self.client(app=broken)
            self.assertEqual(client.get('/livez',base_url='https://localhost').status_code,200)
            self.assertEqual(client.get('/healthz',base_url='https://localhost').status_code,503)
        finally:
            bad.dispose()
        client,_=self.client()
        self.assertEqual(client.get('/healthz',base_url='https://localhost').status_code,200)

    def test_credential_b_keeps_data_after_a_is_retired(self):
        client,csrf=self.client('alice')
        bid=self.reserve(client,csrf).json['booking']['id']
        with patch.dict(os.environ,{'DB_MODE':'local','DB_CONFIG_FILE':str(self.configs['b'])}):
            pool_b=create_pool()
        try:
            newer=create_app(pool_b,self.auth)
            second,_=self.client('alice',newer)
            self.assertEqual(second.get('/api/bookings/'+bid,base_url='https://localhost').status_code,200)
            with self.admin.begin() as conn:
                conn.exec_driver_sql('ALTER ROLE booking_a NOLOGIN')
            self.pool.dispose()
            self.assertEqual(client.get('/healthz',base_url='https://localhost').status_code,503)
            self.assertEqual(second.get('/healthz',base_url='https://localhost').status_code,200)
        finally:
            with self.admin.begin() as conn:
                conn.exec_driver_sql('ALTER ROLE booking_a LOGIN')
            self.pool.dispose()
            pool_b.dispose()

    def test_cloud_run_refuses_local_db_and_insecure_cookie_modes(self):
        with patch.dict(os.environ,{'K_SERVICE':'test-service','DB_MODE':'local','DB_CONFIG_FILE':str(self.configs['a'])}):
            with self.assertRaises(ValueError):
                create_pool()
        with patch.dict(os.environ,{'K_SERVICE':'test-service','APP_LOCAL_TEST':'1'}):
            with self.assertRaises(ValueError):
                create_app(self.pool,self.auth)

if __name__=='__main__':
    unittest.main(verbosity=2)
