"""Audited canonical replay. Portal authorizes operator; this role is service-level."""
import hashlib
import re

from order_domain import Rejected,event_bytes,identifier,key_hash,order_binding,owner_name,parse_event,read_json
from orders import Orders,Conflict,IntegrityFailure,row

REASONS={"dependency_restored","poison_removed","dispatch_restored","delivery_restored"}


def replay_request(body):
    value=read_json(body)
    if set(value)!={"idempotency_key","source_digest","reason"}:
        raise Rejected("invalid_replay_fields")
    identifier(value["idempotency_key"])
    if not isinstance(value["source_digest"],str) or not re.fullmatch(r"[a-f0-9]{64}",value["source_digest"]):
        raise Rejected("invalid_source_digest")
    if not isinstance(value["reason"],str) or value["reason"] not in REASONS:
        raise Rejected("invalid_replay_reason")
    return value


class Replay(Orders):
    def prepare(self,operator,event_id,body):
        # Operator value is from authenticated server session, never request JSON.
        operator,event_id=owner_name(operator),identifier(event_id)
        request=replay_request(body)
        scoped=hashlib.sha256(("replay:"+key_hash(operator,request["idempotency_key"])).encode("ascii")).hexdigest()
        advisory=int.from_bytes(bytes.fromhex(scoped)[:8],"big",signed=True)
        with self.transaction() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)",(advisory,))
            cursor.execute("""SELECT event_id,source_digest,reason,epoch,outcome
                FROM lab007.operator_actions WHERE operator_name=%s AND key_hash=%s""",(operator,scoped))
            previous=row(cursor)
            if previous is not None:
                if (previous["event_id"]!=event_id or previous["source_digest"]!=request["source_digest"]
                        or previous["reason"]!=request["reason"]):
                    raise Conflict("replay_key_conflict")
                return {**previous,"replayed":True}
            # Only outbox is locked. Worker locks orders, but never locks outbox,
            # so replay does not introduce an inverse order/outbox lock cycle.
            event,order,processed,reservations,items,fingerprint=self._checked(cursor,event_id)
            epoch=event["epoch"]
            if order["state"] in ("confirmed","rejected"):
                self._terminal(event_id,order,processed,reservations,items,fingerprint)
                outcome="already_resolved"
            else:
                # A worker may have committed between these reads; a retry is safe.
                # Never interpret an inconsistent snapshot as permission to mutate business data.
                if processed is not None or reservations:
                    raise IntegrityFailure("processing_changed_retry")
                if event["state"]=="publishing" and event["lease_live"]:
                    raise Conflict("dispatch_in_flight")
                if event["last_outcome"]=="invalid_canonical":
                    raise IntegrityFailure("integrity_quarantine")
                if event["state"]!="pending":
                    if epoch>=2:
                        raise Conflict("replay_budget_exhausted")
                    epoch+=1
                    cursor.execute("""UPDATE lab007.outbox SET state='pending',epoch=%s,attempts=0,
                        lease_token=NULL,lease_until=NULL,published_at=NULL,last_outcome='operator_prepared'
                        WHERE event_id=%s""",(epoch,event_id))
                outcome="prepared"
            cursor.execute("""INSERT INTO lab007.operator_actions
                (operator_name,key_hash,event_id,source_digest,reason,epoch,outcome)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (operator,scoped,event_id,request["source_digest"],request["reason"],epoch,outcome))
            return {"event_id":event_id,"source_digest":request["source_digest"],"reason":request["reason"],
                    "epoch":epoch,"outcome":outcome,"replayed":False}

    def _checked(self,cursor,event_id):
        cursor.execute("""SELECT *,lease_until>clock_timestamp() AS lease_live
            FROM lab007.outbox WHERE event_id=%s FOR UPDATE""",(event_id,))
        event=row(cursor)
        if event is None:
            raise Conflict("unknown_event")
        cursor.execute("SELECT * FROM lab007.orders WHERE order_id=%s",(event["order_id"],))
        order=row(cursor)
        if order is None:
            raise IntegrityFailure("missing_order")
        try:
            payload=event["payload"].encode("ascii")
            parsed=parse_event(payload)
            if (payload!=event_bytes(event_id,order["order_id"],order["order_fingerprint"])
                    or hashlib.sha256(payload).hexdigest()!=event["payload_sha256"]
                    or parsed.event_id!=event_id):
                raise IntegrityFailure("canonical_integrity")
            cursor.execute("""SELECT sku,quantity,unit_price_satang FROM lab007.order_items
                WHERE order_id=%s ORDER BY sku""",(order["order_id"],))
            items=[{"sku":sku,"quantity":quantity,"unit_price_satang":price}
                   for sku,quantity,price in cursor.fetchall()]
            _,fingerprint,total=order_binding(order["owner"],order["order_id"],items)
            if fingerprint!=order["order_fingerprint"] or total!=order["total_satang"]:
                raise IntegrityFailure("order_integrity")
        except (UnicodeError,Rejected):
            raise IntegrityFailure("canonical_integrity") from None
        cursor.execute("SELECT * FROM lab007.processed_events WHERE order_id=%s",(order["order_id"],))
        processed=row(cursor)
        cursor.execute("""SELECT sku,units,unit_price_satang FROM lab007.reservations
            WHERE order_id=%s ORDER BY sku""",(order["order_id"],))
        reservations=[tuple(value) for value in cursor.fetchall()]
        return event,order,processed,reservations,items,fingerprint

    @staticmethod
    def _terminal(event_id,order,processed,reservations,items,fingerprint):
        expected=[(i["sku"],i["quantity"],i["unit_price_satang"]) for i in items]
        if (processed is None or processed["event_id"]!=event_id or
                processed["order_fingerprint"]!=fingerprint or processed["outcome"]!=order["state"] or
                reservations!=(expected if order["state"]=="confirmed" else [])):
            raise IntegrityFailure("terminal_integrity")

    def verify(self,event_id):
        event_id=identifier(event_id)
        with self.transaction() as cursor:
            event,order,processed,reservations,items,fingerprint=self._checked(cursor,event_id)
            terminal=order["state"] in ("confirmed","rejected")
            if terminal:
                self._terminal(event_id,order,processed,reservations,items,fingerprint)
            return {"event_id":event_id,"order_id":order["order_id"],"order_fingerprint":fingerprint,
                    "payload_sha256":event["payload_sha256"],"order_state":order["state"],
                    "terminal_verified":terminal}
