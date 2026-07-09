#!/bin/sh
# Backup manual de las 3 bases de datos del proyecto (auth_db, items_db,
# alerts_db en Postgres; logs_db en MongoDB). No hay backup automático
# programado — este script se corre a mano cuando hace falta (antes de una
# demo, antes de un cambio grande, o simplemente como respaldo periódico).
#
# Uso (desde la raíz del repo, con el stack levantado):
#   sh scripts/backup.sh
#
# Genera una carpeta backups/<fecha_hora>/ con:
#   - auth_db.sql, items_db.sql, alerts_db.sql (dumps de texto plano de pg_dump)
#   - logs_db/ (carpeta con el dump binario de mongodump)
#
# Para restaurar, ver scripts/restore.sh

set -e

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="backups/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"

echo "[backup] Exportando PostgreSQL (auth_db, items_db, alerts_db)..."
docker exec postgres pg_dump -U postgres auth_db   > "${BACKUP_DIR}/auth_db.sql"
docker exec postgres pg_dump -U postgres items_db  > "${BACKUP_DIR}/items_db.sql"
docker exec postgres pg_dump -U postgres alerts_db > "${BACKUP_DIR}/alerts_db.sql"

echo "[backup] Exportando MongoDB (logs_db)..."
docker exec mongodb mongodump --username root --password root --authenticationDatabase admin --db logs_db --archive > "${BACKUP_DIR}/logs_db.archive"

echo "[backup] Listo: ${BACKUP_DIR}/"
ls -la "${BACKUP_DIR}"
