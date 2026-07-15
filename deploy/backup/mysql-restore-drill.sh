#!/bin/sh
set -eu

if [ "${CONFIRM_RESTORE_DRILL:-}" != "yes" ]; then
  echo "set CONFIRM_RESTORE_DRILL=yes; only a disposable drill database is allowed" >&2
  exit 2
fi
case "${RESTORE_DATABASE:-}" in
  *_restore_drill) ;;
  *) echo "RESTORE_DATABASE must end with _restore_drill" >&2; exit 2 ;;
esac
test -f "$BACKUP_FILE"
sha256sum -c "${BACKUP_FILE}.sha256"
export MYSQL_PWD="$MYSQL_PASSWORD"
mysql --host="$MYSQL_HOST" --user="$MYSQL_USER" -e "DROP DATABASE IF EXISTS \`$RESTORE_DATABASE\`; CREATE DATABASE \`$RESTORE_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gunzip -c "$BACKUP_FILE" | mysql --host="$MYSQL_HOST" --user="$MYSQL_USER" "$RESTORE_DATABASE"
mysql --host="$MYSQL_HOST" --user="$MYSQL_USER" "$RESTORE_DATABASE" -e "SELECT COUNT(*) AS tables_restored FROM information_schema.tables WHERE table_schema='$RESTORE_DATABASE';"
