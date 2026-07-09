# Alert Service

Node.js + Express · PostgreSQL (`alerts_db`, mismo servidor que `auth_db`/`items_db`, base separada) · RabbitMQ (consume `alerts_queue`) · Puerto `8003`

## Qué hace

El único servicio del proyecto que no está en Python (a propósito, para practicar un stack políglota). Consume la cola `alerts_queue` (binding `alerts.#`), persiste cada alerta en PostgreSQL (`alerts_db.alerts`, con el evento original en una columna JSONB) y expone la API de consulta y ciclo de vida del incidente: `nueva` → `reconocida` → `cerrada`.

**Nota:** `alerts_db` vive en el mismo contenedor/servidor PostgreSQL que `auth_db` e `items_db` — es una base de datos lógica separada, no una instancia de PostgreSQL distinta.

## Endpoints principales

| Método | Endpoint | Auth requerida | Descripción |
|---|---|---|---|
| `GET` | `/alerts` | ninguna | Lista alertas, con filtros por severidad/estado |
| `GET` | `/alerts/stats` | ninguna | Conteos agregados |
| `PATCH` | `/alerts/:id` | JWT + rol `admin` | Cambia el estado (nueva → reconocida → cerrada) |
| `GET` | `/api/health` | ninguna | Estado del servicio |

Este servicio no genera documentación OpenAPI/Swagger (Express no lo hace automáticamente como FastAPI); los endpoints están documentados arriba y en el README raíz del repo.

**Autenticación (Semana 10):** `PATCH /alerts/:id` es el único endpoint que exige un JWT válido (el mismo que emite auth-service) con `role: "admin"` en el payload — sin token da `401`, con rol `analista` da `403`. Las lecturas (`GET`) siguen abiertas a propósito, mismo criterio que log-service y analysis-service: el dashboard ya oculta los botones de ciclo de vida a usuarios no-admin, pero antes de este cambio cualquiera podía llamar el `PATCH` directo por HTTP sin pasar por el dashboard.

## Variables de entorno

`PORT`, `POSTGRES_HOST/PORT/USER/PASSWORD`, `RABBITMQ_HOST/PORT/USER/PASSWORD`, `JWT_SECRET_KEY` (debe ser la misma que usa auth-service para firmar los tokens). Ver `.env.example` en la raíz. Al arrancar crea `alerts_db` y la tabla `alerts` por sí mismo si no existen.

## Logging

El logging operacional (conexión a Postgres/RabbitMQ, alertas persistidas, errores de API) sale por stdout como JSON, un objeto por línea (`logEvent()` en `index.js`): `{"timestamp", "service", "level", "category", "message"}` — mismo formato que los 3 servicios Python del proyecto.

## Tests

Este servicio no tiene tests automatizados propios todavía (no hay Jest ni ningún test runner configurado en `package.json`).

## Levantar solo este servicio

```bash
docker compose up -d --build alert-service
```
