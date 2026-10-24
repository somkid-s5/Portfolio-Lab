#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi
bundle_dir="${1:-/tmp/lab016-bundle}"
app_src="$bundle_dir/app"
scripts_src="$bundle_dir/scripts"
for required in "$app_src/main.py" "$app_src/requirements.txt" "$app_src/schema.sql" "$app_src/seed.sql" "$scripts_src/init_db.py"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing Lab bundle file: $required" >&2
    exit 2
  fi
done
if ! id orders-api >/dev/null 2>&1; then
  useradd --system --home-dir /opt/lab016 --shell /usr/sbin/nologin orders-api
fi
install -d -o root -g orders-api -m 0750 /opt/lab016/app /opt/lab016/scripts
install -o root -g orders-api -m 0640 "$app_src/main.py" "$app_src/schema.sql" "$app_src/seed.sql" /opt/lab016/app/
install -o root -g orders-api -m 0640 "$scripts_src/init_db.py" /opt/lab016/scripts/
python3 -m venv /opt/lab016/venv
/opt/lab016/venv/bin/pip install --no-cache-dir --requirement "$app_src/requirements.txt"

password_file=/etc/lab016/source-app-password
if [[ ! -s "$password_file" ]]; then
  echo "Source database password is missing; start the source database first." >&2
  exit 3
fi
app_password="$(cat "$password_file")"
[[ "$app_password" =~ ^[a-f0-9]{64}$ ]]
printf 'DB_HOST=127.0.0.1\nDB_PORT=5432\nDB_NAME=orders\nDB_USER=orders_app\nDB_PASSWORD=%s\nBACKEND_NAME=legacy-source\nALLOW_WRITES=true\nPORT=8080\n' "$app_password" >/etc/lab016/orders-api.env
chown root:orders-api /etc/lab016/orders-api.env
chmod 0640 /etc/lab016/orders-api.env
cat >/etc/systemd/system/lab016-orders.service <<'UNIT'
[Unit]
Description=Lab 16 synthetic Orders API (legacy source)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=orders-api
Group=orders-api
WorkingDirectory=/opt/lab016/app
EnvironmentFile=/etc/lab016/orders-api.env
ExecStart=/opt/lab016/venv/bin/python /opt/lab016/app/main.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
set -a
source /etc/lab016/orders-api.env
set +a
runuser -u orders-api -- env DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=orders DB_USER=orders_app DB_PASSWORD="$DB_PASSWORD" \
  /opt/lab016/venv/bin/python /opt/lab016/scripts/init_db.py --seed
systemctl enable --now lab016-orders
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8080/readyz >/dev/null; then
    echo "source_orders_api=ready backend=legacy-source"
    exit 0
  fi
  sleep 2
done
journalctl --no-pager --unit lab016-orders --lines 40 >&2
echo "Orders API is not ready; use the unit journal and readiness checks to diagnose." >&2
exit 4
