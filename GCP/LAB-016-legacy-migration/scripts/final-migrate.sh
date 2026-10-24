#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then echo "Run this script with sudo." >&2; exit 1; fi
if [[ "$#" -ne 3 ]]; then echo "Usage: sudo $0 PROJECT_ID PROJECT_ID:REGION:INSTANCE RUN_ID" >&2; exit 64; fi
project_id="$1"
connection_name="$2"
run_id="$3"
if [[ "$connection_name" != "${project_id}:"* || ! "$run_id" =~ ^[a-z0-9][a-z0-9-]{0,31}$ ]]; then
  echo "Project/connection name mismatch or invalid run ID." >&2; exit 64
fi
if ! grep -qx 'ALLOW_WRITES=false' /etc/lab016/orders-api.env; then
  echo "Source writes must be frozen before the final export." >&2; exit 2
fi
container_name=lab016-postgres
if ! docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null | grep -qx healthy; then
  echo "Source PostgreSQL is not healthy; do not create the final dump." >&2; exit 3
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
run_dir="/var/lib/lab016-migration/$run_id"
if [[ -e "$run_dir" ]]; then echo "Run directory already exists; choose a new run ID." >&2; exit 4; fi
install -d -o root -g root -m 0700 "$run_dir" /run/lab016
cleanup() {
  rm -f /run/lab016/target-admin-password /run/lab016/target-app-password /run/lab016/roles.sql
  unset SOURCE_ADMIN_PASSWORD TARGET_ADMIN_PASSWORD TARGET_APP_PASSWORD
}
trap cleanup EXIT
SOURCE_ADMIN_PASSWORD="$(cat /etc/lab016/source-admin-password)"
active_transactions="$(docker exec --env PGPASSWORD="$SOURCE_ADMIN_PASSWORD" "$container_name" \
  psql --no-psqlrc --quiet --tuples-only --no-align --username lab016_admin --dbname orders \
  --command="SELECT count(*) FROM pg_stat_activity WHERE datname='orders' AND pid <> pg_backend_pid() AND (xact_start IS NOT NULL OR state='idle in transaction')")"
if [[ "$active_transactions" != 0 ]]; then
  echo "Found active or idle-in-transaction sessions ("$active_transactions"); resolve them before export." >&2; exit 5
fi
docker exec --env PGPASSWORD="$SOURCE_ADMIN_PASSWORD" "$container_name" \
  pg_dump --host=127.0.0.1 --username=lab016_admin --dbname=orders \
  --format=custom --no-owner --no-privileges >"$run_dir/source.dump"
unset SOURCE_ADMIN_PASSWORD
if [[ ! -s "$run_dir/source.dump" ]]; then echo "The final export is empty; stop and investigate." >&2; exit 6; fi
chmod 0600 "$run_dir/source.dump"
dump_sha="$(sha256sum "$run_dir/source.dump" | awk '{print $1}')"
printf '%s  %s\n' "$dump_sha" source.dump >"$run_dir/SHA256SUMS"
"$script_dir/start-cloud-sql-proxy.sh" "$connection_name"
gcloud secrets versions access latest --secret=lab016-target-admin-password --project="$project_id" >/run/lab016/target-admin-password
gcloud secrets versions access latest --secret=lab016-target-db-password --project="$project_id" >/run/lab016/target-app-password
chmod 0600 /run/lab016/target-admin-password /run/lab016/target-app-password
TARGET_ADMIN_PASSWORD="$(cat /run/lab016/target-admin-password)"
TARGET_APP_PASSWORD="$(cat /run/lab016/target-app-password)"
if [[ ! "$TARGET_ADMIN_PASSWORD" =~ ^[a-f0-9]{64}$ || ! "$TARGET_APP_PASSWORD" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Secret values must be 64 lowercase hex characters generated for this Lab." >&2; exit 7
fi
if ! docker run --rm --network host --env PGPASSWORD="$TARGET_ADMIN_PASSWORD" postgres:16 \
  psql --no-psqlrc --quiet --tuples-only --no-align --host=127.0.0.1 --port=5433 \
  --username=postgres --dbname=orders --command="SELECT to_regclass('public.orders') IS NULL" | grep -qx t; then
  echo "Target already contains public.orders. Do not overwrite it; confirm authority and recover deliberately." >&2; exit 8
fi
docker run --rm --network host --env PGPASSWORD="$TARGET_ADMIN_PASSWORD" \
  --mount "type=bind,source=$run_dir,target=/transfer,readonly" postgres:16 \
  pg_restore --exit-on-error --no-owner --no-privileges --host=127.0.0.1 --port=5433 \
  --username=postgres --dbname=orders /transfer/source.dump
cat >/run/lab016/roles.sql <<SQL
SELECT 'CREATE ROLE orders_app LOGIN' WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='orders_app')\\gexec
ALTER ROLE orders_app WITH LOGIN PASSWORD '$TARGET_APP_PASSWORD';
GRANT CONNECT ON DATABASE orders TO orders_app;
\\connect orders
GRANT USAGE ON SCHEMA public TO orders_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO orders_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO orders_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO orders_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO orders_app;
SQL
chmod 0600 /run/lab016/roles.sql
docker run --rm --interactive --network host --env PGPASSWORD="$TARGET_ADMIN_PASSWORD" postgres:16 \
  psql --no-psqlrc --set=ON_ERROR_STOP=1 --host=127.0.0.1 --port=5433 --username=postgres --dbname=postgres \
  </run/lab016/roles.sql
SOURCE_PASSWORD_FILE=/etc/lab016/source-app-password
TARGET_PASSWORD_FILE=/run/lab016/target-app-password
SOURCE_HOST=127.0.0.1 SOURCE_PORT=5432 SOURCE_DATABASE=orders SOURCE_USER=orders_app \
TARGET_HOST=127.0.0.1 TARGET_PORT=5433 TARGET_DATABASE=orders TARGET_USER=orders_app \
SOURCE_PASSWORD_FILE="$SOURCE_PASSWORD_FILE" TARGET_PASSWORD_FILE="$TARGET_PASSWORD_FILE" \
  /opt/lab016/venv/bin/python "$script_dir/reconcile.py" >"$run_dir/reconciliation.json" || reconcile_status=$?
if [[ "${reconcile_status:-0}" != 0 ]]; then
  cat "$run_dir/reconciliation.json"
  echo "Reconciliation did not match; leave both APIs frozen and do not cut over." >&2
  exit "$reconcile_status"
fi
cat "$run_dir/reconciliation.json"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{\n  "run_id": "%s",\n  "created_at_utc": "%s",\n  "source_dump_sha256": "%s",\n  "reconciliation": "matched"\n}\n' "$run_id" "$created_at" "$dump_sha" >"$run_dir/manifest.json"
chmod 0600 "$run_dir/manifest.json"
echo "migration_run=$run_id source_dump_sha256=$dump_sha reconciliation=matched"
