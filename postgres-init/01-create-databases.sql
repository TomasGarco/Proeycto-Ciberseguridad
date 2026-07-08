-- Ejecutado automáticamente por la imagen oficial de Postgres en el primer
-- arranque del contenedor (docker-entrypoint-initdb.d). Crea las bases de
-- datos que los servicios esperan: auth_db/items_db para Auth Service
-- (replicando la separación auth.db/items.db que antes existía como dos
-- archivos SQLite) y alerts_db para Alert Service.
-- Nota: si el volumen postgres_data ya existe, este script NO se re-ejecuta;
-- alert-service crea alerts_db por sí mismo si no la encuentra (index.js).
CREATE DATABASE auth_db;
CREATE DATABASE items_db;
CREATE DATABASE alerts_db;
