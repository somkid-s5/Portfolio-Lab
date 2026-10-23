"""Short SQL claims, fenced completion; publish is performed after claim commits."""
import hashlib
import uuid

from order_domain import Rejected, event_bytes, identifier, parse_event
from orders import Orders, Conflict, row, all_rows
from pagination import decode_cursor,page,page_limit

LEASE_SECONDS = 120
MAX_ATTEMPTS = 10


class Outbox(Orders):
    def claim(self):
        with self.transaction() as cursor:
            cursor.execute("""SELECT o.*, r.order_fingerprint AS expected_fingerprint
                FROM lab007.outbox o JOIN lab007.orders r USING(order_id)
                WHERE o.state='pending'
                   OR (o.state='publishing' AND o.lease_until <= clock_timestamp())
                ORDER BY o.created_at,o.event_id
                LIMIT 1 FOR UPDATE OF o SKIP LOCKED""")
            candidate = row(cursor)
            if candidate is None:
                return {"disposition":"empty"}
            event_id = candidate["event_id"]
            if candidate["attempts"] >= MAX_ATTEMPTS:
                cursor.execute("""UPDATE lab007.outbox
                    SET state='exhausted',lease_token=NULL,lease_until=NULL,
                        last_outcome='dispatch_budget'
                    WHERE event_id=%s""", (event_id,))
                return {"disposition":"exhausted","event_id":event_id}
            valid = False
            try:
                payload = candidate["payload"].encode("ascii")
                event = parse_event(payload)
                valid = (
                    hashlib.sha256(payload).hexdigest() == candidate["payload_sha256"]
                    and event.event_id == event_id
                    and event.order_id == candidate["order_id"]
                    and event.order_fingerprint == candidate["expected_fingerprint"]
                    and payload == event_bytes(event.event_id,event.order_id,event.order_fingerprint))
            except (UnicodeError, Rejected):
                pass
            if not valid:
                cursor.execute("""UPDATE lab007.outbox
                    SET state='exhausted',lease_token=NULL,lease_until=NULL,
                        last_outcome='invalid_canonical'
                    WHERE event_id=%s""", (event_id,))
                return {"disposition":"integrity_blocked","event_id":event_id}
            token = uuid.uuid4().hex
            cursor.execute("""UPDATE lab007.outbox SET state='publishing',
                attempts=attempts+1,lease_token=%s,
                lease_until=clock_timestamp()+(%s * INTERVAL '1 second'),
                last_outcome='claimed'
                WHERE event_id=%s
                RETURNING event_id,order_id,epoch,attempts,lease_until""",
                (token,LEASE_SECONDS,event_id))
            claimed = row(cursor)
            return {**claimed,"disposition":"claimed","token":token,
                    "payload":payload}

    def finish(self, event_id, token, *, published):
        event_id, token = identifier(event_id), identifier(token)
        if type(published) is not bool:
            raise TypeError("explicit_publish_outcome_required")
        with self.transaction() as cursor:
            cursor.execute("""UPDATE lab007.outbox SET state=%s,
                lease_token=NULL,lease_until=NULL,last_outcome=%s,
                published_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END
                WHERE event_id=%s AND state='publishing' AND lease_token=%s
                  AND lease_until > clock_timestamp()
                RETURNING event_id,state,epoch,attempts""",
                ("published" if published else "pending",
                 "published" if published else "publish_unconfirmed",
                 published,event_id,token))
            result = row(cursor)
            if result is None:
                raise Conflict("stale_dispatch_claim")
            return result

    def list_operator(self, *, limit=20, cursor=None):
        limit=page_limit(limit)
        position=decode_cursor(cursor)
        where=" WHERE (created_at,event_id)<(%s,%s)" if position is not None else ""
        parameters=list(position) if position is not None else []
        with self.transaction() as cursor:
            cursor.execute("""SELECT event_id,order_id,state,epoch,attempts,last_outcome,
                created_at,published_at,lease_until FROM lab007.outbox"""+where+
                " ORDER BY created_at DESC,event_id DESC LIMIT %s",tuple(parameters+[limit+1]))
            return page(all_rows(cursor),limit,"event_id")

    def read_operator(self, event_id):
        event_id=identifier(event_id)
        with self.transaction() as cursor:
            cursor.execute("""SELECT o.event_id,o.order_id,o.state,o.epoch,o.attempts,
                o.last_outcome,o.created_at,o.published_at,o.lease_until,o.payload_sha256,
                r.state AS order_state,r.owner,r.order_fingerprint
                FROM lab007.outbox o JOIN lab007.orders r USING(order_id)
                WHERE o.event_id=%s""",(event_id,))
            return row(cursor)
