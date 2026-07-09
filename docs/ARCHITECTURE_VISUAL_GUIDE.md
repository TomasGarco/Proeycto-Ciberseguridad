# Guía Visual: Arquitectura Completa del Sistema

Esta guía muestra visualmente cómo funciona el sistema.

---

## 1. Estructura de Carpetas

```
python-docker-service/
│
├── auth-service/
│   ├── app.py                 ← ~1800 líneas: API + Dashboard
│   ├── requirements.txt        ← Dependencias
│   └── Dockerfile             ← Imagen Docker (Python 3.12-slim)
│
├── log-service/
│   ├── app.py                 ← ~300 líneas: Logger + Console
│   ├── requirements.txt        ← Dependencias
│   └── Dockerfile             ← Imagen Docker
│
├── postgres-init/
│   └── 01-create-databases.sql ← Crea auth_db e items_db al primer arranque
│
├── data/
│   ├── auth.db                ← SQLite (solo fallback sin Docker)
│   └── items.db               ← SQLite (solo fallback sin Docker)
│
├── logs/
│   └── service.log            ← Archivo de logs persistente
│
├── docs/
│   ├── PROJECT_SUMMARY.md               ← Punto de entrada
│   ├── WEEKS_1-2_IMPLEMENTATION.md      ← Guía general
│   ├── AUTH_SERVICE_ARCHITECTURE.md     ← Guía detallada
│   └── ARCHITECTURE_VISUAL_GUIDE.md     ← Esta guía
│
├── docker-compose.yml         ← Orquestación de contenedores
├── README.md                  ← Punto de entrada del repo
└── run_local.bat              ← Script para Windows local (SQLite)
```

---

## 2. Flujo de Datos (Diagrama de Secuencia)

### Caso: Usuario nuevo se registra y crea un item

```
┌─────────┐                    ┌──────────────────┐          ┌─────────────┐
│ Browser │                    │  Auth Service    │          │ Log Service │
│ (Cliente)                    │  (Puerto 8000)   │          │ (8010)      │
└────┬────┘                    └────────┬─────────┘          └──────┬──────┘
     │                                  │                           │
     │ 1. GET http://localhost:8000     │                           │
     ├─────────────────────────────────>│                           │
     │                                  │                           │
     │ 2. Retorna HTML + Formulario     │                           │
     │<─────────────────────────────────┤                           │
     │                                  │                           │
     │ 3. Usuario completa formulario   │                           │
     │    y hace clic en "Registrarse"  │                           │
     │                                  │                           │
     │ 4. POST /auth/register           │                           │
     │    {"username": "john_doe",      │                           │
     │     "email": "john@....",        │                           │
     │     "password": "****"}          │                           │
     ├─────────────────────────────────>│                           │
     │                                  │ 5. Valida datos          │
     │                                  │ 6. Hash password         │
     │                                  │ 7. INSERT en auth_db     │
     │                                  │                           │
     │                                  │ 8. POST /logs (async)    │
     │                                  ├──────────────────────────>│
     │                                  │ (Background task, no espera)
     │                                  │                           │
     │ 9. Retorna usuario + status 201  │                           │
     │<─────────────────────────────────┤                           │
     │                                  │                           │
     │ 10. Hace clic en "Login"         │                           │
     │                                  │                           │
     │ 11. POST /auth/login             │                           │
     │     username=john_doe            │                           │
     │     password=****                │                           │
     ├─────────────────────────────────>│                           │
     │                                  │ 12. Verifica contraseña   │
     │                                  │ 13. Genera JWT token     │
     │                                  │                           │
     │                                  │ 14. POST /logs (async)   │
     │                                  ├──────────────────────────>│
     │                                  │                           │
     │ 15. Retorna token JWT            │                           │
     │<─────────────────────────────────┤                           │
     │                                  │                           │
     │ 16. Guarda token en localStorage │                           │
     │     Dashboard se actualiza       │                           │
     │                                  │                           │
     │ 17. Completa formulario de item  │                           │
     │     "Teclado Mecánico $89.99"    │                           │
     │                                  │                           │
     │ 18. POST /api/items              │                           │
     │     Authorization: Bearer <token>│                           │
     │     {"name": "Teclado...", ...}  │                           │
     ├─────────────────────────────────>│                           │
     │                                  │ 19. Valida token (JWT)   │
     │                                  │ 20. Extrae user_id       │
     │                                  │ 21. INSERT en items_db   │
     │                                  │     owner_id = user_id   │
     │                                  │                           │
     │                                  │ 22. POST /logs (async)   │
     │                                  ├──────────────────────────>│
     │                                  │                           │
     │ 23. Retorna item creado + 201    │                           │
     │<─────────────────────────────────┤                           │
     │                                  │                           │
     │ 24. Tabla actualiza, ve new item │                           │
     │                                  │                           │
     │ 25. Usuario vuelve a Log Service  │                           │
     │     http://localhost:8010        │                           │
     ├───────────────────────────────────────────────────────────────>│
     │                                  │ 26. Retorna HTML console  │
     │<────────────────────────────────────────────────────────────  │
     │     Ve logs en tiempo real:      │                           │
     │     [OK] "john_doe registrado"   │                           │
     │     [OK] "john_doe inició sesión"│                           │
     │     [OK] "john_doe creó Teclado" │                           │
```

