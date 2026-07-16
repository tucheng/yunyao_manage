#!/bin/sh
set -eu

mkdir -p /backups/objects
mc alias set source "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY"

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  for bucket in $S3_BUCKETS; do
    target="/backups/objects/${bucket}-${stamp}"
    partial="${target}.partial"
    rm -rf "$partial"
    mkdir -p "$partial"
    if mc mirror --overwrite "source/$bucket" "$partial"; then
      mc ls --recursive --json "source/$bucket" > "${partial}/manifest.ndjson"
      mv "$partial" "$target"
      echo "object backup complete: $target"
    else
      rm -rf "$partial"
      echo "object backup failed: $bucket" >&2
    fi
  done
  find /backups/objects -mindepth 1 -maxdepth 1 -type d -mtime "+$BACKUP_RETENTION_DAYS" -exec rm -rf {} +
  sleep "$BACKUP_INTERVAL_SECONDS"
done
