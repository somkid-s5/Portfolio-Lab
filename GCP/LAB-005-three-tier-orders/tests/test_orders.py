"""Disposable PostgreSQL16 domain tests. Not GCP failover evidence."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import unittest
from sqlalchemy import create_engine,event,text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from orders import Orders,Problem,cart

class OrdersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('PGDATABASE')!='orders_ci':
            raise RuntimeError('Use dedicated disposable PGDATABASE=orders_ci')
        def engine(user,password):
            result=create_engine(URL.create('postgresql+pg8000',username=user,password=password,
                host=os.environ['PGHOST'],port=5432,database='orders_ci'),
                pool_size=4,max_overflow=0,pool_timeout=3,pool_pre_ping=True,
                connect_args={'timeout':5},hide_parameters=True)
            @event.listens_for(result,'connect')
            def limits(connection,record):
                cursor=connection.cursor()
                try:
                    cursor.execute("SET statement_timeout = '5s'")
                    cursor.execute("SET lock_timeout = '3s'")
                    connection.commit()
                finally:
                    cursor.close()
            return result
        cls.admin=engine(os.environ['PGUSER'],os.environ['PGPASSWORD'])
        with cls.admin.begin() as conn:
            conn.exec_driver_sql("CREATE ROLE orders_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD 'disposable-orders-ci';")
            for filename in ['schema.sql','grants.sql']:
                source=(ROOT/'db'/filename).read_text().replace('DATABASE orders TO','DATABASE orders_ci TO')
                for statement in source.split(';'):
                    if statement.strip():
                        conn.exec_driver_sql(statement)
        cls.engines=[engine('orders_app','disposable-orders-ci') for _ in range(2)]
        # Distinct pools model two API processes sharing one PostgreSQL DB.
        cls.services=[Orders(e) for e in cls.engines]

    @classmethod
    def tearDownClass(cls):
        for engine in cls.engines+[cls.admin]:
            engine.dispose()

    def setUp(self):
        with self.admin.begin() as conn:
            conn.exec_driver_sql('TRUNCATE stock_events,order_items,orders,products RESTART IDENTITY CASCADE')
            for statement in (ROOT/'db/seed.sql').read_text().split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)

    def tearDown(self):
        with self.admin.connect() as conn:
            self.assertEqual(conn.exec_driver_sql((ROOT/'db/check-invariants.sql').read_text()).all(),[])
        for engine in self.engines:
            self.assertEqual(engine.pool.checkedout(),0)

    def place(self,index=0,username='alice',key='order-key-001',items=None):
        return self.services[index].place(username,key,items if items is not None else [{'sku':'BOOK-01','quantity':2}])

    def test_replay_normalization_snapshot_and_cancel_once(self):
        items=[{'sku':'PEN-01','quantity':1},{'sku':'BOOK-01','quantity':2}]
        first,replayed=self.place(items=items)
        self.assertFalse(replayed)
        self.assertEqual(first['total_satang'],28000)
        with self.admin.begin() as conn:
            conn.execute(text("UPDATE products SET unit_price_satang=20000 WHERE sku='BOOK-01'"))
        second,replayed=self.place(index=1,items=list(reversed(items)))
        self.assertTrue(replayed)
        self.assertEqual(second['id'],first['id'])
        self.assertEqual(second['total_satang'],28000)
        with self.assertRaises(Problem) as conflict:
            self.place(items=[{'sku':'BOOK-01','quantity':1}])
        self.assertEqual(conflict.exception.status,409)
        for expected in [False,True]:
            cancelled,replayed=self.services[1].cancel('alice',first['id'])
            self.assertEqual(replayed,expected)
            self.assertEqual(cancelled['status'],'cancelled')
        replay,replayed=self.place(items=items)
        self.assertTrue(replayed)
        self.assertEqual(replay['status'],'cancelled')
        with self.admin.connect() as conn:
            self.assertEqual(conn.execute(text("SELECT count(*) FROM stock_events WHERE event='cancelled'")).scalar_one(),2)
            self.assertEqual(conn.execute(text("SELECT available FROM products WHERE sku='BOOK-01'")).scalar_one(),10)

    def test_ownership_and_key_scope(self):
        first,_=self.place()
        second,_=self.place(username='bob')
        self.assertNotEqual(first['id'],second['id'])
        for operation in [self.services[1].get,self.services[1].cancel]:
            with self.assertRaises(Problem) as denied:
                operation('bob',first['id'])
            self.assertEqual(denied.exception.status,404)
        self.assertEqual(len(self.services[1].list('alice')),1)
        self.assertEqual(self.services[1].get('alice',first['id'])['id'],first['id'])

    def test_concurrent_same_key_across_two_pools(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda i:self.place(index=i%2),range(6)))
        self.assertEqual(sum(not replay for _,replay in results),1)
        self.assertEqual(len({row['id'] for row,_ in results}),1)
        with self.admin.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM orders')).scalar_one(),1)

    def test_concurrent_distinct_users_cannot_oversell(self):
        def reserve(i):
            try:
                return self.place(index=i%2,username='user'+str(i),key='race-key-'+str(i),
                                  items=[{'sku':'USB-01','quantity':1}])[0]['id']
            except Problem as exc:
                self.assertEqual(exc.status,409)
                self.assertEqual(exc.error,'insufficient_stock')
                return None
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(reserve,range(6)))
        self.assertEqual(sum(x is not None for x in results),4)

    def test_reverse_cart_lock_order_and_cancel_race(self):
        def reserve(i):
            items=[{'sku':'BOOK-01','quantity':1},{'sku':'MUG-01','quantity':1}]
            if i%2:
                items.reverse()
            return self.place(index=i%2,username='user'+str(i),key='multi-key-'+str(i),items=items)[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(reserve,range(4)))
        first=results[0]
        with ThreadPoolExecutor(max_workers=4) as pool:
            cancelled=list(pool.map(lambda i:self.services[i%2].cancel('user0',first['id']),range(4)))
        self.assertEqual(sum(not replay for _,replay in cancelled),1)

    def test_invalid_or_insufficient_cart_is_atomic(self):
        bad=[[],[{'sku':'BOOK-01','quantity':True}],
             [{'sku':'BOOK-01','quantity':21}],
             [{'sku':'BOOK-01','quantity':1},{'sku':'BOOK-01','quantity':2}],
             [{'sku':"BAD';DROP TABLE products",'quantity':1}],
             [{'sku':'MISSING-01','quantity':1}],
             [{'sku':'BOOK-01','quantity':1},{'sku':'MUG-01','quantity':6}]]
        for items in bad:
            with self.assertRaises(Problem):
                self.place(items=items)
        with self.admin.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM orders')).scalar_one(),0)
            self.assertEqual(conn.execute(text('SELECT sum(available-initial_stock) FROM products')).scalar_one(),0)
        for owner,key in [(None,'valid-key'),('alice','short'),('alice','bad key 001')]:
            with self.assertRaises(Problem):
                self.place(username=owner,key=key)

    def test_ledger_failure_rolls_back_order_items_and_stock(self):
        with self.admin.begin() as conn:
            conn.exec_driver_sql("""CREATE FUNCTION reject_test_event() RETURNS trigger LANGUAGE plpgsql AS
                $$ BEGIN RAISE EXCEPTION 'injected test-only ledger failure'; END; $""")
            conn.exec_driver_sql('CREATE TRIGGER reject_event BEFORE INSERT ON stock_events FOR EACH ROW EXECUTE FUNCTION reject_test_event()')
        try:
            with self.assertRaises(SQLAlchemyError):
                self.place()
            with self.admin.connect() as conn:
                for table in ['orders','order_items','stock_events']:
                    self.assertEqual(conn.exec_driver_sql('SELECT count(*) FROM '+table).scalar_one(),0)
                self.assertEqual(conn.execute(text("SELECT available FROM products WHERE sku='BOOK-01'")).scalar_one(),10)
        finally:
            with self.admin.begin() as conn:
                conn.exec_driver_sql('DROP TRIGGER reject_event ON stock_events')
                conn.exec_driver_sql('DROP FUNCTION reject_test_event()')

    def test_non_destructive_seed(self):
        self.place()
        with self.admin.begin() as conn:
            for statement in (ROOT/'db/seed.sql').read_text().split(';'):
                if statement.strip():
                    conn.exec_driver_sql(statement)
            self.assertEqual(conn.execute(text("SELECT available FROM products WHERE sku='BOOK-01'")).scalar_one(),8)

    def test_runtime_is_not_admin_or_ledger_deleter(self):
        with self.engines[0].connect() as conn:
            self.assertEqual(tuple(conn.execute(text('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user')).one()),(False,False,False))
        for statement in ['CREATE TABLE forbidden(id int)','DELETE FROM stock_events',
                          'UPDATE products SET initial_stock=999','UPDATE products SET unit_price_satang=1']:
            with self.assertRaises(SQLAlchemyError):
                with self.engines[0].begin() as conn:
                    conn.exec_driver_sql(statement)

if __name__=='__main__':
    unittest.main(verbosity=2)