---

## 3. Arquitectura de Datos

Actualizado en Semana 4: ambas bases migraron de SQLite a PostgreSQL (`auth_db`, `items_db`), corriendo en un contenedor `postgres` separado. La estructura de tablas es la misma — solo cambió el motor. Sin `POSTGRES_HOST`, el servicio cae a SQLite local para desarrollo sin Docker.

### Base de Datos: auth_db (PostgreSQL)

```
┌──────────────────────────────────────┐
│           Tabla: users               │
├──────────────────────────────────────┤
│ id │ username  │ email           │ ... │
├────┼───────────┼─────────────────┤     │
│ 1  │ admin     │ admin@localhost │ ... │
│ 2  │ john_doe  │ john@example    │ ... │
│ 3  │ jane_smith│ jane@example    │ ... │
└────┴───────────┴─────────────────┴─────┘
     │
     ├─ hashed_password: $2b$12$N9qo8uLOAe...
     ├─ role: "admin" / "analista"
     └─ created_at: 2026-07-02T10:30:00
```

### Base de Datos: items_db (PostgreSQL)

```
┌────────────────────────────────────────────────────┐
│              Tabla: items                          │
├────────────────────────────────────────────────────┤
│ id │ name       │ price   │ owner_id │ is_offer   │
├────┼────────────┼─────────┼──────────┼────────────┤
│ 1  │ Laptop     │ 2500.00 │ 1 (admin)│ true       │
│ 2  │ Mouse      │ 59.99   │ 1 (admin)│ false      │
│ 3  │ Teclado    │ 89.99   │ 2 (john) │ true       │
└────┴────────────┴─────────┴──────────┴────────────┘
     │
     ├─ description: "RTX 3090"
     └─ created_at: 2026-07-02T11:15:00
```

---

## 4. Flujo de Autenticación JWT

