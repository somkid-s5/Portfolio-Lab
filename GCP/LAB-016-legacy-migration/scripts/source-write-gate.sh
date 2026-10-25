#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi
case "${1:-}" in
  freeze) setting=false ;;
  enable) setting=true ;;
  *)
    echo "Usage: sudo $0 freeze|enable" >&2
    exit 64
    ;;
esac
env_file=/etc/lab016/orders-api.env
[[ -f "$env_file" ]]
count="$(grep -c '^ALLOW_WRITES=' "$env_file" || true)"
if [[ "$count" != 1 ]]; then
  echo "Expected exactly one ALLOW_WRITES setting in "$env_file"; refusing to edit." >&2
  exit 2
fi
sed -i "s/^ALLOW_WRITES=.*/ALLOW_WRITES=$setting/" "$env_file"
systemctl restart lab016-orders
for attempt in $(seq 1 20); do
  if curl --fail --silent http://127.0.0.1:8080/readyz >/dev/null; then
    printf 'source_writes=%s readiness=ready\n' "$setting"
    exit 0
  fi
  sleep 2
done
journalctl --no-pager --unit lab016-orders --lines 30 >&2
echo "Readiness failed after changing the write gate; investigate before continuing." >&2
exit 3
