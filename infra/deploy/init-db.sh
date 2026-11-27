#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=kc_password="$KEYCLOAK_DB_PASSWORD" <<'SQL'
SELECT format('CREATE USER keycloak WITH PASSWORD %L', :'kc_password') \gexec
CREATE DATABASE keycloak OWNER keycloak;
SQL
