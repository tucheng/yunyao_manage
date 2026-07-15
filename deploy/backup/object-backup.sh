#!/bin/sh
set -eu

mkdir -p /backups/objects
mc alias set source "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY"

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/objects/${S3_BUCKET}-${stamp}"
  partial="${target}.partial"
  rm -rf "$partial"
  mkdir -p "$partial"
  if mc mirror --overwrite "source/$S3_BUCKET" "$partial"; then
    mc ls --recursive --json "source/$S3_BUCKET" > "${partial}/manifest.ndjson"
    mv "$partial" "$target"
    find /backups/objects -mindepth 1 -maxdepth 1 -type d -mtime "+$BACKUP_RETENTION_DAYS" -exec rm -rf {} +
    echo "object backup complete: $target"
  else
    rm -rf "$partial"
    echo "object backup failed" >&2
  fi
  sleep "$BACKUP_INTERVAL_SECONDS"
done
