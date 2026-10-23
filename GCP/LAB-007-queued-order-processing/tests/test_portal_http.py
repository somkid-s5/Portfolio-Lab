import copy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

from werkzeug.security import generate_password_hash
from werkzeug.exceptions import InternalServerError

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from auth_config import HASH_METHOD
from portal_http import create_app
from orders import Conflict,IntegrityFailure
from pagination import encode_cursor

BASE="https://portal.test"
ORDER="a"*32
EVENT="b"*32
KEY="c"*32
PASSWORDS={"alice":"alice-demo-only","bob":"bob-demo-only","operator":"operator-demo-only"}


class PortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth={"session_key":"f"*64,"users":{
            name:{"password_hash":generate_password_hash(password,method=HASH_METHOD,salt_length=16),
                  "role":"operator" if name=="operator" else "customer"}
            for name,password in PASSWORDS.items()}}

    def setUp(self):
        self.orders,self.outbox,self.health=Mock(),Mock(),Mock()
        self.records=[]
        self.record={"order_id":ORDER,"owner":"alice","state":"accepted","safe_reason":None,
            "total_satang":12500,"created_at":datetime(2026,10,24,tzinfo=timezone.utc),
            "finished_at":None,"order_fingerprint":"d"*64,"private_field":"private-secret",
            "items":[{"sku":"BOOK-01","quantity":1,"unit_price_satang":12500,
                      "token":"private-secret"}],
            "dispatch":{"event_id":EVENT,"state":"pending","epoch":0,"attempts":0,
                        "last_outcome":None,"published_at":None,"lease_token":"private-secret",
                        "payload":"private-secret"}}
        self.out_record={"event_id":EVENT,"order_id":ORDER,"state":"pending","epoch":0,
            "attempts":0,"last_outcome":None,"created_at":self.record["created_at"],
            "published_at":None,"lease_until":None,"payload_sha256":"e"*64,
            "order_state":"accepted","owner":"alice","order_fingerprint":"d"*64,
            "lease_token":"private-secret","payload":"private-secret"}
        self.orders.catalog.return_value=[{"sku":"BOOK-01","unit_price_satang":12500,"available":200}]
        self.orders.create.return_value={"order_id":ORDER,"state":"accepted","replayed":False}
        self.orders.read_owned.side_effect=lambda owner,key:(
            copy.deepcopy(self.record) if owner=="alice" and key==ORDER else None)
        self.orders.list_owned.return_value={"items":[self.record],"next_cursor":None}
        self.orders.list_operator.return_value={"items":[self.record],"next_cursor":None}
        self.outbox.list_operator.return_value={"items":[self.out_record],"next_cursor":None}
        self.outbox.read_operator.return_value=self.out_record
        self.app=create_app(self.orders,self.outbox,copy.deepcopy(self.auth),
                           database_health=self.health,emit=self.records.append)
        self.client=self.app.test_client()

    def get(self,path):
        return self.client.get(path,base_url=BASE)

    def post(self,path,body,token=None,**kwargs):
        if token is None:
            token=self.get("/api/session").json["csrf"]
        return self.client.post(path,json=body,headers={"X-CSRF-Token":token},
                                base_url=BASE,**kwargs)

    def login(self,name="alice"):
        response=self.post("/api/login",{"username":name,"password":PASSWORDS[name]})
        self.assertEqual(response.status_code,200)
        return response.json["csrf"]

    def order_body(self):
        return {"idempotency_key":KEY,"items":[{"sku":"BOOK-01","quantity":1}]}

    def test_session_cookie_flags_hashes_hidden_and_login_rotates_csrf(self):
        initial=self.get("/api/session")
        self.assertIsNone(initial.json["user"])
        old=initial.json["csrf"]
        self.assertEqual(len(old),64)
        for flag in ("Secure","HttpOnly","SameSite=Lax"):
            self.assertIn(flag,initial.headers["Set-Cookie"])
        current=self.login()
        self.assertNotEqual(old,current)
        self.assertEqual(self.get("/api/session").json["role"],"customer")
        self.assertNotIn("password",self.get("/api/session").get_data(as_text=True))
        self.assertFalse(self.app.config["SESSION_REFRESH_EACH_REQUEST"])
        self.assertEqual(self.app.config["PERMANENT_SESSION_LIFETIME"].total_seconds(),1800)

    def test_login_and_mutations_require_csrf_and_wrong_login_is_generic(self):
        response=self.client.post("/api/login",json={"username":"alice","password":PASSWORDS["alice"]},
                                  base_url=BASE)
        self.assertEqual(response.status_code,403)
        for username in ("alice","unknown"):
            response=self.post("/api/login",{"username":username,"password":"wrong-password"})
            self.assertEqual((response.status_code,response.json["error"]),(401,"invalid_login"))
        old=self.get("/api/session").json["csrf"]
        self.login()
        self.assertEqual(self.post("/api/orders",self.order_body(),token=old).status_code,403)
        self.assertEqual(self.client.post("/api/orders",json=self.order_body(),
            headers={"X-CSRF-Token":"é"},base_url=BASE).status_code,403)

    def test_customer_create_replay_and_session_owner_binding(self):
        self.login()
        response=self.post("/api/orders",self.order_body())
        self.assertEqual((response.status_code,response.json["order_id"]),(202,ORDER))
        owner,raw=self.orders.create.call_args.args
        self.assertEqual(owner,"alice")
        self.assertEqual(json.loads(raw),self.order_body())
        self.orders.create.return_value={"order_id":ORDER,"state":"confirmed","replayed":True}
        response=self.post("/api/orders",self.order_body())
        self.assertEqual((response.status_code,response.json["replayed"]),(200,True))

    def test_owner_price_unknown_fields_and_duplicate_json_are_rejected_before_repository(self):
        self.login()
        invalid=[{**self.order_body(),"owner":"bob"},
                 {**self.order_body(),"price":1},
                 {"idempotency_key":KEY,"items":[{"sku":"BOOK-01","quantity":1,
                                                 "unit_price_satang":1}]}]
        for value in invalid:
            self.assertEqual(self.post("/api/orders",value).status_code,400)
        csrf=self.get("/api/session").json["csrf"]
        response=self.client.post("/api/orders",data=b'{"items":[],"items":[]}',
            headers={"X-CSRF-Token":csrf},content_type="application/json",base_url=BASE)
        self.assertEqual(response.status_code,400)
        self.orders.create.assert_not_called()

    def test_foreign_order_is_404_and_customer_cannot_use_operator_views(self):
        self.login("bob")
        self.assertEqual(self.get("/api/orders/"+ORDER).status_code,404)
        self.assertEqual(self.get("/api/orders/not-an-id").status_code,404)
        self.assertEqual(self.get("/api/operator/orders").status_code,403)
        self.assertEqual(self.get("/api/operator/outbox").status_code,403)
        self.assertEqual(self.get("/api/operator/outbox/"+EVENT).status_code,403)
        self.orders.list_operator.assert_not_called()
        self.outbox.list_operator.assert_not_called()

    def test_operator_can_inspect_safe_views_but_cannot_create_customer_order(self):
        self.login("operator")
        self.assertEqual(self.get("/api/operator/orders").status_code,200)
        response=self.get("/api/operator/outbox/"+EVENT)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["payload_sha256"],"e"*64)
        self.assertNotIn("lease_token",response.json)
        self.assertNotIn("payload",response.json)
        self.assertNotIn("private-secret",response.get_data(as_text=True))
        self.assertEqual(self.post("/api/orders",self.order_body()).status_code,403)
        self.orders.create.assert_not_called()

    def test_owner_detail_projection_and_cursor_are_bounded(self):
        self.login()
        response=self.get("/api/orders/"+ORDER)
        self.assertEqual(response.json["created_at"],"2026-10-24T00:00:00Z")
        self.assertNotIn("order_fingerprint",response.json)
        self.assertNotIn("private-secret",response.get_data(as_text=True))
        cursor=encode_cursor(self.record["created_at"],ORDER)
        self.assertEqual(self.get("/api/orders?limit=2&cursor="+cursor).status_code,200)
        self.orders.list_owned.assert_called_with("alice",limit=2,cursor=cursor)
        for query in ("owner=bob","limit=1&limit=2","limit=21","limit=0","limit=True",
                      "cursor=https://attacker.example","limit="+("1"*1025)):
            self.assertEqual(self.get("/api/orders?"+query).status_code,400)

    def test_role_from_cookie_field_does_not_override_server_configuration(self):
        self.login()
        with self.client.session_transaction(base_url=BASE) as saved:
            saved["role"]="operator"
        self.assertEqual(self.get("/api/session").json["role"],"customer")
        self.assertEqual(self.get("/api/operator/orders").status_code,403)

    def test_logout_clears_current_client_and_rotates_nonce_without_claiming_global_revocation(self):
        self.login()
        old=self.get("/api/session").json["csrf"]
        response=self.post("/api/logout",{})
        self.assertEqual(response.status_code,200)
        self.assertNotEqual(response.json["csrf"],old)
        self.assertEqual(self.get("/api/orders").status_code,401)
        self.assertIsNone(self.get("/api/session").json["user"])

    def test_dependency_conflict_integrity_and_framework_errors_are_safe(self):
        self.login()
        self.orders.create.side_effect=Conflict("private-secret")
        response=self.post("/api/orders",self.order_body())
        self.assertEqual((response.status_code,response.json["error"]),(409,"order_conflict"))
        for error in (RuntimeError("private-secret"),IntegrityFailure("private-secret"),
                      InternalServerError(description="private-secret")):
            self.orders.catalog.side_effect=error
            response=self.get("/api/catalog")
            self.assertEqual(response.status_code,503)
            self.assertNotIn("private-secret",response.get_data(as_text=True))

    def test_anonymous_body_limit_health_and_log_sanitization(self):
        self.assertEqual(self.get("/api/catalog").status_code,401)
        self.login()
        csrf=self.get("/api/session").json["csrf"]
        response=self.client.post("/api/orders?key=private-secret",data=b"x"*4097,
            headers={"X-CSRF-Token":csrf,"X-Request-ID":"private-secret"},
            content_type="application/json",base_url=BASE)
        self.assertEqual(response.status_code,413)
        self.health.side_effect=RuntimeError("private-secret")
        self.assertEqual(self.get("/livez").status_code,200)
        self.assertEqual(self.get("/healthz").status_code,503)
        logs=json.dumps(self.records)
        self.assertNotIn("private-secret",logs)
        self.assertNotIn(csrf,logs)
        self.assertNotIn(PASSWORDS["alice"],logs)

    def test_invalid_auth_configuration_fails_at_startup(self):
        for mutate in (
            lambda v:v.update(session_key="short"),
            lambda v:v["users"]["alice"].update(role="operator"),
            lambda v:v["users"]["alice"].update(password_hash="plaintext"),
            lambda v:v["users"].pop("bob")):
            auth=copy.deepcopy(self.auth)
            mutate(auth)
            with self.assertRaises(ValueError):
                create_app(self.orders,self.outbox,auth,database_health=self.health)


if __name__=="__main__":
    unittest.main()