```
┌──────────────────────────────────────────────────┐
│       FLUJO DE AUTENTICACIÓN CON JWT             │
└──────────────────────────────────────────────────┘

1. REGISTRO
    ┌─────────────────┐
    │ POST /register  │
    ├─────────────────┤
    │ username        │
    │ email           │
    │ password (plano)│
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ hash_password()         │
    │ + bcrypt                │
    │ = hashed_password       │
    └────────┬────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ INSERT usuario en BD    │
    │ [OK] Usuario registrado │
    └─────────────────────────┘

2. LOGIN
    ┌─────────────────┐
    │ POST /login     │
    ├─────────────────┤
    │ username        │
    │ password (plano)│
    └────────┬────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ SELECT usuario FROM auth_db     │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ verify_password(plano, hashed)  │
    │ ¿Coinciden?                     │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ create_access_token()           │
    │ ┌───────────────────────────┐   │
    │ │ Payload:                  │   │
    │ │ {                         │   │
    │ │   "sub": "john_doe",      │   │
    │ │   "user_id": 2,           │   │
    │ │   "role": "analista",     │   │
    │ │   "exp": 1684423200       │   │
    │ │ }                         │   │
    │ └───────────────────────────┘   │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────┐
    │ jwt.encode(payload,             │
    │            SECRET_KEY,          │
    │            algorithm=HS256)     │
    │                                 │
    │ = eyJhbGciOiJIUzI1NiIs... (60)  │
    └────────┬────────────────────────┘
             │
             ▼
    ┌─────────────────────────┐
    │ Retorna token al cliente│
    │ localStorage.token =... │
    └─────────────────────────┘

3. USO DEL TOKEN (Endpoints protegidos)
    ┌──────────────────────────────┐
    │ GET /auth/me                 │
    ├──────────────────────────────┤
    │ Headers:                     │
    │ Authorization: Bearer <token>│
    └────────┬─────────────────────┘
             │
             ▼
    ┌──────────────────────────────────┐
    │ get_current_user() dependency    │
    │ ┌──────────────────────────────┐ │
    │ │ 1. Extrae token del header  │ │
    │ │ 2. jwt.decode(token, key)   │ │
    │ │ 3. Obtiene "sub" (username) │ │
    │ │ 4. SELECT usuario FROM BD   │ │
    │ │ 5. Retorna usuario objeto   │ │
    │ └──────────────────────────────┘ │
    └────────┬─────────────────────────┘
             │
             ▼
    ┌──────────────────────────┐
    │ [OK] Acceso permitido    │
    │ Endpoint ejecutado       │
    └──────────────────────────┘

4. EXPIRACIÓN DE TOKEN
    ┌──────────────────────────┐
    │ Token válido por 60 min  │
    │ exp = ahora + 3600 seg   │
    └────────┬─────────────────┘
             │
             ▼
    Después de 60 minutos:
    ┌──────────────────────────────┐
    │ [ERROR] 401 Unauthorized     │
    │ "Token expirado"             │
    │ → Usuario debe login de nuevo│
    └──────────────────────────────┘
```

---

## 5. Control de Acceso por Roles (RBAC)

```
┌─────────────────────────────────────────────────────┐
│         MATRIZ DE CONTROL DE ACCESO                 │
├─────────────────────────────────────────────────────┤

ROLE: "analista" (Usuario normal)
  [SI] POST /auth/register          → Registrarse
  [SI] POST /auth/login              → Iniciar sesión
  [SI] GET  /auth/me                 → Ver su propio perfil
  [NO] GET  /auth/users              → Ver todos (SOLO ADMIN)
  [SI] GET  /api/items               → Ver productos
  [SI] POST /api/items               → Crear producto (owner_id = su_id)
  [NO] PUT  /api/items/{id}          → Actualizar (SOLO ADMIN)
  [NO] DELETE /api/items/{id}        → Eliminar (SOLO ADMIN)

ROLE: "admin" (Administrador)
  [SI] POST /auth/register           → Registrarse
  [SI] POST /auth/login              → Iniciar sesión
  [SI] GET  /auth/me                 → Ver su propio perfil
  [SI] GET  /auth/users              → Ver todos ← especial
  [SI] GET  /api/items               → Ver todos
  [SI] POST /api/items               → Crear producto
  [SI] PUT  /api/items/{id}          → Actualizar cualquier ← especial
  [SI] DELETE /api/items/{id}        → Eliminar cualquiera ← especial

Dependency: require_admin()
┌────────────────────────────────────┐
│ if current_user.role != "admin":   │
│   raise HTTPException(403)          │
│ return current_user                 │
└────────────────────────────────────┘
```

