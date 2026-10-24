"""DB-API repository for atomic order/outbox creation and stock reservation.
Connection factories must supply the matching least-privilege role. No external
network calls occur inside these SQL transactions. A committed transaction is
not proof that an HTTP acknowledgement was delivered.
"""
from contextlib import contextmanager
import hashlib
import uuid
from order_domain import (OrderEvent, create_order, event_bytes, identifier,
                          key_hash, order_binding, owner_name, parse_event)
from pagination import decode_cursor,page,page_limit


class Conflict(ValueError):
    pass


class IntegrityFailure(ValueError):
    pass


def row(cursor):
    value = cursor.fetchone()
    if value is None:
        return None
    return dict(zip((column[0] for column in cursor.description), value))


def all_rows(cursor):
    columns=[field[0] for field in cursor.description]
    return [dict(zip(columns,value)) for value in cursor.fetchall()]


class Orders:
    def __init__(self, connect):
        self.connect = connect

    @contextmanager
    def transaction(self):
        connection = self.connect()
        cursor = connection.cursor()
        try:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            cursor.execute("SET LOCAL statement_timeout = '3s'")
            cursor.execute("SET LOCAL lock_timeout = '2s'")
            yield cursor
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            try:
                cursor.close()
            finally:
                connection.close()

    def create(self, owner, body):
        owner = owner_name(owner)
        request = create_order(body)
        scoped_key = key_hash(owner, request.idempotency_key)
        # Hash collisions can serialize unrelated keys, but cannot merge orders.
        advisory = int.from_bytes(bytes.fromhex(scoped_key)[:8], "big", signed=True)
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (advisory,))
            cursor.execute("""SELECT order_id,request_fingerprint,state
                FROM lab007.orders WHERE owner=%s AND key_hash=%s""", (owner,scoped_key))
            previous = row(cursor)
            if previous:
                if previous["request_fingerprint"] != request.request_fingerprint:
                    raise Conflict("idempotency_conflict")
                return {"order_id":previous["order_id"],"state":previous["state"],
                        "replayed":True}
            skus = [item[0] for item in request.items]
            placeholders = ",".join(["%s"]*len(skus))
            cursor.execute("SELECT sku,unit_price_satang FROM lab007.products "
                           "WHERE sku IN ("+placeholders+") ORDER BY sku", tuple(skus))
            prices = dict(cursor.fetchall())
            if set(prices) != set(skus):
                raise Conflict("unknown_sku")
            priced = [{"sku":sku,"quantity":quantity,
                       "unit_price_satang":prices[sku]} for sku,quantity in request.items]
            order_id, event_id = uuid.uuid4().hex, uuid.uuid4().hex
            items, fingerprint, total = order_binding(owner,order_id,priced)
            payload = event_bytes(event_id,order_id,fingerprint)
            cursor.execute("""INSERT INTO lab007.orders
                (order_id,owner,key_hash,request_fingerprint,order_fingerprint,total_satang)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (order_id,owner,scoped_key,request.request_fingerprint,fingerprint,total))
            for item in items:
                cursor.execute("""INSERT INTO lab007.order_items
                    (order_id,sku,quantity,unit_price_satang) VALUES (%s,%s,%s,%s)""",
                    (order_id,item["sku"],item["quantity"],item["unit_price_satang"]))
            cursor.execute("""INSERT INTO lab007.outbox
                (event_id,order_id,payload,payload_sha256) VALUES (%s,%s,%s,%s)""",
                (event_id,order_id,payload.decode("ascii"),hashlib.sha256(payload).hexdigest()))
            return {"order_id":order_id,"state":"accepted","replayed":False}

    def read_owned(self, owner, order_id):
        owner, order_id = owner_name(owner), identifier(order_id)
        with self.transaction() as cursor:
            cursor.execute("""SELECT order_id,owner,state,safe_reason,total_satang,
                order_fingerprint,created_at,finished_at FROM lab007.orders
                WHERE owner=%s AND order_id=%s""", (owner,order_id))
            order=row(cursor)
            if order is None:
                return None
            cursor.execute("""SELECT sku,quantity,unit_price_satang FROM lab007.order_items
                WHERE order_id=%s ORDER BY sku""",(order_id,))
            order["items"]=all_rows(cursor)
            cursor.execute("""SELECT event_id,state,epoch,attempts,last_outcome,published_at
                FROM lab007.outbox WHERE order_id=%s""",(order_id,))
            order["dispatch"]=row(cursor)
            return order

    def health(self):
        with self.transaction() as cursor:
            cursor.execute("SELECT version,seed_version FROM lab007.schema_meta WHERE singleton")
            if tuple(cursor.fetchone() or ()) != (1,"catalog-v1"):
                raise IntegrityFailure("schema_mismatch")
            return True

    def process(self, event, *, fail_after_write=False):
        if not isinstance(event,OrderEvent):
            raise TypeError("parsed_event_required")
        event_bytes(event.event_id,event.order_id,event.order_fingerprint)
        with self.transaction() as cursor:
            cursor.execute("SELECT * FROM lab007.orders WHERE order_id=%s FOR UPDATE",
                           (event.order_id,))
            order = row(cursor)
            if order is None:
                raise Conflict("unknown_order")
            cursor.execute("SELECT event_id,payload,payload_sha256 FROM lab007.outbox "
                           "WHERE order_id=%s", (event.order_id,))
            stored = row(cursor)
            if (stored is None or stored["event_id"] != event.event_id or
                    order["order_fingerprint"] != event.order_fingerprint):
                raise Conflict("event_binding_mismatch")
            payload = stored["payload"].encode("ascii")
            if (hashlib.sha256(payload).hexdigest() != stored["payload_sha256"] or
                    parse_event(payload) != event):
                raise IntegrityFailure("outbox_integrity")
            cursor.execute("""SELECT sku,quantity,unit_price_satang FROM lab007.order_items
                WHERE order_id=%s ORDER BY sku""", (event.order_id,))
            items = [{"sku":sku,"quantity":quantity,"unit_price_satang":price}
                     for sku,quantity,price in cursor.fetchall()]
            _, fingerprint, total = order_binding(order["owner"],event.order_id,items)
            if fingerprint != event.order_fingerprint or total != order["total_satang"]:
                raise IntegrityFailure("order_integrity")
            cursor.execute("SELECT * FROM lab007.processed_events WHERE order_id=%s",
                           (event.order_id,))
            processed = row(cursor)
            if order["state"] != "accepted":
                if (processed is None or processed["event_id"] != event.event_id or
                        processed["order_fingerprint"] != event.order_fingerprint or
                        processed["outcome"] != order["state"]):
                    raise IntegrityFailure("terminal_ledger_mismatch")
                cursor.execute("""SELECT sku,units,unit_price_satang FROM lab007.reservations
                    WHERE order_id=%s ORDER BY sku""", (event.order_id,))
                actual = [tuple(value) for value in cursor.fetchall()]
                expected = [(i["sku"],i["quantity"],i["unit_price_satang"]) for i in items]
                if actual != (expected if order["state"]=="confirmed" else []):
                    raise IntegrityFailure("reservation_integrity")
                return {"state":order["state"],"disposition":"duplicate"}
            if processed is not None:
                raise IntegrityFailure("unexpected_processed_ledger")
            stock = {}
            # Lock every product in canonical SKU order before changing any stock.
            for item in items:
                cursor.execute("SELECT available FROM lab007.products WHERE sku=%s FOR UPDATE",
                               (item["sku"],))
                value = cursor.fetchone()
                if value is None:
                    raise IntegrityFailure("missing_product")
                stock[item["sku"]] = value[0]
            outcome = "confirmed" if all(stock[i["sku"]] >= i["quantity"]
                                         for i in items) else "rejected"
            if outcome == "confirmed":
                for index,item in enumerate(items):
                    cursor.execute("""UPDATE lab007.products SET available=available-%s
                        WHERE sku=%s AND available >= %s""",
                        (item["quantity"],item["sku"],item["quantity"]))
                    if cursor.rowcount != 1:
                        raise IntegrityFailure("stock_update_conflict")
                    cursor.execute("""INSERT INTO lab007.reservations
                        (order_id,sku,units,unit_price_satang) VALUES (%s,%s,%s,%s)""",
                        (event.order_id,item["sku"],item["quantity"],item["unit_price_satang"]))
                    if fail_after_write and index == 0:
                        # Test-only/sandbox injection; transaction rolls back all writes.
                        raise RuntimeError("intentional_sql_rollback")
            cursor.execute("""INSERT INTO lab007.processed_events
                (event_id,order_id,order_fingerprint,outcome) VALUES (%s,%s,%s,%s)""",
                (event.event_id,event.order_id,event.order_fingerprint,outcome))
            cursor.execute("""UPDATE lab007.orders SET state=%s,safe_reason=%s,
                finished_at=clock_timestamp() WHERE order_id=%s""",
                (outcome,None if outcome=="confirmed" else "insufficient_stock",event.order_id))
            return {"state":outcome,"disposition":"processed"}

    def stock_snapshot(self):
        with self.transaction() as cursor:
            cursor.execute("""SELECT p.sku,p.initial_stock,p.available,
                COALESCE(SUM(r.units),0) AS reserved
                FROM lab007.products p LEFT JOIN lab007.reservations r ON r.sku=p.sku
                GROUP BY p.sku ORDER BY p.sku""")
            columns = [item[0] for item in cursor.description]
            return [dict(zip(columns,value)) for value in cursor.fetchall()]

    def catalog(self):
        with self.transaction() as cursor:
            cursor.execute("""SELECT sku,unit_price_satang,available
                FROM lab007.products ORDER BY sku LIMIT 50""")
            return all_rows(cursor)

    def list_owned(self, owner, *, limit=20, cursor=None):
        return self._list_orders(owner_name(owner),limit,cursor)

    def list_operator(self, *, limit=20, cursor=None):
        # App must authorize operator before calling this service-level interface.
        return self._list_orders(None,limit,cursor)

    def _list_orders(self, owner, limit, cursor_value):
        limit=page_limit(limit)
        position=decode_cursor(cursor_value)
        conditions,parameters=[],[]
        if owner is not None:
            conditions.append("owner=%s")
            parameters.append(owner)
        if position is not None:
            conditions.append("(created_at,order_id)<(%s,%s)")
            parameters.extend(position)
        where=" WHERE "+" AND ".join(conditions) if conditions else ""
        with self.transaction() as cursor:
            cursor.execute("""SELECT order_id,owner,state,safe_reason,total_satang,
                created_at,finished_at FROM lab007.orders"""+where+
                " ORDER BY created_at DESC,order_id DESC LIMIT %s",tuple(parameters+[limit+1]))
            return page(all_rows(cursor),limit,"order_id")
