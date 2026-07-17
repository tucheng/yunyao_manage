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
  cutoff_epoch="$(date -u -d "$BACKUP_RETENTION_DAYS days ago" +%s)"
  for backup_path in /backups/objects/*; do
    [ -d "$backup_path" ] || continue
    modified_epoch="$(stat -c %Y "$backup_path")"
    if [ "$modified_epoch" -lt "$cutoff_epoch" ]; then
      rm -rf "$backup_path"
    fi
  done
  sleep "$BACKUP_INTERVAL_SECONDS"
done
