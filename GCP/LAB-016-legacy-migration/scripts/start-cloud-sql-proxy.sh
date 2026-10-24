#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then echo "Run this script with sudo." >&2; exit 1; fi
if [[ "$#" -ne 1 || "$1" != *:*:* ]]; then echo "Usage: sudo $0 PROJECT_ID:REGION:INSTANCE" >&2; exit 64; fi
connection_name="$1"
proxy_bin=/usr/local/bin/cloud-sql-proxy
pid_file=/run/lab016/cloud-sql-proxy.pid
install -d -o root -g root -m 0700 /run/lab016
if [[ ! -x "$proxy_bin" ]]; then echo "Cloud SQL Auth Proxy is missing; inspect the VM startup log." >&2; exit 2; fi
if [[ -s "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
  echo "Cloud SQL Auth Proxy process already exists; checking local listener."
else
  nohup "$proxy_bin" --private-ip --address 127.0.0.1 --port 5433 --structured-logs "$connection_name" \
    >>/var/log/lab016-cloud-sql-proxy.log 2>&1 </dev/null &
  echo "$!" >"$pid_file"
fi
for attempt in $(seq 1 40); do
  if docker run --rm --network host postgres:16 pg_isready --host 127.0.0.1 --port 5433 --username postgres --dbname postgres >/dev/null 2>&1; then
    echo "target_proxy=ready address=127.0.0.1:5433 private_ip=true"
    exit 0
  fi
  sleep 2
done
tail -n 40 /var/log/lab016-cloud-sql-proxy.log >&2
echo "Cloud SQL Auth Proxy did not become ready; inspect its log and IAM/network gates." >&2
exit 3
