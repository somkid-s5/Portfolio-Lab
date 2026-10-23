"""Real Chrome -> HTTPS Flask -> Firestore emulator -> worker.
Storage and signing are explicit CI test doubles, not GCS verification.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

from flask import request
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "app"))
from firestore_jobs import Jobs
from portal_http import create_app
from processor import Processor, IntegrityFailure


class QuietHandler(WSGIRequestHandler):
    def log(self, *args, **kwargs):
        pass


class BrowserJourneyTests(unittest.TestCase):
    def test_real_browser_resumes_lost_create_reply_without_duplicate_job(self):
        if os.environ.get("FIRESTORE_EMULATOR_HOST") != "127.0.0.1:8086":
            raise RuntimeError("explicit_loopback_emulator_required")
        now = datetime.now(timezone.utc)
        client = firestore.Client(project="demo-lab006", database="lab006-files",
                                  credentials=AnonymousCredentials())
        jobs = Jobs(client, clock=lambda: now)
        owner = "browser_" + uuid.uuid4().hex
        class Objects:
            source = b""
            outputs = {}
            creates = 0
            def read_source(self, name, generation, max_bytes):
                assert generation == "123" and len(self.source) <= max_bytes
                return self.source
            def create_or_verify(self, name, body, **metadata):
                if name in self.outputs and self.outputs[name] != body:
                    raise IntegrityFailure()
                if name not in self.outputs:
                    self.outputs[name] = body
                    self.creates += 1
                return "456"
        objects = Objects()
        processor = Processor(jobs, objects)
        class Access:
            def upload_policy(self, job_id, user):
                jobs.read_owned(job_id, user)
                return {"url": "https://storage.googleapis.com/lab006-ci-double",
                        "fields": {"job_id": job_id, "Content-Type": "text/csv"},
                        "max_bytes": 1048576}
        auth = {"session_key": "s"*64, "users": {
            owner: {"password_hash": generate_password_hash("ci-only-pass"),
                    "role": "customer"}}}
        app = create_app(jobs, Access(), auth, clock=lambda: now, emit=lambda _: None)

        @app.post("/__ci_storage_double")
        def upload_double():
            job_id = request.form["job_id"]
            jobs.read_owned(job_id, owner)
            objects.source = request.files["file"].read(1048577)
            result = processor.run(job_id, "123", now)
            if result["status"] != 204:
                return "", 503
            return "", 201

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            cert, key = folder/"cert.pem", folder/"key.pem"
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                            "-nodes", "-keyout", str(key), "-out", str(cert),
                            "-days", "1", "-subj", "/CN=localhost"],
                           check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=15)
            server = make_server("127.0.0.1", 0, app, threaded=True,
                                 ssl_context=(str(cert), str(key)),
                                 request_handler=QuietHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            options = webdriver.ChromeOptions()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--window-size=1400,1100")
            options.set_capability("acceptInsecureCerts", True)  # CI loopback cert only.
            driver = None
            try:
                driver = webdriver.Chrome(options=options)
                driver.set_page_load_timeout(20)
                wait = WebDriverWait(driver, 25)
                origin = f"https://127.0.0.1:{server.server_port}"
                driver.get(origin)
                wait.until(lambda d: "ยังไม่เข้าสู่ระบบ" in d.find_element(By.ID,"identity").text)
                driver.find_element(By.ID,"username").send_keys(owner)
                driver.find_element(By.ID,"password").send_keys("ci-only-pass")
                driver.find_element(By.CSS_SELECTOR,"#login-form button").click()
                wait.until(lambda d: owner in d.find_element(By.ID,"identity").text)
                fixture = LAB/"fixtures/valid-sales.csv"
                driver.find_element(By.ID,"file").send_keys(str(fixture))
                driver.execute_script("""
                    const nativeFetch = window.fetch.bind(window);
                    window.fetch = async (url, options) => {
                      const response = await nativeFetch(url, options);
                      if (url === '/api/jobs' && options && options.method === 'POST') {
                        window.fetch = nativeFetch;
                        throw new TypeError('CI simulated lost create response');
                      }
                      return response;
                    };
                """)
                driver.find_element(By.ID,"upload-button").click()
                wait.until(lambda d: "CI simulated lost create response" in
                           d.find_element(By.ID,"message").text)
                pending = json.loads(driver.execute_script(
                    "return sessionStorage.getItem(arguments[0]);", "lab006.pending."+owner))
                self.assertNotIn("job_id", pending)
                quota = client.collection("owner_quotas").document(owner).get().to_dict()
                self.assertEqual(quota["daily_count"], 1)
                original_id = quota["active_ids"][0]
                driver.refresh()
                wait.until(lambda d: owner in d.find_element(By.ID,"identity").text)
                driver.execute_script("""
                    const nativeFetch = window.fetch.bind(window);
                    window.fetch = (url, options) => {
                      if (String(url).startsWith('https://storage.googleapis.com/')) {
                        return nativeFetch('/__ci_storage_double', {...options,
                          credentials:'same-origin', headers:{'X-CSRF-Token':window.__ciCsrf}});
                      }
                      return nativeFetch(url, options);
                    };
                """)
                # Test-only CSRF setup for the injected Storage double; no production hook.
                driver.execute_async_script("""
                    const done=arguments[arguments.length-1];
                    fetch('/api/session').then(r=>r.json()).then(s=>{
                      window.__ciCsrf=s.csrf; done(true);
                    });
                """)
                driver.find_element(By.ID,"file").send_keys(str(fixture))
                driver.find_element(By.ID,"upload-button").click()
                wait.until(lambda d: "succeeded" in d.find_element(By.ID,"detail").text)
                current = jobs.read_owned(original_id, owner)
                self.assertEqual(current["state"], "succeeded")
                quota = client.collection("owner_quotas").document(owner).get().to_dict()
                self.assertEqual((quota["daily_count"], quota["active_ids"]), (1,[original_id]))
                self.assertEqual(objects.creates, 1)
                report = json.loads(next(iter(objects.outputs.values())))
                self.assertEqual((report["rows"], report["units"], report["total_satang"]),
                                 (3,6,72400))
                self.assertEqual(report["input_sha256"],
                                 hashlib.sha256(fixture.read_bytes()).hexdigest())
                self.assertIsNone(driver.execute_script(
                    "return sessionStorage.getItem(arguments[0]);", "lab006.pending."+owner))
                driver.execute_script("document.getElementById('password').value='';")
                preview = Path("lab006-previews/ui-ci.png")
                preview.parent.mkdir(exist_ok=True)
                height = min(2600, int(driver.execute_script("return document.documentElement.scrollHeight")) + 40)
                driver.set_window_size(1400, height)
                driver.save_screenshot(str(preview))
            finally:
                if driver is not None:
                    driver.quit()
                server.shutdown()
                thread.join(timeout=5)
                client.close()


if __name__ == "__main__":
    unittest.main()
