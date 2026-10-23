import base64
import copy
import json
from pathlib import Path
import sys
import unittest

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB/"app"))
from order_domain import (Rejected, canonical, create_order, event_bytes, key_hash,
                          order_binding, parse_event, parse_push, read_json)

SUB = "projects/demo-lab007/subscriptions/lab007-orders-worker"
ORDER = "a"*32
EVENT = "b"*32
KEY = "c"*32
FINGERPRINT = "d"*64


class DomainTests(unittest.TestCase):
    def request(self, items=None, **extra):
        return {"idempotency_key": KEY,
                "items": items or [{"sku":"USB-01","quantity":1},
                                  {"sku":"BOOK-01","quantity":2}], **extra}

    def push(self, **extra):
        return {"message":{"messageId":"12345", "data":base64.b64encode(
            event_bytes(EVENT, ORDER, FINGERPRINT)).decode()},
                "subscription":SUB, **extra}

    def reject(self, function, value, *args):
        with self.assertRaises(Rejected):
            function(value, *args)

    def test_create_canonical_sort_fingerprint_and_key_scope(self):
        original = self.request()
        saved = copy.deepcopy(original)
        first = create_order(canonical(original))
        original["items"].reverse()
        second = create_order(canonical(original))
        self.assertEqual(first, second)
        self.assertEqual(first.items, (("BOOK-01",2),("USB-01",1)))
        self.assertEqual(saved["items"][0]["sku"], "USB-01")
        self.assertNotEqual(key_hash("alice",KEY), key_hash("bob",KEY))
        self.assertEqual(key_hash("alice",KEY),key_hash("alice",KEY))

    def test_owner_price_and_unexpected_fields_are_rejected(self):
        for value in [self.request(owner="bob"), self.request(price=0),
                      self.request([{"sku":"BOOK-01","quantity":1,"unit_price_satang":1}])]:
            self.reject(create_order, canonical(value))
        for key in ["", "x"*32, "../"+KEY, True, 123]:
            value=self.request()
            value["idempotency_key"]=key
            self.reject(create_order, canonical(value))

    def test_quantity_sku_duplicates_and_item_bounds(self):
        for quantity in [True,0,4,-1,1.0,"1",None]:
            self.reject(create_order,canonical(self.request([{"sku":"BOOK-01","quantity":quantity}])))
        for sku in ["book", "<script>", "X"*33, None]:
            self.reject(create_order,canonical(self.request([{"sku":sku,"quantity":1}])))
        for items in [[], [{"sku":"BOOK-01","quantity":1}]*2,
                      [{"sku":s,"quantity":1} for s in ["A","B","C"]]]:
            value={"idempotency_key":KEY,"items":items}
            self.reject(create_order,canonical(value))

    def test_json_duplicates_encoding_nan_size_and_depth(self):
        for body in [b'{"a":1,"a":2}', b'{"a":NaN}', b"\xff", b"[]",
                     b"", b"x"*4097, b'{"a":'+b"["*2000+b"]"*2000+b"}"]:
            self.reject(read_json,body)
        with self.assertRaises(TypeError):
            read_json("{}")

    def test_order_binding_contains_owner_prices_order_and_exact_total(self):
        items=[{"sku":"BOOK-01","quantity":2,"unit_price_satang":12500},
               {"sku":"USB-01","quantity":1,"unit_price_satang":9900}]
        normalized, fingerprint, total = order_binding("alice",ORDER,items)
        self.assertEqual(total,34900)
        self.assertEqual(order_binding("alice",ORDER,list(reversed(items))),
                         (normalized,fingerprint,total))
        for owner,order,data in [("bob",ORDER,items),("alice","e"*32,items),
                                ("alice",ORDER,[{**items[0],"unit_price_satang":1},items[1]])]:
            self.assertNotEqual(order_binding(owner,order,data)[1],fingerprint)
        self.reject(order_binding,"alice",ORDER,[{**items[0],"unit_price_satang":True}])

    def test_event_exact_schema_and_immutable_fields(self):
        body=event_bytes(EVENT,ORDER,FINGERPRINT)
        event=parse_event(body)
        self.assertEqual((event.event_id,event.order_id,event.order_fingerprint),
                         (EVENT,ORDER,FINGERPRINT))
        value=json.loads(body)
        for changes in [{"schema_version":99},{"schema_version":True},
                        {"owner":"alice"},{"event_id":"bad"},{"order_fingerprint":"x"*64}]:
            self.reject(parse_event,canonical({**value,**changes}))

    def test_push_roundtrip_message_ids_do_not_change_business_event(self):
        first=parse_push(canonical(self.push(deliveryAttempt=2)),SUB)
        body=self.push()
        body["message"]["messageId"]="67890"
        second=parse_push(canonical(body),SUB)
        self.assertNotEqual(first.message_id,second.message_id)
        self.assertEqual(first.event,second.event)
        self.assertEqual(first.delivery_attempt,2)
        self.assertIsNone(second.delivery_attempt)

    def test_documented_push_aliases_are_accepted_only_when_consistent(self):
        value=self.push()
        value["message"].update({"message_id":"12345",
            "publishTime":"2021-02-26T19:13:55.749Z",
            "publish_time":"2021-02-26T19:13:55.749Z"})
        self.assertEqual(parse_push(canonical(value),SUB).message_id,"12345")
        del value["message"]["messageId"]
        self.assertEqual(parse_push(canonical(value),SUB).message_id,"12345")
        value["message"]["messageId"]="different"
        self.reject(parse_push,canonical(value),SUB)
        value["message"]["messageId"]="12345"
        value["message"]["publish_time"]="different"
        self.reject(parse_push,canonical(value),SUB)

    def test_push_subscription_base64_payload_and_safe_errors(self):
        values=[self.push(subscription="projects/other-project/subscriptions/other-sub"),
                self.push(deliveryAttempt=True),self.push(deliveryAttempt=-1),
                self.push(owner="alice")]
        for data in ["!", "", base64.b64encode(b"x"*4097).decode()]:
            value=self.push()
            value["message"]["data"]=data
            values.append(value)
        for value in values:
            self.reject(parse_push,canonical(value),SUB)
        with self.assertRaises(ValueError):
            parse_push(canonical(self.push()),"https://attacker.example")
        with self.assertRaises(Rejected) as error:
            parse_push(b"x"*65537,SUB)
        self.assertNotIn("xxx",str(error.exception))

    def test_seed_and_fixture_are_synthetic_valid_contracts(self):
        request=create_order((LAB/"fixtures/order-request.json").read_bytes())
        self.assertEqual(len(request.items),2)
        products=json.loads((LAB/"fixtures/catalog.json").read_text())
        self.assertEqual([p["sku"] for p in products],["BOOK-01","LAST-01","USB-01"])
        self.assertEqual(products[1]["initial_stock"],1)
        self.assertTrue(all(type(p["unit_price_satang"]) is int for p in products))


if __name__ == "__main__":
    unittest.main()
