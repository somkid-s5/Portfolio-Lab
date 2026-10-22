#!/bin/bash
# Run on each Debian 12 APP VM only, after reviewing the lab guide.
# Requires /etc/lab002/app.env and /etc/lab002/token-hashes.json prepared separately.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo on the target App VM." >&2
  exit 1
fi
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test -f /etc/lab002/app.env
test -f /etc/lab002/token-hashes.json
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-psycopg2
if ! id lab002 >/dev/null 2>&1; then
  useradd --system --home-dir /opt/lab002 --shell /usr/sbin/nologin lab002
fi
install -d -m 755 /opt/lab002
install -m 644 "$SOURCE_DIR/app/server.py" /opt/lab002/server.py
install -m 644 "$SOURCE_DIR/app/index.html" /opt/lab002/index.html
chown root:lab002 /etc/lab002/token-hashes.json
chmod 640 /etc/lab002/token-hashes.json
chmod 600 /etc/lab002/app.env
cat > /etc/systemd/system/lab002-inventory.service <<'SERVICE'
[Unit]
Description=Private Inventory demo
Wants=network-online.target
After=network-online.target
[Service]
User=lab002
Group=lab002
EnvironmentFile=/etc/lab002/app.env
Environment=TOKEN_HASH_FILE=/etc/lab002/token-hashes.json
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=/opt/lab002
ExecStart=/usr/bin/python3 /opt/lab002/server.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable lab002-inventory
systemctl restart lab002-inventory
