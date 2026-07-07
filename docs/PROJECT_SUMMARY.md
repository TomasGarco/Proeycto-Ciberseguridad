<img src="https://cdn.jsdelivr.net/npm/lucide-static@latest/icons/graduation-cap.svg" width="24" height="24" align="left" style="margin-right:8px;" />

# Guía de Estudio — Resumen del Proyecto

**Propósito de este documento:** un único punto de entrada para explicar el proyecto de memoria — qué es, por qué existe, qué se construyó, cómo funciona y qué falta. No repite el contenido de los otros documentos, los enlaza en el orden en que conviene leerlos.

---

## 1. El elevator pitch (30 segundos)

> "Es la base de una plataforma SOC/SIEM — un sistema de monitoreo de seguridad que recolecta logs, los analiza y genera alertas. Ahora mismo tengo construida la parte de autenticación y el motor CRUD: cuatro contenedores en Docker (Auth Service, Log Service, PostgreSQL y MongoDB), con login JWT, control de roles, dos bases de datos Postgres aisladas, logs persistidos en MongoDB y un dashboard web. Cubre las Semanas 1 a 5 de un roadmap de 10 semanas (aunque Mongo aún no se verificó end-to-end); lo que falta es sumar colas de mensajes (RabbitMQ), un motor de reglas de detección y un dashboard en React."

## 2. Qué es un SOC/SIEM (el contexto de negocio)

- **SOC (Security Operations Center):** el equipo/proceso que detecta y responde a incidentes de seguridad en tiempo real.
- **SIEM (Security Information and Event Management):** la tecnología que alimenta al SOC — recolecta logs de múltiples fuentes, los correlaciona y genera alertas.
- **Por qué importa la gestión de logs:** sin recolección y normalización de eventos, es imposible detectar amenazas, correlacionar incidentes o cumplir marcos como ISO 27001, NIST o PCI-DSS.

Detalle completo del objetivo, alcance y arquitectura final propuesta: **[`README.md`](../README.md)**.

## 3. Qué existe hoy — el estado real del código

Cuatro contenedores orquestados con `docker-compose.yml` (Auth Service, Log Service, PostgreSQL, MongoDB). Detalle de puertos, responsabilidades y variables de conexión: **[`README.md`](../README.md)** (secciones "Diseño y Arquitectura" y "Persistencia de Datos en Docker").

Auth Service y Log Service se comunican por HTTP síncrono (`requests` + `BackgroundTasks` de FastAPI) — **no hay cola de mensajes todavía**, eso es Semana 6.

Nota de estado: la integración de MongoDB en Log Service (Semana 4) está implementada en el código pero **no verificada end-to-end** — ver [`README.md`](../README.md) sección "Estado actual vs. objetivo final".

## 4. El roadmap de 10 semanas — qué está hecho y qué no

Tabla completa con detalle de entregables y estado de cada semana: **[`README.md`](../README.md)** (sección "Estado del Roadmap").

## 5. Cómo se ve la arquitectura final (a la que se llega en la Semana 9)

5 microservicios en vez de 2 — Auth (FastAPI), Log (FastAPI), **Analysis** (Python, motor de reglas), **Alert** (Node.js/Express), **Dashboard** (React) — sobre PostgreSQL + MongoDB + RabbitMQ + Redis. Diagrama completo y qué hace cada servicio nuevo: **[`README.md`](../README.md)** sección "Arquitectura objetivo".

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

Cómo está organizado el repo, por qué hay que reconstruir la imagen Docker después de cada cambio (no hay volumen montado — el código se copia en build-time), estilo de código, cómo correr el único test que existe:
**[`README.md`](../README.md)**

## 10. Tabla completa de comandos y scripts

Cada comando de Docker Compose, cada script (`run_local.bat`, `test_crud.py`) y cada archivo de inicialización (`postgres-init/`) explicados uno por uno — qué hace exactamente, cuándo usarlo, y qué pasa si sale mal:
**[`docs/WEEKS_1-2_IMPLEMENTATION.md`](WEEKS_1-2_IMPLEMENTATION.md#command--script-reference)** — sección "Command & Script Reference"

## 11. Preguntas que probablemente te hagan (y dónde está la respuesta)

| Pregunta | Dónde está la respuesta |
|---|---|
| "¿Por qué dos bases de datos separadas en vez de una?" | `docs/AUTH_SERVICE_ARCHITECTURE.md` → sección "Base de Datos" |
| "¿Cómo se protege la contraseña?" | `docs/AUTH_SERVICE_ARCHITECTURE.md` → `hash_password()` (bcrypt, nunca texto plano) |
| "¿Qué pasa si el token expira?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Token expired" en Troubleshooting |
| "¿Por qué HTTP y no cola de mensajes para los logs?" | `docs/ARCHITECTURE_VISUAL_GUIDE.md` → sección 7, y `README.md` (es justamente lo que cambia en Semana 6) |
| "¿Qué le falta al proyecto para estar completo?" | Este documento, sección 4, o `README.md` completo |
| "¿Cómo se controla qué puede hacer un admin vs un user?" | `docs/ARCHITECTURE_VISUAL_GUIDE.md` → sección 5 (RBAC) |
| "¿Cómo pruebo la API sin escribir código?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Testing Endpoints" (Swagger UI en `/docs`) |
| "¿Qué hace exactamente cada comando/script del proyecto?" | `docs/WEEKS_1-2_IMPLEMENTATION.md` → "Command & Script Reference" |
