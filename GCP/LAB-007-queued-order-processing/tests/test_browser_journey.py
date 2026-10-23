"""Real Chrome/HTTPS/PG journey; Queue transport and IAM are explicit test doubles."""
import base64
import hashlib
import http.cookiejar
import importlib.util
import ssl
import urllib.request
from unittest.mock import patch
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/"app"))
from auth_config import HASH_METHOD
from database import make_pool
from dispatch import Dispatcher
from orders import Orders
from outbox import Outbox
from portal_http import create_app
from replay import Replay
from queue_http import create_worker
from test_sql import connection  # Do not import SQLTests: schema already initialized by earlier CI step.


class QuietHandler(WSGIRequestHandler):
    def log(self,*args,**kwargs):
        pass


def admin(sql,parameters=()):
    con=connection()
    try:
        cur=con.cursor()
        try:
            cur.execute(sql,parameters)
            result=cur.fetchall() if cur.description else None
            con.commit()
            return result
        finally:
            cur.close()
    finally:
        con.close()


class BrowserJourneyTests(unittest.TestCase):
    def test_lost_create_reply_reload_same_key_and_duplicate_delivery(self):
        admin("""TRUNCATE lab007.operator_actions,lab007.reservations,
            lab007.processed_events,lab007.outbox,lab007.order_items,lab007.orders""")
        admin("UPDATE lab007.products SET available=initial_stock")
        admin("UPDATE lab007.products SET unit_price_satang=12500 WHERE sku='BOOK-01'")
        engines=[]
        def repository(role,size,kind):
            engine=make_pool(lambda:connection(role),size)
            engines.append(engine)
            return kind(engine.raw_connection)
        api=repository("order_api",2,Orders)
        api_outbox=Outbox(engines[0].raw_connection)
        worker=repository("order_worker",2,Orders)
        outbox=repository("outbox_dispatcher",1,Outbox)
        password="disposable-browser-password"
        auth={"session_key":"a"*64,"users":{
            name:{"role":"operator" if name=="operator" else "customer",
                  "password_hash":generate_password_hash(password,method=HASH_METHOD,salt_length=16)}
            for name in ("alice","bob","operator")}}
        app=create_app(api,api_outbox,auth,database_health=api.health,emit=lambda _:None,replay=Replay(engines[0].raw_connection))
        subscription="projects/demo-lab007/subscriptions/lab007-orders-push"
        receiver=create_worker(worker,subscription,database_health=worker.health)
        class QueueDouble:
            deliveries=0
            def publish(self,payload):
                # Both invocations call real HTTP parsing and real PG transactions.
                for _ in range(2):
                    self.deliveries+=1
                    with receiver.test_client() as client:
                        response=client.post("/events/orders",json={
                            "subscription":subscription,"message":{
                                "data":base64.b64encode(payload).decode("ascii"),
                                "messageId":"ci-message-"+str(self.deliveries)}})
                        if response.status_code!=204:
                            raise AssertionError("worker did not acknowledge test delivery")
                return "ci-publish-ack"
        queue=QueueDouble()
        dispatcher=Dispatcher(outbox,queue)
        driver=server=thread=None
        try:
            with tempfile.TemporaryDirectory() as folder:
                cert,key=Path(folder)/"cert.pem",Path(folder)/"key.pem"
                subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes",
                    "-keyout",str(key),"-out",str(cert),"-days","1","-subj","/CN=localhost",
                    "-addext","subjectAltName=IP:127.0.0.1,DNS:localhost"],
                    check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
                server=make_server("127.0.0.1",0,app,threaded=True,
                    ssl_context=(str(cert),str(key)),request_handler=QuietHandler)
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                options=webdriver.ChromeOptions()
                for argument in ("--headless=new","--no-sandbox","--disable-dev-shm-usage","--window-size=1400,1100"):
                    options.add_argument(argument)
                options.set_capability("acceptInsecureCerts",True)  # Only disposable CI loopback certificate.
                driver=webdriver.Chrome(options=options)
                driver.set_page_load_timeout(20)
                wait=WebDriverWait(driver,25)
                driver.get(f"https://127.0.0.1:{server.server_port}")
                wait.until(lambda d:"ยังไม่ได้เข้าสู่ระบบ" in d.find_element(By.ID,"identity").text)
                driver.find_element(By.ID,"password").send_keys(password)
                driver.find_element(By.CSS_SELECTOR,"#login-form button").click()
                wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,"#catalog-body input"))==3)
                wait.until(lambda d:not d.find_element(By.ID,"submit-order").get_attribute("disabled"))
                for sku,quantity in (("BOOK-01",2),("USB-01",1)):
                    field=driver.find_element(By.CSS_SELECTOR,'input[data-sku="'+sku+'"]')
                    field.clear()
                    field.send_keys(str(quantity))
                driver.execute_script("""
                    const nativeFetch=window.fetch.bind(window);
                    window.fetch=async (url,options)=>{
                      const response=await nativeFetch(url,options);
                      if(url==='/api/orders'&&options?.method==='POST'){
                        window.fetch=nativeFetch;
                        throw new TypeError('CI simulated lost create reply');
                      }
                      return response;
                    };
                """)
                driver.find_element(By.ID,"submit-order").click()
                wait.until(lambda d:"ยังยืนยันผลไม่ได้" in d.find_element(By.ID,"message").text)
                pending=json.loads(driver.execute_script("return sessionStorage.getItem('lab007.pending.alice');"))
                self.assertNotIn("order_id",pending)
                self.assertEqual(admin("SELECT count(*) FROM lab007.orders")[0][0],1)
                self.assertEqual(admin("SELECT count(*) FROM lab007.outbox")[0][0],1)
                original_id=admin("SELECT order_id FROM lab007.orders")[0][0]
                driver.refresh()
                wait.until(lambda d:len(d.find_elements(By.CSS_SELECTOR,"#catalog-body input"))==3)
                wait.until(lambda d:not d.find_element(By.ID,"submit-order").get_attribute("disabled"))
                self.assertEqual(driver.find_element(By.CSS_SELECTOR,'input[data-sku="BOOK-01"]').get_attribute("value"),"2")
                # Startup must not submit a new order. Explicit same-key retry only.
                self.assertEqual(admin("SELECT count(*) FROM lab007.orders")[0][0],1)
                driver.find_element(By.ID,"submit-order").click()
                wait.until(lambda d:original_id in d.find_element(By.ID,"order-detail").text)
                replay=json.loads(driver.execute_script("return sessionStorage.getItem('lab007.pending.alice');"))
                self.assertEqual((replay["key"],replay["order_id"]),(pending["key"],original_id))
                result=dispatcher.drain()
                self.assertEqual((result["status"],result["publish_acks"],result["finished"]),(200,1,1))
                wait.until(lambda d:'"state": "confirmed"' in d.find_element(By.ID,"order-detail").text)
                wait.until(lambda d:d.execute_script("return sessionStorage.getItem('lab007.pending.alice');") is None)
                self.assertEqual(queue.deliveries,2)
                self.assertEqual(admin("SELECT count(*) FROM lab007.orders")[0][0],1)
                self.assertEqual(admin("SELECT count(*) FROM lab007.processed_events")[0][0],1)
                self.assertEqual(admin("SELECT count(*) FROM lab007.reservations")[0][0],2)
                self.assertEqual(admin("SELECT total_satang,state FROM lab007.orders")[0], [34900,"confirmed"])
                stock=dict(admin("SELECT sku,available FROM lab007.products"))
                self.assertEqual(stock,{"BOOK-01":198,"USB-01":199,"LAST-01":1})
                self.assertEqual(driver.find_element(By.ID,"password").get_attribute("value"),"")
                stored=driver.execute_script("return JSON.stringify({...sessionStorage});")
                self.assertNotIn(password,stored)
                self.assertNotIn("csrf",stored.lower())
                # Sending again without explicitly starting a new draft must not buy twice.
                driver.find_element(By.ID,"submit-order").click()
                wait.until(lambda d:"กดเริ่มรายการใหม่" in d.find_element(By.ID,"message").text)
                self.assertEqual(admin("SELECT count(*) FROM lab007.orders")[0][0],1)
                preview=Path("lab007-previews/ui-ci.png")
                preview.parent.mkdir(exist_ok=True)
                height=min(2800,int(driver.execute_script("return document.documentElement.scrollHeight"))+200)
                driver.set_window_size(1400,height)
                self.assertTrue(driver.execute_script("return window.innerHeight>=document.documentElement.scrollHeight;"))
                self.assertTrue(driver.save_screenshot(str(preview)))
                # Real browser account switch must not retain Alice's visible records.
                def login_as(name):
                    driver.find_element(By.ID,"logout").click()
                    wait.until(lambda d:d.find_element(By.ID,"login-panel").is_displayed())
                    wait.until(lambda d:not d.find_element(By.CSS_SELECTOR,"#login-form button").get_attribute("disabled"))
                    field=driver.find_element(By.ID,"username")
                    field.clear()
                    field.send_keys(name)
                    driver.find_element(By.ID,"password").send_keys(password)
                    driver.find_element(By.CSS_SELECTOR,"#login-form button").click()
                    wait.until(lambda d:name+" · " in d.find_element(By.ID,"identity").text)
                login_as("bob")
                wait.until(lambda d:"เลือกสินค้าหรือตรวจคำขอเดิม" in d.find_element(By.ID,"message").text)
                self.assertNotIn(original_id,driver.find_element(By.ID,"orders-body").text)
                self.assertNotIn(original_id,driver.find_element(By.ID,"order-detail").text)
                statuses=driver.execute_async_script("""
                    const done=arguments[arguments.length-1],id=arguments[0];
                    Promise.all(['/api/orders/'+id,'/api/operator/outbox'].map(
                      path=>fetch(path).then(r=>r.status))).then(done);
                """,original_id)
                self.assertEqual(statuses,[404,403])
                login_as("operator")
                wait.until(lambda d:original_id in d.find_element(By.ID,"operator-outbox-body").text)
                wait.until(lambda d:not d.find_element(By.ID,"logout").get_attribute("disabled"))
                self.assertFalse(driver.find_element(By.ID,"customer").is_displayed())
                driver.find_element(By.CSS_SELECTOR,"#operator-outbox-body button").click()
                wait.until(lambda d:'"payload_sha256"' in d.find_element(By.ID,"operator-detail").text)
                detail=driver.find_element(By.ID,"operator-detail").text
                self.assertNotIn('"payload":',detail)
                self.assertNotIn("lease_token",detail)
                height=min(2800,int(driver.execute_script("return document.documentElement.scrollHeight"))+200)
                driver.set_window_size(1400,height)
                self.assertTrue(driver.execute_script("return window.innerHeight>=document.documentElement.scrollHeight;"))
                self.assertTrue(driver.save_screenshot("lab007-previews/operator-ci.png"))
                # Real operator client HTTPS/cookies/CSRF -> real Portal -> real PG.
                # Only the origin allowlist is replaced for this trusted loopback CA.
                spec=importlib.util.spec_from_file_location("ci_operator_client",LAB/"scripts/operator-replay.py")
                cli=importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cli)
                origin=f"https://127.0.0.1:{server.server_port}"
                bundle=Path(folder)/"demo-logins.json"
                bundle.write_bytes(cli.canonical({"operator":{"password":password,"role":"operator"}}))
                bundle.chmod(0o600)
                event_id=admin("SELECT event_id FROM lab007.outbox")[0][0]
                digest=hashlib.sha256(b"explicit-ci-transport-double-not-live-DLQ").hexdigest()
                trusted=urllib.request.build_opener(cli.NoRedirect(),
                    urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=str(cert))),
                    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                class LoseReplayReply:
                    lost=False
                    def open(self,request,timeout):
                        response=trusted.open(request,timeout=timeout)
                        if request.full_url.endswith("/replay") and not self.lost:
                            self.lost=True
                            response.read(65537)
                            response.close()
                            raise TimeoutError("CI lost replay reply after server committed")
                        return response
                with patch.object(cli,"origin_url",return_value=origin):
                    request_body=cli.journal(Path(folder)/"replay.json",origin,event_id,digest,"delivery_restored")
                    client=cli.Portal(origin,opener=LoseReplayReply())
                    client.login(bundle)
                    with self.assertRaisesRegex(ValueError,"outcome_unconfirmed_reuse_journal"):
                        client.prepare(event_id,request_body)
                    resolved=client.prepare(event_id,request_body)
                self.assertEqual((resolved["outcome"],resolved["replayed"]),("already_resolved",True))
                self.assertEqual(admin("SELECT count(*) FROM lab007.operator_actions")[0][0],1)
                self.assertEqual(admin("SELECT count(*) FROM lab007.orders")[0][0],1)
                self.assertEqual(admin("SELECT count(*) FROM lab007.processed_events")[0][0],1)
                self.assertEqual(dict(admin("SELECT sku,available FROM lab007.products")),stock)
        finally:
            if driver is not None:driver.quit()
            if server is not None:server.shutdown()
            if thread is not None:thread.join(timeout=5)
            for engine in engines:engine.dispose()


if __name__=="__main__":
    unittest.main()
