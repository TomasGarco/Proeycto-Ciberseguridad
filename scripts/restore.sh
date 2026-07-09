#!/bin/sh
# Restaura un backup generado por scripts/backup.sh.
#
# Uso (desde la raíz del repo, con el stack levantado):
#   sh scripts/restore.sh backups/20260709_170000
#
# ADVERTENCIA: esto sobreescribe los datos actuales de las 4 bases
# (auth_db, items_db, alerts_db, logs_db) con el contenido del backup.
# No pide confirmación — pensalo dos veces antes de correrlo contra
# datos que no querés perder.

set -e

BACKUP_DIR="$1"
if [ -z "${BACKUP_DIR}" ] || [ ! -d "${BACKUP_DIR}" ]; then
  echo "Uso: sh scripts/restore.sh <carpeta_de_backup>"
  echo "Ejemplo: sh scripts/restore.sh backups/20260709_170000"
  exit 1
fi

echo "[restore] Restaurando PostgreSQL desde ${BACKUP_DIR}..."
cat "${BACKUP_DIR}/auth_db.sql"   | docker exec -i postgres psql -U postgres -d auth_db
cat "${BACKUP_DIR}/items_db.sql" | docker exec -i postgres psql -U postgres -d items_db
cat "${BACKUP_DIR}/alerts_db.sql" | docker exec -i postgres psql -U postgres -d alerts_db

echo "[restore] Restaurando MongoDB desde ${BACKUP_DIR}..."
cat "${BACKUP_DIR}/logs_db.archive" | docker exec -i mongodb mongorestore --username root --password root --authenticationDatabase admin --archive --drop

echo "[restore] Listo."
