"""Bounded outbox orchestration. Results contain no token/payload/exception text."""
import re
import time
from orders import Conflict

MAX_EVENTS = 20
DRAIN_SECONDS = 40
OPERATION_RESERVE = 15


class Dispatcher:
    def __init__(self, outbox, publisher, *, clock=time.monotonic):
        self.outbox, self.publisher, self.clock = outbox, publisher, clock

    def drain(self):
        deadline = self.clock() + DRAIN_SECONDS
        result = {"status":200,"reason":"batch_limit","claimed":0,
                  "publish_acks":0,"finished":0,"exhausted":0,
                  "integrity_blocked":0,"events":[]}
        for _ in range(MAX_EVENTS):
            if self.clock() > deadline - OPERATION_RESERVE:
                result["reason"] = "budget"
                break
            try:
                claim = self.outbox.claim()
            except Exception:
                result.update(status=503,reason="claim_unconfirmed")
                break
            disposition = claim.get("disposition")
            if disposition == "empty":
                result["reason"] = "empty"
                break
            if disposition in ("exhausted","integrity_blocked"):
                result[disposition] += 1
                result["events"].append({"event_id":claim["event_id"],
                                         "outcome":disposition})
                continue
            if disposition != "claimed":
                result.update(status=503,reason="invalid_claim")
                break
            result["claimed"] += 1
            record = {"event_id":claim["event_id"],"order_id":claim["order_id"],
                      "epoch":claim["epoch"],"attempts":claim["attempts"]}
            result["events"].append(record)
            try:
                message_id = self.publisher.publish(claim["payload"])
                if not isinstance(message_id,str) or not re.fullmatch(
                        r"[A-Za-z0-9_-]{1,128}",message_id):
                    raise ValueError("invalid_publish_ack")
            except Exception:
                record["publish_ack"] = "unconfirmed"
                try:
                    self.outbox.finish(claim["event_id"],claim["token"],published=False)
                    record["finish"] = "pending"
                    result.update(status=503,reason="publish_unconfirmed")
                except Conflict:
                    record["finish"] = "stale"
                    result.update(status=503,reason="stale_claim")
                except Exception:
                    record["finish"] = "unconfirmed"
                    result.update(status=503,reason="release_unconfirmed")
                break  # No tight retry of the same pending event in this request.
            result["publish_acks"] += 1
            record.update(publish_ack="accepted",message_id=message_id)
            try:
                self.outbox.finish(claim["event_id"],claim["token"],published=True)
            except Conflict:
                record["finish"] = "stale"
                result.update(status=503,reason="stale_claim")
                break
            except Exception:
                # Finish may already have committed. Do not overwrite/release it.
                record["finish"] = "unconfirmed"
                result.update(status=503,reason="finish_unconfirmed")
                break
            result["finished"] += 1
            record["finish"] = "published"
        return result
