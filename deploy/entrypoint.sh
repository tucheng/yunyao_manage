#!/bin/sh
set -eu

if [ "${APP_ENV:-development}" = "production" ] && [ "${FORWARDED_ALLOW_IPS:-}" = "*" ]; then
  echo "FORWARDED_ALLOW_IPS=* is forbidden in production" >&2
  exit 1
fi

exec uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
