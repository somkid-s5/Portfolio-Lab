"""Real PostgreSQL integration. Refuses all non-loopback/non-disposable targets."""
from concurrent.futures import ThreadPoolExecutor
import json
import hashlib
import os
from pathlib import Path
import sys
import threading
import unittest
import uuid

import pg8000.dbapi
from sqlalchemy.exc import TimeoutError as PoolTimeout

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"app"))
from order_domain import OrderEvent, canonical, parse_event
from orders import Orders, Conflict, IntegrityFailure
from outbox import Outbox
from dispatch import Dispatcher
from database import make_pool


def connection(role=None):
    if (os.environ.get("LAB007_DISPOSABLE_TEST") != "1" or
            os.environ.get("PGHOST") != "127.0.0.1" or
            os.environ.get("PGDATABASE") != "lab007_ci"):
        raise RuntimeError("disposable_loopback_database_required")
    result = pg8000.dbapi.connect(
        host="127.0.0.1", port=int(os.environ["PGPORT"]), database="lab007_ci",
        user=os.environ["PGUSER"], password=os.environ["PGPASSWORD"], timeout=5)
    if role is not None:
        if role not in {"order_api","order_worker","outbox_dispatcher"}:
            result.close()
            raise ValueError("invalid_test_role")
        cursor=result.cursor()
        cursor.execute("SET ROLE "+role)
        result.commit()
        cursor.close()
    return result


class SQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        con=connection()
        cur=con.cursor()
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != "lab007_ci":
            raise RuntimeError("wrong_test_database")
        for name in ["schema.sql","roles.sql"]:
            # Static DDL files contain no functions/quoted semicolons. Not a general SQL parser.
            text="\n".join(line for line in (LAB/"sql"/name).read_text().splitlines()
                           if not line.lstrip().startswith("--"))
            for statement in text.split(";"):
                if statement.strip():
                    cur.execute(statement)
        con.commit()
        cur.close()
        con.close()

    def setUp(self):
        self.admin("""TRUNCATE lab007.operator_actions,lab007.reservations,
            lab007.processed_events,lab007.outbox,lab007.order_items,lab007.orders""")
        self.admin("UPDATE lab007.products SET available=initial_stock")
        self.admin("UPDATE lab007.products SET unit_price_satang=12500 WHERE sku='BOOK-01'")
        self.api=Orders(lambda:connection("order_api"))
        self.worker=Orders(lambda:connection("order_worker"))
        self.dispatcher=Outbox(lambda:connection("outbox_dispatcher"))

    def admin(self, sql, parameters=()):
        con=connection()
        cur=con.cursor()
        try:
            cur.execute(sql, parameters)
            value=cur.fetchall() if cur.description else None
            con.commit()
            return value
        finally:
            cur.close()
            con.close()

    def create(self, items=None, key=None, owner="alice"):
        body=canonical({"idempotency_key":key or uuid.uuid4().hex,
                        "items":items or [{"sku":"BOOK-01","quantity":2},
                                         {"sku":"USB-01","quantity":1}]})
        return self.api.create(owner,body)

    def event(self, order_id):
        payload=self.admin("SELECT payload FROM lab007.outbox WHERE order_id=%s",(order_id,))[0][0]
        return parse_event(payload.encode("ascii"))

    def assert_stock(self):
        for value in self.worker.stock_snapshot():
            self.assertGreaterEqual(value["available"],0)
            self.assertEqual(value["initial_stock"]-value["reserved"],value["available"])

    def test_create_order_and_outbox_atomic_with_server_price(self):
        key=uuid.uuid4().hex
        first=self.create(key=key)
        again=self.create(key=key)
        self.assertEqual(first["order_id"],again["order_id"])
        self.assertFalse(first["replayed"])
        self.assertTrue(again["replayed"])
        order=self.api.read_owned("alice",first["order_id"])
        self.assertEqual(order["total_satang"],34900)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.orders")[0][0],1)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.outbox")[0][0],1)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.order_items")[0][0],2)

    def test_concurrent_same_create_key_produces_one_order(self):
        key=uuid.uuid4().hex
        barrier=threading.Barrier(6)
        def run(_):
            barrier.wait(timeout=10)
            return self.create(key=key)["order_id"]
        with ThreadPoolExecutor(max_workers=6) as pool:
            values=list(pool.map(run,range(6),timeout=30))
        self.assertEqual(len(set(values)),1)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.outbox")[0][0],1)

    def test_conflict_and_unknown_sku_do_not_create_partial_rows(self):
        key=uuid.uuid4().hex
        self.create(key=key)
        with self.assertRaisesRegex(Conflict,"idempotency_conflict"):
            self.create([{"sku":"BOOK-01","quantity":1}],key=key)
        with self.assertRaisesRegex(Conflict,"unknown_sku"):
            self.create([{"sku":"MISSING-01","quantity":1}])
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.orders")[0][0],1)
        self.assert_stock()

    def test_duplicate_delivery_concurrently_reserves_once(self):
        order=self.create()
        event=self.event(order["order_id"])
        barrier=threading.Barrier(2)
        def run(_):
            barrier.wait(timeout=10)
            return self.worker.process(event)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(run,range(2),timeout=30))
        self.assertEqual(sorted(o["disposition"] for o in outcomes),["duplicate","processed"])
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.processed_events")[0][0],1)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.reservations")[0][0],2)
        self.assert_stock()

    def test_last_unit_race_has_one_confirmed_and_one_rejected(self):
        orders=[self.create([{"sku":"LAST-01","quantity":1}]) for _ in range(2)]
        events=[self.event(o["order_id"]) for o in orders]
        barrier=threading.Barrier(2)
        def run(event):
            barrier.wait(timeout=10)
            return self.worker.process(event)["state"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            states=list(pool.map(run,events,timeout=30))
        self.assertEqual(sorted(states),["confirmed","rejected"])
        self.assertEqual(self.admin("SELECT available FROM lab007.products WHERE sku='LAST-01'")[0][0],0)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.reservations")[0][0],1)
        self.assert_stock()

    def test_multi_item_shortage_has_no_partial_reservation(self):
        order=self.create([{"sku":"BOOK-01","quantity":2},{"sku":"LAST-01","quantity":2}])
        event=self.event(order["order_id"])
        self.assertEqual(self.worker.process(event)["state"],"rejected")
        self.assertEqual(self.worker.process(event)["disposition"],"duplicate")
        self.assertEqual(self.admin("SELECT available FROM lab007.products WHERE sku='BOOK-01'")[0][0],200)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.reservations")[0][0],0)
        self.assert_stock()

    def test_exception_after_first_write_rolls_back_everything(self):
        order=self.create()
        event=self.event(order["order_id"])
        with self.assertRaisesRegex(RuntimeError,"intentional_sql_rollback"):
            self.worker.process(event,fail_after_write=True)
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"accepted")
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.reservations")[0][0],0)
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.processed_events")[0][0],0)
        self.assert_stock()
        self.assertEqual(self.worker.process(event)["state"],"confirmed")
        self.assert_stock()

    def test_commit_before_ack_replay_and_owner_boundary(self):
        order=self.create()
        event=self.event(order["order_id"])
        first=self.worker.process(event)  # Simulated HTTP reply loss occurs AFTER commit.
        before=self.worker.stock_snapshot()
        self.assertEqual(first["state"],"confirmed")
        self.assertEqual(self.worker.process(event)["disposition"],"duplicate")
        self.assertEqual(self.worker.stock_snapshot(),before)
        self.assertIsNone(self.api.read_owned("bob",order["order_id"]))

    def test_forged_event_or_corrupt_canonical_payload_is_not_acked_as_duplicate(self):
        order=self.create()
        event=self.event(order["order_id"])
        for forged in [OrderEvent(uuid.uuid4().hex,event.order_id,event.order_fingerprint),
                       OrderEvent(event.event_id,event.order_id,"f"*64)]:
            with self.assertRaises(Conflict):
                self.worker.process(forged)
        self.admin("UPDATE lab007.outbox SET payload=payload || ' ' WHERE order_id=%s",
                   (order["order_id"],))
        with self.assertRaisesRegex(IntegrityFailure,"outbox_integrity"):
            self.worker.process(event)
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"accepted")
        self.assert_stock()

    def test_runtime_grants_reject_ddl_price_edits_and_ledger_deletion(self):
        forbidden=[
            ("order_api","CREATE TABLE lab007.evil(x int)"),
            ("order_api","UPDATE lab007.orders SET state='confirmed'"),
            ("outbox_dispatcher","UPDATE lab007.products SET available=0"),
            ("order_worker","UPDATE lab007.products SET unit_price_satang=0"),
            ("order_worker","DELETE FROM lab007.reservations"),
            ("order_worker","UPDATE lab007.processed_events SET outcome='rejected'")]
        for role,sql in forbidden:
            with self.subTest(role=role,sql=sql):
                con=connection(role)
                try:
                    with self.assertRaises(pg8000.dbapi.DatabaseError):
                        con.cursor().execute(sql)
                    con.rollback()
                finally:
                    con.close()

    def test_terminal_ledger_corruption_is_detected_without_second_stock_effect(self):
        order=self.create()
        event=self.event(order["order_id"])
        self.worker.process(event)
        before=self.admin("SELECT sku,available FROM lab007.products ORDER BY sku")
        self.admin("DELETE FROM lab007.reservations WHERE order_id=%s",(order["order_id"],))
        with self.assertRaisesRegex(IntegrityFailure,"reservation_integrity"):
            self.worker.process(event)
        self.assertEqual(before,self.admin("SELECT sku,available FROM lab007.products ORDER BY sku"))

    def test_catalog_change_does_not_change_existing_order_price_snapshot(self):
        key=uuid.uuid4().hex
        order=self.create(key=key)
        self.admin("UPDATE lab007.products SET unit_price_satang=1 WHERE sku='BOOK-01'")
        self.assertTrue(self.create(key=key)["replayed"])
        self.worker.process(self.event(order["order_id"]))
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["total_satang"],34900)
        self.assertEqual(self.admin("""SELECT unit_price_satang FROM lab007.reservations
            WHERE order_id=%s AND sku='BOOK-01'""",(order["order_id"],))[0][0],12500)
        self.assert_stock()


    def test_outbox_concurrent_claims_have_one_owner(self):
        self.create()
        barrier=threading.Barrier(2)
        def run(_):
            barrier.wait(timeout=10)
            return self.dispatcher.claim()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims=list(pool.map(run,range(2),timeout=30))
        self.assertEqual(sorted(c["disposition"] for c in claims),["claimed","empty"])
        claimed=next(c for c in claims if c["disposition"]=="claimed")
        self.assertEqual(claimed["attempts"],1)
        self.assertEqual(parse_event(claimed["payload"]).event_id,claimed["event_id"])

    def test_outbox_lease_reclaim_fences_old_completion(self):
        self.create()
        old=self.dispatcher.claim()
        self.admin("""UPDATE lab007.outbox
            SET lease_until=clock_timestamp()-INTERVAL '1 second'
            WHERE event_id=%s""",(old["event_id"],))
        current=self.dispatcher.claim()
        self.assertNotEqual(old["token"],current["token"])
        self.assertEqual(current["attempts"],2)
        self.assertEqual(current["payload"],old["payload"])
        with self.assertRaisesRegex(Conflict,"stale_dispatch_claim"):
            self.dispatcher.finish(old["event_id"],old["token"],published=True)
        result=self.dispatcher.finish(current["event_id"],current["token"],published=True)
        self.assertEqual(result["state"],"published")
        self.assertEqual(self.dispatcher.claim()["disposition"],"empty")

    def test_outbox_release_republishes_same_event_without_new_order(self):
        order=self.create()
        first=self.dispatcher.claim()
        # A publish reply may be lost even when the worker has already committed.
        self.worker.process(parse_event(first["payload"]))
        before=self.worker.stock_snapshot()
        self.dispatcher.finish(first["event_id"],first["token"],published=False)
        second=self.dispatcher.claim()
        self.assertEqual((second["event_id"],second["payload"]),
                         (first["event_id"],first["payload"]))
        self.assertEqual(self.worker.process(parse_event(second["payload"]))["disposition"],
                         "duplicate")
        self.dispatcher.finish(second["event_id"],second["token"],published=True)
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"confirmed")
        self.assertEqual(before,self.worker.stock_snapshot())
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.orders")[0][0],1)

    def test_outbox_retry_budget_is_finite_and_does_not_reject_order(self):
        order=self.create()
        for attempt in range(1,11):
            claim=self.dispatcher.claim()
            self.assertEqual(claim["attempts"],attempt)
            self.dispatcher.finish(claim["event_id"],claim["token"],published=False)
        self.assertEqual(self.dispatcher.claim()["disposition"],"exhausted")
        self.assertEqual(self.dispatcher.claim()["disposition"],"empty")
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"accepted")
        self.assertEqual(tuple(self.admin("SELECT attempts,last_outcome FROM lab007.outbox")[0]),
                         (10,"dispatch_budget"))
        self.assert_stock()

    def test_outbox_corruption_is_quarantined_without_publish_or_stock_write(self):
        order=self.create()
        self.admin("UPDATE lab007.outbox SET payload=payload || ' ' WHERE order_id=%s",
                   (order["order_id"],))
        self.assertEqual(self.dispatcher.claim()["disposition"],"integrity_blocked")
        self.assertEqual(self.dispatcher.claim()["disposition"],"empty")
        self.assertEqual(self.admin("SELECT last_outcome FROM lab007.outbox")[0][0],
                         "invalid_canonical")
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"accepted")
        self.assert_stock()

    def test_outbox_expired_current_token_cannot_finish_without_reclaim(self):
        self.create()
        claim=self.dispatcher.claim()
        self.admin("""UPDATE lab007.outbox
            SET lease_until=clock_timestamp()-INTERVAL '1 second'
            WHERE event_id=%s""",(claim["event_id"],))
        with self.assertRaisesRegex(Conflict,"stale_dispatch_claim"):
            self.dispatcher.finish(claim["event_id"],claim["token"],published=False)
        self.assertEqual(self.dispatcher.claim()["attempts"],2)


    def test_dispatcher_publish_runs_after_outbox_lock_is_released(self):
        order=self.create()
        test=self
        class WorkerPublisher:
            def publish(self,payload):
                event=parse_event(payload)
                # NOWAIT proves no claim transaction still holds this outbox row.
                test.admin("SELECT event_id FROM lab007.outbox WHERE event_id=%s FOR UPDATE NOWAIT",
                           (event.event_id,))
                test.worker.process(event)
                return "synthetic-123"
        result=Dispatcher(self.dispatcher,WorkerPublisher()).drain()
        self.assertEqual((result["status"],result["finished"]),(200,1))
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"confirmed")
        self.assert_stock()

    def test_dispatcher_unknown_publish_reply_reuses_committed_business_result(self):
        self.create()
        test=self
        published=[]
        class LostReplyPublisher:
            def publish(self,payload):
                event=parse_event(payload)
                published.append(event.event_id)
                test.worker.process(event)
                if len(published)==1:
                    raise TimeoutError("private-secret")
                return "synthetic-123"
        dispatcher=Dispatcher(self.dispatcher,LostReplyPublisher())
        first=dispatcher.drain()
        self.assertEqual((first["status"],first["reason"]),(503,"publish_unconfirmed"))
        before=self.worker.stock_snapshot()
        second=dispatcher.drain()
        self.assertEqual((second["status"],second["finished"]),(200,1))
        self.assertEqual(published[0],published[1])
        self.assertEqual(before,self.worker.stock_snapshot())
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.orders")[0][0],1)
        self.assertNotIn("private-secret",json.dumps(first))
        self.assert_stock()

    def test_dispatcher_unknown_finish_commit_does_not_release_or_publish_again(self):
        self.create()
        test=self
        finish_calls=[]
        class UnknownFinish:
            def claim(self):
                return test.dispatcher.claim()
            def finish(self,*args,**kwargs):
                finish_calls.append(kwargs["published"])
                test.dispatcher.finish(*args,**kwargs)
                raise ConnectionError("private-secret")
        class WorkerPublisher:
            def publish(self,payload):
                test.worker.process(parse_event(payload))
                return "synthetic-123"
        first=Dispatcher(UnknownFinish(),WorkerPublisher()).drain()
        self.assertEqual((first["status"],first["reason"]),(503,"finish_unconfirmed"))
        self.assertEqual(finish_calls,[True])
        self.assertEqual(self.admin("SELECT state FROM lab007.outbox")[0][0],"published")
        second=Dispatcher(self.dispatcher,WorkerPublisher()).drain()
        self.assertEqual((second["reason"],second["claimed"]),("empty",0))
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.processed_events")[0][0],1)
        self.assert_stock()

    def test_outbox_noncanonical_serialization_is_blocked_even_with_matching_hash(self):
        order=self.create()
        payload=self.admin("SELECT payload FROM lab007.outbox WHERE order_id=%s",
                           (order["order_id"],))[0][0]+" "
        self.admin("UPDATE lab007.outbox SET payload=%s,payload_sha256=%s WHERE order_id=%s",
                   (payload,hashlib.sha256(payload.encode("ascii")).hexdigest(),order["order_id"]))
        self.assertEqual(self.dispatcher.claim()["disposition"],"integrity_blocked")
        self.assertEqual(self.api.read_owned("alice",order["order_id"])["state"],"accepted")
        self.assert_stock()

    def test_health_reads_schema_using_runtime_roles_without_creating_orders(self):
        self.assertTrue(self.api.health())
        self.assertTrue(self.worker.health())
        self.assertTrue(self.dispatcher.health())
        self.assertEqual(self.admin("SELECT count(*) FROM lab007.orders")[0][0],0)


    def test_real_pool_preserves_repository_transactions_with_same_pg8000_driver(self):
        api_engine=make_pool(lambda:connection("order_api"),2)
        worker_engine=make_pool(lambda:connection("order_worker"),2)
        self.addCleanup(api_engine.dispose)
        self.addCleanup(worker_engine.dispose)
        api=Orders(api_engine.raw_connection)
        worker=Orders(worker_engine.raw_connection)
        self.assertTrue(api.health())
        order=api.create("alice",canonical({"idempotency_key":uuid.uuid4().hex,
            "items":[{"sku":"BOOK-01","quantity":1}]}))
        self.assertEqual(worker.process(self.event(order["order_id"]))["state"],"confirmed")
        self.assertEqual(api.read_owned("alice",order["order_id"])["total_satang"],12500)
        self.assertNotIn(os.environ["PGPASSWORD"],str(api_engine.url))
        self.assert_stock()

    def test_pool_does_not_overflow_and_reuses_released_connection(self):
        creations=[]
        def creator():
            con=connection("order_worker")
            creations.append(con)
            return con
        engine=make_pool(creator,1)
        self.addCleanup(engine.dispose)
        first=engine.raw_connection()
        physical=first.driver_connection
        try:
            with self.assertRaises(PoolTimeout):
                engine.raw_connection()
            self.assertEqual(len(creations),1)
        finally:
            first.close()
        second=engine.raw_connection()
        try:
            self.assertIs(second.driver_connection,physical)
            self.assertEqual(len(creations),1)
        finally:
            second.close()

    def test_pool_rolls_back_uncommitted_changes_before_reuse(self):
        engine=make_pool(lambda:connection("order_worker"),1)
        self.addCleanup(engine.dispose)
        first=engine.raw_connection()
        cursor=first.cursor()
        try:
            cursor.execute("UPDATE lab007.products SET available=available-1 WHERE sku='BOOK-01'")
        finally:
            cursor.close()
            first.close()  # No commit: pool reset must roll back.
        second=engine.raw_connection()
        cursor=second.cursor()
        try:
            cursor.execute("SELECT available,current_user FROM lab007.products WHERE sku='BOOK-01'")
            available,user=cursor.fetchone()
            self.assertEqual((available,user),(200,"order_worker"))
        finally:
            cursor.close()
            second.close()
        self.assert_stock()


if __name__ == "__main__":
    unittest.main()
