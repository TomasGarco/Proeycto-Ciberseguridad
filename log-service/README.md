# Log Service

FastAPI · MongoDB (`logs_db.logs`) · RabbitMQ (publica a `logs_events`) · Puerto `8010`

## Qué hace

Recolector centralizado de eventos: recibe logs por HTTP, los persiste en MongoDB y publica cada uno en RabbitMQ (exchange topic `logs_events`, routing key `logs.<nivel>`) para que Analysis Service los consuma en tiempo real. Es intencionalmente "tonto" — no analiza nada, solo guarda y reenvía — para que si Analysis Service se cae, los logs se sigan guardando igual.

El origen de cada evento es el campo libre `service` del payload (por ejemplo `"auth-service"`); no hay adaptadores dedicados por tipo de fuente (Linux, Windows, firewall, etc.) — cualquier cliente HTTP puede publicar un evento con el formato correcto.

## Endpoints principales

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/` | Consola web de monitoreo con auto-refresco |
| `POST` | `/logs` | Registra un evento: `{service, level, message, timestamp}` |
| `GET` | `/logs` | Consulta/filtra logs almacenados en MongoDB |
| `GET` | `/api/health` | Estado del servicio |

Swagger/OpenAPI (autogenerado por FastAPI): `http://localhost:8010/docs`.

## Variables de entorno

`MONGO_HOST/PORT/DATABASE/USERNAME/PASSWORD`, `RABBITMQ_HOST/PORT/USER/PASSWORD` (opcional — sin `RABBITMQ_HOST` el servicio funciona solo con Mongo, sin publicar a la cola), `CORS_ORIGINS`. Ver `.env.example` en la raíz.

## Logging

Cada evento recibido por `POST /logs` se ecoa por stdout como JSON (`category: "EVENTO_RECIBIDO"`, con el `service`/`level` del emisor original); el logging operacional del propio proceso (conexión a Mongo/RabbitMQ, errores internos) usa la misma función `log_event()` con su propia categoría (`DB`, `RABBITMQ`). Un objeto JSON por línea en ambos casos.

## Tests

Este servicio no tiene tests automatizados propios todavía.

## Levantar solo este servicio

```bash
docker compose up -d --build log-service
```
