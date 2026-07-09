# Auth Service

FastAPI · PostgreSQL (`auth_db`, `items_db`, fallback a SQLite local) · Puerto `8000`

## Qué hace

Autenticación con JWT, gestión de usuarios y roles, y un CRUD de "items" de ejemplo usado para practicar operaciones protegidas por rol. Roles soportados: `analista` (rol por defecto al registrarse) y `admin`. También reporta cada evento relevante al Log Service en segundo plano (`BackgroundTasks` + `requests`), sin bloquear la respuesta al cliente.

Incluye rate limiting de login: 5 intentos fallidos en 60s bloquean al usuario 60s (`429 Too Many Requests`) — mismo umbral que la regla `fuerza-bruta-login` del Analysis Service. También rate limiting de registro (Semana 10): 10 registros en 5 minutos desde la misma IP bloquean nuevos registros de esa IP (`429`) — protege contra creación masiva de cuentas automatizada.

## Endpoints principales

| Método | Endpoint | Rol requerido |
|---|---|---|
| `POST` | `/auth/register` | público |
| `POST` | `/auth/login` | público |
| `GET` | `/auth/me` | cualquier usuario autenticado |
| `GET` | `/auth/users` | `admin` |
| `PATCH` | `/auth/users/{id}/role` | `admin` (no puede cambiar su propio rol) |
| `GET`/`POST` | `/api/items` | cualquier usuario autenticado |
| `PUT`/`DELETE` | `/api/items/{id}` | `admin` |
| `GET` | `/api/health` | público |

Documentación interactiva completa (Swagger/OpenAPI, autogenerada por FastAPI): `http://localhost:8000/docs`.

## Variables de entorno

Ver `docker-compose.yml` (sección `auth-service`) y `.env.example` en la raíz del repo. Las relevantes para este servicio: `POSTGRES_HOST/PORT/USER/PASSWORD`, `JWT_SECRET_KEY`, `LOG_SERVICE_URL`, `CORS_ORIGINS`. Sin `POSTGRES_HOST` definido, cae automáticamente a SQLite local (`data/auth.db`, `data/items.db`).

## Logging

El logging operacional del proceso (conexiones a Postgres, errores al reportar al Log Service) sale por stdout como un objeto JSON por línea: `{"timestamp", "service", "level", "category", "message"}` (función `log_event()` en `app.py`). Distinto de `send_log()`, que envía el evento de negocio al Log Service para persistirlo en MongoDB.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_auth.py` cubre registro, login, emisión de JWT y control de acceso por rol.

## Levantar solo este servicio

```bash
docker compose up -d --build auth-service
```
