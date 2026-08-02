#!/usr/bin/env sh
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "[bridge-api] Aplicando migraciones Alembic..."
  alembic -c /app/alembic.ini upgrade head
fi

exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8005 \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}"
