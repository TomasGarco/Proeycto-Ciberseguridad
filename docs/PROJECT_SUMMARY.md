<img src="https://cdn.jsdelivr.net/npm/lucide-static@latest/icons/graduation-cap.svg" width="24" height="24" align="left" style="margin-right:8px;" />

# Guía de Estudio — Resumen del Proyecto

**Propósito de este documento:** un único punto de entrada para explicar el proyecto de memoria — qué es, por qué existe, qué se construyó, cómo funciona y qué falta. No repite el contenido de los otros documentos, los enlaza en el orden en que conviene leerlos.

---

## 1. El elevator pitch (30 segundos)

> "Es una plataforma SOC/SIEM — un sistema de monitoreo de seguridad que recolecta logs, los analiza y genera alertas. Son 5 microservicios en 8 contenedores Docker: autenticación con JWT y roles (FastAPI + PostgreSQL), recolección de logs (FastAPI + MongoDB), análisis con un motor de reglas de detección que evalúa severidad (umbral, patrón, palabra clave), gestión de alertas con ciclo de vida de incidentes (Node.js + PostgreSQL) y un dashboard en React. Los servicios se comunican de forma asíncrona por RabbitMQ y Redis actúa como capa de caché de las estadísticas. La arquitectura objetivo del roadmap está completa."

## 2. Qué es un SOC/SIEM (el contexto de negocio)

- **SOC (Security Operations Center):** el equipo/proceso que detecta y responde a incidentes de seguridad en tiempo real.
- **SIEM (Security Information and Event Management):** la tecnología que alimenta al SOC — recolecta logs de múltiples fuentes, los correlaciona y genera alertas.
- **Por qué importa la gestión de logs:** sin recolección y normalización de eventos, es imposible detectar amenazas, correlacionar incidentes o cumplir marcos como ISO 27001, NIST o PCI-DSS.

Detalle completo del objetivo, alcance y arquitectura: **[`README.md`](../README.md)** (sección "Diseño y Arquitectura").

## 3. Qué existe hoy — el estado real del código

Ocho contenedores orquestados con `docker-compose.yml`: los 5 servicios de aplicación (Auth, Log, Analysis, Alert, Dashboard) más PostgreSQL, MongoDB y RabbitMQ. Detalle de puertos, responsabilidades y variables de conexión: **[`README.md`](../README.md)** (secciones "Diseño y Arquitectura" y "Persistencia de Datos en Docker").

La comunicación es asíncrona en dos tramos vía RabbitMQ: Log Service publica cada evento al exchange `logs_events` (lo consume Analysis Service) y Analysis Service publica cada alerta disparada al exchange `alerts_events` (lo consume Alert Service, que la persiste en PostgreSQL). Solo el tramo Auth → Log es HTTP directo (`requests` + `BackgroundTasks` de FastAPI).

## 4. El roadmap de 10 semanas — qué está hecho y qué no

Semanas 1–9 completadas: autenticación JWT con roles (1–3), persistencia PostgreSQL y MongoDB (4–5), mensajería RabbitMQ (6), dashboard React (7), motor de reglas de detección + Alert Service con ciclo de vida de incidentes (8), Redis como capa de caché de estadísticas (9). Lo que queda por delante son refinamientos, no piezas de arquitectura.

## 5. La arquitectura final (completa)

Los 5 microservicios existen y están conectados — Auth (FastAPI), Log (FastAPI), **Analysis** (Python, motor de reglas), **Alert** (Node.js/Express), **Dashboard** (React) — sobre PostgreSQL + MongoDB + RabbitMQ + Redis. Es la arquitectura objetivo del roadmap, sin piezas pendientes. Diagrama completo: **[`README.md`](../README.md)** sección "Diseño y Arquitectura".

## 6. Cómo explicar el flujo técnico (para una demo en vivo)

El recorrido completo — usuario se registra → hace login → recibe JWT → crea un item → el evento se loguea de forma asíncrona — está diagramado paso a paso (con diagrama de secuencia ASCII) en:
**[`docs/ARCHITECTURE_VISUAL_GUIDE.md`](ARCHITECTURE_VISUAL_GUIDE.md)** — empieza por la sección 2 ("Flujo de Datos") si vas a hacer una demo en vivo; tiene también el flujo de JWT (sección 4), RBAC por roles (sección 5) y seguridad en capas (sección 6).

## 7. Cómo explicar el código línea por línea (si preguntan detalle técnico)

Cada endpoint, modelo ORM, schema Pydantic y función de seguridad explicados uno por uno, con el código real al lado:
**[`docs/AUTH_SERVICE_ARCHITECTURE.md`](AUTH_SERVICE_ARCHITECTURE.md)** — usa la Tabla de Contenidos del propio archivo para saltar directo a lo que te pregunten (ej. "¿cómo funciona el hash de contraseñas?" → sección `hash_password()`).

## 8. Cómo levantar y probar el proyecto en vivo

Comandos exactos, API reference completa con ejemplos de request/response, troubleshooting de errores comunes (puerto ocupado, Docker no corre, token expirado, etc.):
**[`docs/WEEKS_1-2_IMPLEMENTATION.md`](WEEKS_1-2_IMPLEMENTATION.md)**

## 9. Si vas a tocar el código (convenciones técnicas)

Lo esencial: cada servicio copia su código en build-time (no hay volumen montado), así que **después de editar hay que reconstruir** — `docker compose build <servicio> && docker compose up -d <servicio>`. Estilo: español en docstrings/mensajes de error/UI, 4 espacios en Python, modelos Pydantic con `Field(..., example=...)`, clases ORM con sufijo `ORM`. Los comandos de build, inspección de bases de datos y ejecución local están en **[`docs/WEEKS_1-2_IMPLEMENTATION.md`](WEEKS_1-2_IMPLEMENTATION.md#command--script-reference)**.

## 10. Tabla completa de comandos y scripts

Cada comando de Docker Compose, cada script (`run_local.bat`, `test_crud.py`) y cada archivo de inicialización (`postgres-init/`) explicados uno por uno — qué hace exactamente, cuándo usarlo, y qué pasa si sale mal:
**[`docs/WEEKS_1-2_IMPLEMENTATION.md`](WEEKS_1-2_IMPLEMENTATION.md#command--script-reference)** — sección "Command & Script Reference"

## 11. Preguntas que probablemente te hagan (y dónde está la respuesta)

| Pregunta | Dónde está la respuesta |
|---|---|
| "¿Por qué dos bases de datos separadas en vez de una?" | `docs/AUTH_SERVICE_ARCHITECTURE.md` → sección "Base de Datos" |
| "¿Cómo se protege la contraseña?" | `docs/AUTH_SERVICE_ARCHITECTURE.md` → `hash_password()` (bcrypt, nunca texto plano) |
| "¿Qué pasa si el token expira?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Token expired" en Troubleshooting |
| "¿Por qué colas de mensajes y no HTTP entre servicios?" | Este documento, sección 3, y `README.md` → sección de RabbitMQ (desacople: un servicio caído no tumba a los demás) |
| "¿Qué le falta al proyecto para estar completo?" | Este documento, secciones 4 y 5 (la arquitectura está completa; lo excluido a propósito —ML, cloud, SOAR— está en el alcance del proyecto) |
| "¿Cómo se controla qué puede hacer un admin vs un user?" | `docs/ARCHITECTURE_VISUAL_GUIDE.md` → sección 5 (RBAC) |
| "¿Cómo pruebo la API sin escribir código?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Testing Endpoints" (Swagger UI en `/docs`) |
| "¿Qué hace exactamente cada comando/script del proyecto?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Command & Script Reference" |
