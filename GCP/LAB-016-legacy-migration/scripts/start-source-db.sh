#!/usr/bin/env bash
set -Eeuo pipefail
if [[ "$EUID" -ne 0 ]]; then
  echo "Run this script with sudo." >&2
  exit 1
fi
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_dir=/var/lib/lab016-postgres
secret_dir=/etc/lab016
container_name=lab016-postgres
image_ref="${POSTGRES_IMAGE:-postgres:16}"

if docker container inspect "$container_name" >/dev/null 2>&1; then
  if [[ "$(docker inspect --format '{{.State.Running}}' "$container_name")" != true ]]; then
    docker start "$container_name" >/dev/null
  fi
  echo "Reused existing PostgreSQL container; data and credentials were not reset."
else
  if [[ -d "$data_dir" ]] && find "$data_dir" -mindepth 1 -print -quit | grep -q .; then
    echo "Refusing to initialize non-empty $data_dir without its original container." >&2
    exit 2
  fi
  install -d -o root -g root -m 0750 "$secret_dir"
  install -d -o root -g root -m 0750 "$data_dir"
  umask 077
  if [[ ! -s "$secret_dir/source-admin-password" ]]; then
    openssl rand -hex 32 >"$secret_dir/source-admin-password"
  fi
  if [[ ! -s "$secret_dir/source-app-password" ]]; then
    openssl rand -hex 32 >"$secret_dir/source-app-password"
  fi
  chmod 0600 "$secret_dir/source-admin-password" "$secret_dir/source-app-password"
  install -m 0755 "$script_dir/source-db-init.sh" "$secret_dir/source-db-init.sh"
  docker pull "$image_ref"
  docker run --detach \
    --name "$container_name" \
    --restart unless-stopped \
    --publish 127.0.0.1:5432:5432 \
    --mount "type=bind,source=$data_dir,target=/var/lib/postgresql/data" \
    --mount "type=bind,source=$secret_dir/source-admin-password,target=/run/secrets/pg-admin-password,readonly" \
    --mount "type=bind,source=$secret_dir/source-app-password,target=/run/secrets/lab016-app-password,readonly" \
    --mount "type=bind,source=$secret_dir/source-db-init.sh,target=/docker-entrypoint-initdb.d/10-lab016.sh,readonly" \
    --env POSTGRES_USER=lab016_admin \
    --env POSTGRES_DB=postgres \
    --env POSTGRES_PASSWORD_FILE=/run/secrets/pg-admin-password \
    --env POSTGRES_INITDB_ARGS=--auth-host=scram-sha-256 \
    --health-cmd="pg_isready -U lab016_admin -d postgres" \
    --health-interval=5s \
    --health-timeout=3s \
    --health-retries=18 \
    "$image_ref" >/dev/null
fi

for attempt in $(seq 1 60); do
  if [[ "$(docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null || true)" == healthy ]]; then
    echo "source_postgres=ready port=127.0.0.1:5432"
    exit 0
  fi
  sleep 2
done
docker logs --tail 40 "$container_name" >&2
echo "PostgreSQL did not become healthy; inspect container logs before retrying." >&2
exit 3
