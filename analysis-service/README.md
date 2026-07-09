# Analysis Service

FastAPI · RabbitMQ (consume `analysis_queue`, publica `alerts_events`) · Redis (caché de estadísticas) · Puerto `8002`

## Qué hace

Un hilo dedicado consume la cola `analysis_queue` (binding `logs.#`) y le aplica a cada evento el motor de reglas de detección definido en la lista `RULES` (dentro de `app.py`): umbral (N eventos en una ventana de tiempo), patrón (regex) y palabra clave. Cada alerta disparada se publica en el exchange `alerts_events` con routing key `alerts.<severidad>`.

**Nota sobre "umbrales configurables":** los valores de `threshold` y `window_seconds` de cada regla están hardcodeados en `RULES` dentro del código fuente — para cambiarlos hay que editar `app.py` y reconstruir la imagen, no son variables de entorno. No existe una regla de "fuera de horario".

## Endpoints principales

| Método | Endpoint | Auth requerida | Descripción |
|---|---|---|---|
| `GET` | `/api/health` | ninguna | Estado del servicio |
| `GET` | `/stats` | JWT (cualquier rol) | Estadísticas agregadas (por nivel, por servicio, por severidad de alerta) |
| `GET` | `/events/recent` | JWT (cualquier rol) | Últimos eventos consumidos (máx. 50, en memoria/Redis) |
| `GET` | `/rules` | JWT (cualquier rol) | Lista de reglas activas |

Swagger/OpenAPI (autogenerado por FastAPI): `http://localhost:8002/docs`.

**Autenticación (Semana 10):** los 3 endpoints de lectura exigen un JWT válido emitido por auth-service — sin restricción de rol, porque la pestaña Estadísticas del dashboard la ve tanto `analista` como `admin`.

## Variables de entorno

`RABBITMQ_HOST/PORT/USER/PASSWORD`, `REDIS_HOST/PORT` (opcional — sin `REDIS_HOST` funciona solo en memoria, sin persistir contadores entre reinicios), `JWT_SECRET_KEY` (debe ser la misma que usa auth-service para firmar los tokens), `CORS_ORIGINS`. Ver `.env.example` en la raíz.

## Logging

El logging operacional (conexión a RabbitMQ/Redis, eventos consumidos, alertas disparadas) sale por stdout como JSON, un objeto por línea (`log_event()` en `app.py`): `{"timestamp", "service", "level", "category", "message"}`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_rules_engine.py` — 17 tests que cubren los 3 tipos de regla, el cooldown de alertas repetidas y casos negativos.

## Levantar solo este servicio

```bash
docker compose up -d --build analysis-service
```
