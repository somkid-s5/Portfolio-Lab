#!/usr/bin/env bash
set -euo pipefail
set +x

PROJECT_ID="${1:?Usage: prepare_db_users.sh PROJECT_ID INSTANCE_NAME}"
INSTANCE_NAME="${2:?Usage: prepare_db_users.sh PROJECT_ID INSTANCE_NAME}"
ACTIVE_PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [[ "$ACTIVE_PROJECT" != "$PROJECT_ID" ]]; then
  echo "Active gcloud project ($ACTIVE_PROJECT) does not match $PROJECT_ID." >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
chmod 700 "$TMP_DIR"
cleanup() {
  unset ADMIN_PASSWORD APP_PASSWORD
  rm -f "$TMP_DIR/admin" "$TMP_DIR/app"
  rmdir "$TMP_DIR"
}
trap cleanup EXIT

ADMIN_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
APP_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
umask 077
printf '%s' "$ADMIN_PASSWORD" > "$TMP_DIR/admin"
printf '%s' "$APP_PASSWORD" > "$TMP_DIR/app"

gcloud sql users set-password postgres \
  --instance="$INSTANCE_NAME" --project="$PROJECT_ID" --password="$ADMIN_PASSWORD"
if gcloud sql users list --instance="$INSTANCE_NAME" --project="$PROJECT_ID" \
    --format='value(name)' | grep -Fxq records_app; then
  gcloud sql users set-password records_app \
    --instance="$INSTANCE_NAME" --project="$PROJECT_ID" --password="$APP_PASSWORD"
else
  gcloud sql users create records_app \
    --instance="$INSTANCE_NAME" --project="$PROJECT_ID" --password="$APP_PASSWORD"
fi

gcloud secrets versions add lab017-db-admin-password \
  --project="$PROJECT_ID" --data-file="$TMP_DIR/admin"
gcloud secrets versions add lab017-db-password \
  --project="$PROJECT_ID" --data-file="$TMP_DIR/app"

unset ADMIN_PASSWORD APP_PASSWORD
echo "db_users_ready=true admin_password_secret=lab017-db-admin-password app_password_secret=lab017-db-password"
