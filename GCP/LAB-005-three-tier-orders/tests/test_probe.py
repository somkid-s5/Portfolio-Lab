import contextlib
import importlib.util
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('orders_probe',ROOT/'scripts/probe.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class ProbeTests(unittest.TestCase):
    def test_origin_and_bounds(self):
        self.assertEqual(probe.endpoint('https://orders.example.com','/healthz'),'https://orders.example.com/healthz')
        for base in ['http://orders.example.com','https://user:password@orders.example.com','https://orders.example.com?token=secret','https://orders.example.com/path','https://orders.example.com:8443']:
            with self.assertRaises(ValueError):
                probe.endpoint(base,'/healthz')
        with self.assertRaises(ValueError):
            probe.endpoint('https://orders.example.com','/api/orders')
        for count,workers,interval in [(201,1,1),(1,9,1),(1,1,0),(True,1,1)]:
            with self.assertRaises(ValueError):
                probe.run('http://127.0.0.1',count,workers,interval)

    def test_real_http_sanitizes_body_and_does_not_follow_redirect(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                if self.path=='/redirect':
                    self.send_response(302)
                    self.send_header('Location','/forbidden')
                    self.end_headers()
                    return
                if self.path=='/forbidden':
                    raise AssertionError('Redirect followed')
                self.send_response(200 if self.path=='/healthz' else 503)
                self.send_header('X-Web-ID','web-a')
                self.send_header('X-Backend-ID','api-b')
                self.send_header('Set-Cookie','private-cookie=NEVER-LOG')
                self.end_headers()
                self.wfile.write(json.dumps({'version':'v1','csrf':'NEVER-LOG','private':'NEVER-LOG'}).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            origin='http://127.0.0.1:'+str(server.server_port)
            rows=[]
            result=probe.run(probe.endpoint(origin,'/healthz',True),count=4,workers=2,interval=0.1,emit=rows.append)
            self.assertEqual(result['errors'],0)
            self.assertEqual(result['api_counts'],{'api-b':4})
            self.assertNotIn('NEVER-LOG',json.dumps(rows))
            self.assertEqual(probe.sample(origin+'/error')['error'],'unexpected_http_status')
            self.assertEqual(probe.sample(origin+'/redirect')['status'],302)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_summary_counts_failures_without_pass_claim(self):
        records=[{'status':200,'latency_ms':1,'api':'api-a'},
                 {'status':503,'latency_ms':20,'error':'unexpected_http_status'}]
        with patch.object(probe,'sample',side_effect=records),patch.object(probe.time,'sleep'):
            result=probe.run('https://orders.example.com/healthz',2)
        self.assertEqual(result['errors'],1)
        self.assertEqual(result['p95_ms'],20)
        self.assertNotIn('PASS',json.dumps(result))
