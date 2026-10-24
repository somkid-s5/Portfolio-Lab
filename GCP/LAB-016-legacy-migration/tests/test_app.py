from __future__ import annotations
import json
import os
from datetime import datetime
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import psycopg
from app.main import Handler

ROOT=Path(__file__).resolve().parents[1]
BASE_ROWS=[
 (1001,"LAB16-ORD-1001","Mali",12500,"PAID","2026-01-10T09:00:00Z"),
 (1002,"LAB16-ORD-1002","Niran",45900,"NEW","2026-01-10T09:05:00Z"),
 (1003,"LAB16-ORD-1003","Dao",7800,"CANCELLED","2026-01-10T09:10:00Z"),
 (1004,"LAB16-ORD-1004","Krit",21300,"PAID","2026-01-10T09:15:00Z"),
 (1005,"LAB16-ORD-1005","Ploy",9900,"NEW","2026-01-10T09:20:00Z"),
]

class OrdersHTTPTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
  cls.base=f"http://127.0.0.1:{cls.server.server_port}"
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=3)
 def setUp(self):
  os.environ["ALLOW_WRITES"]="true"; os.environ["BACKEND_NAME"]="ci"
  with psycopg.connect(os.environ["PG_DSN"]) as conn:
   conn.execute("TRUNCATE public.orders RESTART IDENTITY")
   for row in BASE_ROWS:
    conn.execute("INSERT INTO public.orders(id,order_ref,customer_name,amount_cents,status,created_at) VALUES (%s,%s,%s,%s,%s,%s)", (*row[:5], datetime.fromisoformat(row[5].replace("Z","+00:00"))))
   conn.execute("SELECT setval(pg_get_serial_sequence('public.orders','id'),1005,true)")
 def request(self,path,method="GET",payload=None):
  data=None if payload is None else json.dumps(payload).encode()
  req=Request(self.base+path,data=data,method=method,headers={"Content-Type":"application/json"} if data is not None else {})
  try:
   with urlopen(req,timeout=3) as response: return response.status,json.loads(response.read())
  except HTTPError as exc: return exc.code,json.loads(exc.read())
 def test_health_does_not_depend_on_database_and_readiness_does(self):
  status,body=self.request("/healthz"); self.assertEqual(status,200); self.assertEqual(body["backend"],"ci")
  status,body=self.request("/readyz"); self.assertEqual(status,200); self.assertEqual(body["status"],"ready")
 def test_order_list_and_business_summary(self):
  status,body=self.request("/v1/orders?limit=3"); self.assertEqual(status,200); self.assertEqual(body["count"],3)
  self.assertEqual(body["orders"][0]["order_ref"],"LAB16-ORD-1005")
  status,body=self.request("/ops/summary"); self.assertEqual(status,200)
  self.assertEqual(body["count"],5); self.assertEqual(body["total_amount_cents"],97400)
  self.assertEqual(body["max_id"],1005); self.assertEqual(body["sequence_last_value"],1005)
 def test_create_is_idempotency_safe_and_validated(self):
  payload={"order_ref":"LAB16-CI-1","customer_name":"Test User","amount_cents":1250}
  status,body=self.request("/v1/orders","POST",payload); self.assertEqual(status,201); self.assertEqual(body["order"]["id"],1006)
  status,body=self.request("/v1/orders","POST",payload); self.assertEqual(status,409); self.assertEqual(body["error"],"order_ref_already_exists")
  status,body=self.request("/v1/orders","POST",{**payload,"amount_cents":True}); self.assertEqual(status,400)
 def test_write_freeze_rejects_mutation_but_keeps_reads(self):
  os.environ["ALLOW_WRITES"]="false"
  status,body=self.request("/v1/orders","POST",{"order_ref":"LAB16-FROZEN","customer_name":"Test","amount_cents":900})
  self.assertEqual(status,503); self.assertEqual(body["error"],"writes_frozen")
  status,body=self.request("/v1/orders"); self.assertEqual(status,200); self.assertEqual(body["count"],5)
 def test_errors_are_bounded_json(self):
  status,body=self.request("/v1/orders?limit=1000"); self.assertEqual(status,400); self.assertEqual(body["error"],"limit_out_of_range")
  status,body=self.request("/unknown"); self.assertEqual(status,404); self.assertEqual(body["error"],"not_found")

if __name__=="__main__": unittest.main()