---

## 6. Seguridad en Capas

```
┌──────────────────────────────────────────┐
│     SEGURIDAD EN CAPAS DEL SISTEMA       │
├──────────────────────────────────────────┤

Capa 1: Contraseñas
   ├─ Almacenadas hasheadas con bcrypt
   ├─ Nunca en texto plano
   └─ Verificación segura: verify_password()

Capa 2: Autenticación
   ├─ JWT con firma HMAC-SHA256
   ├─ Token con expiración (60 min)
   ├─ Almacenado en localStorage (cliente)
   └─ Validación en cada request

Capa 3: Autorización
   ├─ RBAC: roles "analista" y "admin"
   ├─ Dependencias: Depends(get_current_user)
   ├─ Control granular por endpoint
   └─ 403 Forbidden si no autorizado

Capa 4: Comunicación
   ├─ HTTP plano entre servicios (red interna de Docker, no expuesta al host)
   ├─ HTTPS en el navegador (Semana 10): dashboard-service/nginx termina TLS en :443
   └─ CORS restringido a un origen específico (CORS_ORIGINS, no "todos los orígenes")

Capa 5: Base de Datos
   ├─ PostgreSQL (Docker) / SQLite (fallback local)
   ├─ Bases de auth e items aisladas entre sí
   └─ Foreign keys para integridad

ENDURECIDO EN SEMANA 10 (ya no son recomendaciones pendientes):
   ├─ JWT_SECRET_KEY es una variable de entorno con secreto real generado (no hardcodeado)
   ├─ HTTPS habilitado en el punto de entrada del navegador (certificado autofirmado de desarrollo)
   ├─ Rate limiting: login (5 fallos/60s), registro (10/5min por IP), y general en nginx (1 req/s por IP)
   ├─ Logging estructurado en JSON en los 5 servicios; Log Service persiste en MongoDB (no en memoria) desde la Semana 4
   └─ Backups: manual (scripts/backup.sh) + automático (Tarea Programada de Windows, diario 3 AM)
```

---

## 7. Comunicación Entre Servicios

```
┌──────────────────────────────────────────────┐
│    AUTH SERVICE  <->  LOG SERVICE            │
├──────────────────────────────────────────────┤

Auth Service (8000)              Log Service (8010)
      │                                 │
      │  Evento: Usuario se registró    │
      ├────────────────────────────────>│
      │  POST /logs                      │
      │  {                               │
      │    "service": "auth-service",    │
      │    "level": "INFO",              │
      │    "message": "User 'john'...",  │
      │    "timestamp": "2026-07-..."    │
      │  }                               │
      │                                  │
      │  ← 201 Created                   │
      │<─────────────────────────────────┤
      │                                  │
      │  Evento: Usuario inició sesión   │
      ├────────────────────────────────>│
      │  POST /logs                      │
      │  (Background Task - no espera)   │
      │                                  │
      │  ← 201 Created                   │
      │<─────────────────────────────────┤
      │                                  │
      │  (Más eventos: create, update,   │
      │   delete items, etc.)            │
      │                                  │
      │  Log Service almacena todos      │
      │  en memoria + archivo log        │

Log Service internamente:
┌─────────────────────────────────────┐
│ GET /logs                           │
├─────────────────────────────────────┤
│ in_memory_logs = [               │
│   {"service": "auth-service",    │
│    "level": "INFO",              │
│    "message": "..."},            │
│   ...                            │
│ ]                                │
│                                 │
│ Filtra por:                      │
│ - level (INFO, WARNING, ERROR)   │
│ - service (auth-service)         │
│ - limit (últimos 100)            │
│ - timestamp                      │
└─────────────────────────────────────┘
```

---

## 8. Flujo Visual del Dashboard

