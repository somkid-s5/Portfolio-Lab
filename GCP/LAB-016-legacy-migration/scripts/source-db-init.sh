#!/usr/bin/env bash
set -Eeuo pipefail
password_file=/run/secrets/lab016-app-password
test -r "$password_file"
app_password="$(cat "$password_file")"
[[ "$app_password" =~ ^[a-f0-9]{64}$ ]]
psql --set=ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE orders_app LOGIN PASSWORD '$app_password';
CREATE DATABASE orders OWNER orders_app;
SQL
