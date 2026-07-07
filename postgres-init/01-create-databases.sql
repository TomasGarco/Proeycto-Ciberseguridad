-- Ejecutado automáticamente por la imagen oficial de Postgres en el primer
-- arranque del contenedor (docker-entrypoint-initdb.d). Crea las dos bases
-- de datos que Auth Service espera, replicando la separación auth.db/items.db
-- que antes existía como dos archivos SQLite independientes.
CREATE DATABASE auth_db;
CREATE DATABASE items_db;
