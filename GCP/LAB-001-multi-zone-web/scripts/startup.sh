#!/bin/bash
# Paste the entire file into the startup-script field of each backend VM (A, B and change-request C).
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3
install -d -m 755 /opt/lab001
if ! id lab001 >/dev/null 2>&1; then
  useradd --system --home-dir /opt/lab001 --shell /usr/sbin/nologin lab001
fi
cat > /opt/lab001/app.py <<'PYAPP'
import json
import os
import socket
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = socket.gethostname()
PAGE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Field Notes | Lab 01</title>
<style>body{margin:0;padding:8vw;background:#f4f4ef;color:#26362d;font:17px/1.6 system-ui}main{max-width:800px;margin:auto}small{letter-spacing:3px;color:#68776c}h1{font-size:clamp(36px,7vw,70px);line-height:1.05}section{border:1px solid #b8c5bb;padding:28px;background:white}code{font-size:22px;color:#276b4b}button,a{color:#276b4b}button{margin-top:22px;padding:12px 20px;background:#e9f1ea;border:1px solid #9db2a3;cursor:pointer}</style>
<main><small>FIELD NOTES / CLOUD ENGINEERING</small><h1>One address.<br>Two application servers.</h1>
<p>A small stateless web application behind a load balancer.</p>
<section><small>THIS RESPONSE WAS SERVED BY</small><p><code id="host">__HOST__</code></p><p id="time">__TIME__</p><p>Application version: lab001-v1</p></section>
<button onclick="location.reload()">Request again</button> <a href="/api">View JSON response</a>
<p>Reloading does not guarantee a different backend. Use the probe script to observe a sample of requests.</p></main></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path).path
        timestamp = datetime.now(timezone.utc).isoformat()
        if route == '/healthz':
            healthy = not Path(os.environ.get('UNHEALTHY_FILE', '/opt/lab001/unhealthy')).exists()
            code, mime, body = (200 if healthy else 503), 'text/plain', ('ok\n' if healthy else 'unhealthy\n')
        elif route == '/api':
            code, mime = 200, 'application/json'
            body = json.dumps({'service': 'field-notes', 'version': 'lab001-v1', 'hostname': HOST, 'time_utc': timestamp})
        elif route == '/':
            code, mime = 200, 'text/html'
            body = PAGE.replace('__HOST__', HOST).replace('__TIME__', timestamp)
        else:
            code, mime, body = 404, 'text/plain', 'not found\n'
        payload = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Lab-Backend', HOST)
        self.end_headers()
        self.wfile.write(payload)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '8080'))), Handler).serve_forever()
PYAPP
chmod 644 /opt/lab001/app.py
cat > /etc/systemd/system/lab001-app.service <<'SERVICE'
[Unit]
Description=Lab 01 stateless application
After=network-online.target
Wants=network-online.target

[Service]
User=lab001
Group=lab001
WorkingDirectory=/opt/lab001
ExecStart=/usr/bin/python3 /opt/lab001/app.py
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable lab001-app
systemctl restart lab001-app
