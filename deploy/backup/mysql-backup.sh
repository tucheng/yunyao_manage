#!/bin/sh
set -eu

mkdir -p /backups/mysql
export MYSQL_PWD="$MYSQL_PASSWORD"

while true; do
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  target="/backups/mysql/${MYSQL_DATABASE}-${stamp}.sql.gz"
  partial="${target}.partial"
  if mysqldump --host="$MYSQL_HOST" --user="$MYSQL_USER" --single-transaction \
      --routines --events --triggers --set-gtid-purged=OFF "$MYSQL_DATABASE" | gzip -9 > "$partial"; then
    gzip -t "$partial"
    mv "$partial" "$target"
    sha256sum "$target" > "${target}.sha256"
    find /backups/mysql -type f -mtime "+$BACKUP_RETENTION_DAYS" -delete
    echo "mysql backup complete: $target"
  else
    rm -f "$partial"
    echo "mysql backup failed" >&2
  fi
  sleep "$BACKUP_INTERVAL_SECONDS"
done