```
┌────────────────────────────────────────────────────┐
│         INTERFAZ DEL DASHBOARD (Auth Service)      │
├────────────────────────────────────────────────────┤

[No autenticado]
┌──────────────────────────────────────────────────┐
│  Python CRUD API Service                         │
├──────────────────────────────────────────────────┤
│                                                  │
│  Por favor, inicia sesión                        │
│                                                  │
│  Username: [________________]                   │
│  Password: [________________]                   │
│  [Ingresar]  [¿No tienes cuenta? Registrate]   │
│                                                  │
└──────────────────────────────────────────────────┘

[Autenticado como "john_doe" (analista)]
┌──────────────────────────────────────────────────┐
│  Python CRUD API Service                         │
├──────────────────────────────────────────────────┤
│                                                  │
│  Bienvenido, john_doe (analista)                     │
│  [Cerrar sesión]                                │
│                                                  │
│  ┌─ Inventario de Productos ──────────────────┐ │
│  │                                              │ │
│  │ Laptop Gaming         │ $2500.00  (analista)    │ │
│  │ Mouse Gamer          │ $59.99    (analista)    │ │
│  │ Monitor 4K           │ $349.99   (analista)    │ │
│  │ Teclado Mecánico     │ $89.99    (analista)    │ │
│  │                                              │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  ┌─ Agregar Nuevo Producto ──────────────────┐ │
│  │ Nombre: [_______________________]         │ │
│  │ Descripción: [___________________]        │ │
│  │ Precio: [$____________]                    │ │
│  │ [ ] Es una oferta especial                 │ │
│  │ [Guardar Producto]                         │ │
│  └──────────────────────────────────────────────┘ │
│                                                  │
│  Accesos Rápidos:                               │
│  [Swagger UI]  [Log Console]  [Documentación]   │
│                                                  │
└──────────────────────────────────────────────────┘

[Autenticado como "admin" (admin)]
                (mismo layout, pero además)
                Botón "eliminar" visible por item
                Botón "actualizar" visible por item
```

---

## 9. Stack Tecnológico

```
┌────────────────────────────────────────────────┐
│           STACK COMPLETO DEL SISTEMA            │
├────────────────────────────────────────────────┤

Backend API:
  ├─ Python 3.12
  ├─ FastAPI (framework web)
  ├─ Uvicorn (servidor ASGI)
  ├─ SQLAlchemy (ORM)
  ├─ PostgreSQL (BD principal, Docker) / SQLite (fallback local)
  ├─ psycopg2-binary (driver Postgres)
  ├─ python-jose (tokens JWT)
  ├─ Passlib + bcrypt (hashing)
  └─ Requests (HTTP client)

Frontend:
  ├─ HTML5 embebido en Python (sin build step)
  ├─ CSS3 (variables, grid, flexbox)
  ├─ JavaScript vanilla
  ├─ Fetch API
  ├─ Lucide Icons (SVG inline, sin CDN)
  └─ localStorage (JWT storage)

Documentación:
  ├─ FastAPI OpenAPI/Swagger (tema personalizado en /docs)
  ├─ Markdown docs (servidos también dentro del dashboard vía /documentation)
  └─ Diagramas Mermaid (en README.md)

DevOps:
  ├─ Docker (containerización)
  ├─ Docker Compose (orquestación de 3 servicios: postgres, auth-service, log-service)
  ├─ Healthcheck de Postgres antes de arrancar Auth Service
  └─ Volúmenes persistentes (postgres_data, log_data)

Herramientas:
  ├─ Git (versionado)
  ├─ Bash/PowerShell (scripts)
  └─ cURL/Postman (testing manual)
```

---

## 10. Tabla de Decisiones Arquitectónicas

