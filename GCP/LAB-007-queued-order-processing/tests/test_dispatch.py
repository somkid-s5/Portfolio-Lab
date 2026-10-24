import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from dispatch import Dispatcher
from order_domain import event_bytes
from orders import Conflict

EVENT="a"*32
ORDER="b"*32
TOKEN="c"*32
PAYLOAD=event_bytes(EVENT,ORDER,"d"*64)


def claim():
    return {"disposition":"claimed","event_id":EVENT,"order_id":ORDER,
            "epoch":0,"attempts":1,"token":TOKEN,"payload":PAYLOAD}


class DispatchTests(unittest.TestCase):
    def setup_pair(self):
        outbox=Mock()
        outbox.claim.side_effect=[claim(),{"disposition":"empty"}]
        publisher=Mock()
        publisher.publish.return_value="synthetic-123"
        return outbox,publisher

    def assert_private(self,result):
        text=json.dumps(result)
        self.assertNotIn(TOKEN,text)
        self.assertNotIn("schema_version",text)
        self.assertNotIn("private-secret",text)

    def test_one_publish_then_finish_without_tokens_or_payloads(self):
        outbox,publisher=self.setup_pair()
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual((result["status"],result["publish_acks"],result["finished"]),(200,1,1))
        self.assertEqual(result["reason"],"empty")
        publisher.publish.assert_called_once_with(PAYLOAD)
        outbox.finish.assert_called_once_with(EVENT,TOKEN,published=True)
        self.assert_private(result)

    def test_publish_error_is_unknown_and_stops_without_tight_retry(self):
        outbox,publisher=self.setup_pair()
        publisher.publish.side_effect=RuntimeError("private-secret")
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual(result["reason"],"publish_unconfirmed")
        self.assertEqual((result["status"],result["finished"]),(503,0))
        outbox.finish.assert_called_once_with(EVENT,TOKEN,published=False)
        self.assertEqual(outbox.claim.call_count,1)
        self.assert_private(result)

    def test_finish_error_does_not_try_false_release(self):
        outbox,publisher=self.setup_pair()
        outbox.finish.side_effect=RuntimeError("private-secret")
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual(result["reason"],"finish_unconfirmed")
        self.assertEqual((result["publish_acks"],result["finished"]),(1,0))
        outbox.finish.assert_called_once_with(EVENT,TOKEN,published=True)
        self.assert_private(result)

    def test_stale_completion_does_not_mutate_new_claim(self):
        outbox,publisher=self.setup_pair()
        outbox.finish.side_effect=Conflict("stale_dispatch_claim")
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual((result["status"],result["reason"]),(503,"stale_claim"))
        self.assertEqual(outbox.finish.call_count,1)
        self.assert_private(result)

    def test_batch_and_time_limits_are_explicit(self):
        outbox,publisher=self.setup_pair()
        outbox.claim.side_effect=None
        outbox.claim.return_value=claim()
        result=Dispatcher(outbox,publisher,clock=lambda:0).drain()
        self.assertEqual((outbox.claim.call_count,publisher.publish.call_count),(20,20))
        self.assertEqual(result["reason"],"batch_limit")
        state={"time":0}
        outbox,publisher=self.setup_pair()
        def publish(_):
            state["time"]=30
            return "synthetic-123"
        publisher.publish.side_effect=publish
        result=Dispatcher(outbox,publisher,clock=lambda:state["time"]).drain()
        self.assertEqual(outbox.claim.call_count,1)
        self.assertEqual(result["reason"],"budget")

    def test_blocked_rows_are_reported_not_published(self):
        outbox,publisher=self.setup_pair()
        outbox.claim.side_effect=[
            {"disposition":"exhausted","event_id":EVENT},
            {"disposition":"integrity_blocked","event_id":EVENT},
            {"disposition":"empty"}]
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual((result["exhausted"],result["integrity_blocked"]),(1,1))
        publisher.publish.assert_not_called()
        outbox.finish.assert_not_called()
        self.assert_private(result)

    def test_claim_and_release_errors_are_sanitized(self):
        outbox,publisher=self.setup_pair()
        outbox.claim.side_effect=RuntimeError("private-secret")
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual(result["reason"],"claim_unconfirmed")
        self.assert_private(result)
        outbox,publisher=self.setup_pair()
        publisher.publish.side_effect=TimeoutError("private-secret")
        outbox.finish.side_effect=RuntimeError("private-secret")
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual(result["reason"],"release_unconfirmed")
        self.assert_private(result)

    def test_invalid_ack_is_not_logged_or_treated_as_business_success(self):
        outbox,publisher=self.setup_pair()
        publisher.publish.return_value="private-secret with newline\n"
        result=Dispatcher(outbox,publisher).drain()
        self.assertEqual((result["status"],result["publish_acks"]),(503,0))
        self.assert_private(result)


if __name__=="__main__":
    unittest.main()
