# Dashboard Service

React (JavaScript + JSX, **no TypeScript**) · Vite · Recharts · Axios · nginx · Puerto `3000`

## Qué hace

Frontend y punto de entrada principal de la plataforma. nginx sirve la SPA compilada y además actúa como reverse proxy: todas las llamadas del navegador van a `/api/*` en este mismo origen y nginx las reenvía internamente a auth-service, log-service, analysis-service y alert-service — así no hay problemas de CORS entre pestañas.

**Nota sobre el stack:** el proyecto usa JavaScript con JSX, no TypeScript — no hay `tsconfig.json` ni archivos `.ts`/`.tsx` en `src/`.

## Pantallas (`src/pages/`)

| Archivo | Qué muestra | Restricción por rol |
|---|---|---|
| `LoginPage.jsx` | Login y registro con validación en vivo | — |
| `LogsPage.jsx` | Logs en vivo con filtros | — |
| `StatsPage.jsx` | Estadísticas agregadas con gráficos (Recharts) | — |
| `AlertsPage.jsx` | Alertas con búsqueda/orden/detalle/gráfico por severidad | ciclo de vida (reconocer/cerrar) solo `admin` |
| `ItemsPage.jsx` | CRUD de artículos | crear: cualquier rol · editar/eliminar: solo `admin` |
| `UsersPage.jsx` | Gestión de usuarios (cambio de rol) | solo `admin` |

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