```
┌────────────────────────────────────────────────────┐
│     DECISIONES ARQUITECTÓNICAS Y RAZONES           │
├────────────────────────────────────────────────────┤

Dos BD separadas (auth_db + items_db)
   ├─ ¿Por qué? Separación de responsabilidades
   ├─ Ventaja: Escalabilidad futura
   └─ Posibilidad: Migrar cada una independientemente

JWT para autenticación
   ├─ ¿Por qué? Stateless, sin sesiones
   ├─ Ventaja: Escala horizontalmente
   └─ Ideal para microservicios

BackgroundTasks para logging
   ├─ ¿Por qué? No bloquea respuesta al cliente
   ├─ Ventaja: API rápida
   └─ Desventaja: Logs pueden perderse (no crítico)

PostgreSQL en Docker, SQLite como fallback
   ├─ ¿Por qué? Postgres refleja producción, SQLite simplifica dev sin Docker
   ├─ Estado: Migrado en Semana 4
   └─ Log Service usa MongoDB (también migrado en Semana 4), no Postgres

HTML embebido en FastAPI
   ├─ ¿Por qué? Dashboard simple, all-in-one
   ├─ Desventaja: Hacía app.py muy largo
   └─ Estado: reemplazado por el dashboard React en Semana 7 — el HTML embebido sigue existiendo como consola secundaria en :8000, sin tocar

Docker Compose con volúmenes
   ├─ ¿Por qué? Persistencia entre reinicios
   ├─ Ventaja: Datos no se pierden
   └─ Ideal para desarrollo y testing

Rate limiting (Semana 10 — ya implementado)
   ├─ Login: 5 fallos/60s bloquean 60s por usuario
   ├─ Registro: 10 registros/5min bloquean por IP
   └─ General: 1 req/s por IP en nginx (todo /api/*)

HTTPS (Semana 10 — ya implementado)
   ├─ nginx (dashboard-service) sirve el navegador por :443 con certificado autofirmado
   ├─ El tramo nginx → microservicios sigue en HTTP, dentro de la red interna de Docker
   └─ Para producción real: reemplazar el certificado por uno de una autoridad certificadora
```

---

## 11. Checklist de Comprensión

Puntos clave para verificar que la arquitectura quedó clara:

```
- ¿Cómo funciona el flujo de login? (JWT encoding)
- ¿Qué hace get_current_user()? (Dependency injection)
- ¿Por qué dos bases de datos? (Separación de responsabilidades)
- ¿Cómo se validan las requests? (Pydantic schemas)
- ¿Qué es owner_id en items? (Foreign key lógica)
- ¿Por qué BackgroundTasks? (Non-blocking)
- ¿Cómo se protegen los endpoints? (Depends + roles)
- ¿Qué hace hash_password()? (bcrypt encryption)
- ¿Cómo comunica Auth -> Log? (HTTP POST async)
- ¿Por qué Lucide icons? (Sin dependencia de CDN, consistencia visual)
```

---

## 12. Troubleshooting Visual

```
"401 Unauthorized en /auth/me"
   Problema: Token no enviado o inválido
      Solución 1: Hacer login de nuevo
      Solución 2: Verificar header "Authorization: Bearer <token>"

"403 Forbidden en PUT /api/items/{id}"
   Problema: Tu usuario no es admin
      Solución: Usa admin/admin123 o pide a un admin

"400 Bad Request en POST /auth/register"
   Problema: Usuario/email ya existe
      Solución: Elige otro username

"404 Not Found en GET /api/items/{id}"
   Problema: Item no existe o fue eliminado
      Solución: Verifica el ID en la lista

"Connection refused 8010"
   Problema: Log Service no está corriendo
      Solución: docker compose up -d --build

"Token expirado después de 1 hora"
   Esperado: sí, por diseño (60 min)
      Solución: Re-login
      Cambio: editar ACCESS_TOKEN_EXPIRE_MINUTES en auth-service/app.py

"FATAL: database auth_db does not exist" (al levantar Postgres)
   Problema: el volumen postgres_data ya existía de un intento previo sin el script de init
      Solución: docker compose down; docker volume rm python-docker-service_postgres_data; docker compose up -d
```
