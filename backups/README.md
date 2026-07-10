# backups/

Carpeta de destino de los respaldos de las bases de datos. **Es normal que
esté vacía**: se llena solo cuando se corre un backup, y su contenido no se
versiona en git (ver `.gitignore`) porque los dumps pueden contener datos
reales y pesan.

## Cómo generar un backup

Con el stack levantado, desde la raíz del repo:

```bash
sh scripts/backup.sh
```

Crea una subcarpeta `backups/<fecha_hora>/` con:

| Archivo | Contenido |
|---|---|
| `auth_db.sql` | Usuarios y roles (PostgreSQL, `pg_dump`) |
| `items_db.sql` | Inventario de artículos (PostgreSQL, `pg_dump`) |
| `alerts_db.sql` | Alertas del Alert Service (PostgreSQL, `pg_dump`) |
| `logs_db.archive` | Logs de auditoría (MongoDB, `mongodump`) |

## Cómo restaurar

```bash
sh scripts/restore.sh backups/<fecha_hora>
```

## Backup programado (opcional)

`scripts/backup-scheduled.bat` es un wrapper para el Programador de tareas de
Windows — ver la sección "Backups" del README principal.
