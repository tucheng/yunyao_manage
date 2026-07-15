#!/bin/sh
set -eu

if [ "${CONFIRM_RESTORE_DRILL:-}" != "yes" ]; then
  echo "set CONFIRM_RESTORE_DRILL=yes; only a drill bucket is allowed" >&2
  exit 2
fi
case "${RESTORE_BUCKET:-}" in
  *-restore-drill) ;;
  *) echo "RESTORE_BUCKET must end with -restore-drill" >&2; exit 2 ;;
esac
test -d "$BACKUP_PATH"
mc alias set target "$S3_ENDPOINT_URL" "$S3_ACCESS_KEY_ID" "$S3_SECRET_ACCESS_KEY"
mc mb --ignore-existing "target/$RESTORE_BUCKET"
mc mirror --overwrite --exclude manifest.ndjson "$BACKUP_PATH" "target/$RESTORE_BUCKET"
mc ls --recursive --json "target/$RESTORE_BUCKET" > /tmp/restored-manifest.ndjson
echo "object restore drill complete: $RESTORE_BUCKET"
