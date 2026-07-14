# Dashboard Service

React (JavaScript + JSX, **no TypeScript**) · Vite · Recharts · Axios · nginx · Puertos `443` (HTTPS) / `3000` (redirige a `443`)

## Qué hace

Frontend y punto de entrada principal de la plataforma. nginx sirve la SPA compilada y además actúa como reverse proxy: todas las llamadas del navegador van a `/api/*` en este mismo origen y nginx las reenvía internamente a auth-service, log-service, analysis-service y alert-service — así no hay problemas de CORS entre pestañas.

**Nota sobre el stack:** el proyecto usa JavaScript con JSX, no TypeScript — no hay `tsconfig.json` ni archivos `.ts`/`.tsx` en `src/`.

## HTTPS (Semana 10)

`:443` sirve la SPA y el proxy sobre HTTPS con un certificado autofirmado de desarrollo (`certs/dev.crt`/`certs/dev.key` en la raíz del repo, generados con `certs/generate-dev-cert.sh` — no versionados). `:3000` solo redirige (`301`) hacia `:443`, salvo `/health`, que responde en HTTP puro para el healthcheck del propio contenedor. El tramo nginx → microservicios backend sigue en HTTP plano dentro de la red interna de Docker.

El contexto de build de este servicio es la **raíz del repo** (no `dashboard-service/`), porque el `Dockerfile` necesita copiar `certs/dev.crt`/`certs/dev.key` — ver `dockerfile: dashboard-service/Dockerfile` en `docker-compose.yml`.

## Rate limiting (Semana 10)

`ratelimit.conf` define la zona `api_zone` (1 request/segundo por IP, ráfaga de 20) a nivel `http` de nginx; `nginx.conf` la aplica con `limit_req` en cada `location /api/*`. Cubre floods generales a items, alertas, logs y estadísticas — además del límite específico que ya tenía login/registro en auth-service. Responde `429` (configurado con `limit_req_status 429`, en vez del `503` por defecto de nginx).

## Pantallas (`src/pages/`)

| Archivo | Qué muestra | Restricción por rol |
|---|---|---|
| `LoginPage.jsx` | Login y registro con validación en vivo | — |
| `LogsPage.jsx` | Logs en vivo con filtros | — |
| `StatsPage.jsx` | Estadísticas agregadas con gráficos (Recharts) | — |
| `AlertsPage.jsx` | Alertas con búsqueda/orden/detalle/gráfico por severidad | ciclo de vida (reconocer/cerrar) solo `admin` |
| `RulesPage.jsx` | Reglas de detección del motor de análisis, con tipo/severidad/parámetros y estado | activar/desactivar solo `admin` |
| `ItemsPage.jsx` | CRUD de artículos | crear: cualquier rol · editar/eliminar: solo `admin` |
| `UsersPage.jsx` | Gestión de usuarios (cambio de rol) | solo `admin` |

El botón **Cerrar sesión** llama a `POST /auth/logout` para revocar la sesión en Redis (server-side) antes de descartar el token local.

No hay una vista dedicada de "estado de los servicios" (health de cada microservicio) todavía.

## Variables de entorno

Ninguna en build-time más allá de lo que compila Vite; en runtime, `nginx.conf` fija los destinos del reverse proxy (`/api/auth`, `/api/logs`, `/api/analysis`, `/api/alerts`, `/api/items`).

## Tests

Este servicio no tiene tests automatizados propios todavía (no hay Jest, Vitest ni React Testing Library configurado en `package.json`).

## Levantar solo este servicio

```bash
docker compose up -d --build dashboard-service
```

## Desarrollo local sin Docker

```bash
cd dashboard-service
npm install
npm run dev
```
