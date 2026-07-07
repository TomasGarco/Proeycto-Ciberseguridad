# Week 1-2 Implementation Guide: Docker + FastAPI CRUD

This guide documents what has been implemented in **Week 1 (Docker Fundamentals)** and **Week 2 (FastAPI REST API + CRUD)**, updated to reflect the **Week 4 (PostgreSQL migration)** state of the codebase.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture Overview](#architecture-overview)
3. [API Reference](#api-reference)
4. [Database Design](#database-design)
5. [Authentication & Authorization](#authentication--authorization)
6. [Development Workflow](#development-workflow)
7. [Background Logging](#background-logging)
8. [Command & Script Reference](#command--script-reference)
9. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Quick Start

### Option A: Docker Compose (Recommended)

Requires Docker Desktop running.

```bash
# 1. Build and start postgres, auth-service and log-service in background
docker compose up -d --build

# 2. Access in browser:
#    http://localhost:8000        Auth Service Dashboard
#    http://localhost:8000/docs   Swagger UI (API Documentation)
#    http://localhost:8010        Log Service Console
#    localhost:5432               PostgreSQL (auth_db, items_db)

# 3. View logs:
docker compose logs -f

# 4. Stop services:
docker compose down
```

**First test:**
- Login with credentials: `admin` / `admin123`
- Create a new product: fill the form and click "Guardar Producto"
- See the item appear in the "Inventario de Productos" list
- Click Swagger UI link to explore all endpoints

### Option B: Local Development (Windows, SQLite fallback)

Requires Python 3.10+ and local `venv` already created. Without `POSTGRES_HOST` set, `auth-service` automatically uses local SQLite files (`data/auth.db`, `data/items.db`) instead of Postgres.

```bash
# 1. Run the startup script (opens two command windows)
./run_local.bat

# 2. Access in browser:
#    http://localhost:8000        Auth Service & Dashboard
#    http://localhost:8010        Log Service Monitor

# 3. Stop: Close the command windows or press Ctrl+C
```

---

## Architecture Overview

### System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Developer/Client                      │
│                    (Browser @ localhost)                     │
└──────┬──────────────────────────────┬───────────────────────┘
       │                              │
       │ HTTP 8000                    │ HTTP 8010
       ▼                              ▼
┌──────────────────────┐    ┌─────────────────────┐
│  Auth Service (8000) │    │ Log Service (8010)  │
│  ──────────────────  │    │ ───────────────────  │
│ - Register/Login     │    │ - Receive logs      │
│ - JWT Token Mgmt     │    │ - Store in memory   │
│ - CRUD Items         │───→│ - HTML console      │
│ - Dashboard (HTML)   │HTTP│ - REST GET /logs    │
└──────────┬───────────┘(BackgroundTasks)
           │
           ▼
    ┌──────────────────┐
    │  PostgreSQL       │
    │ ──────────────── │
    │ - auth_db         │
    │   (Users, Auth)  │
    │ - items_db        │
    │   (Products)     │
    └──────────────────┘
```

### Containers

**Auth Service** (port 8000)
- Main FastAPI application
- Handles registration, login, JWT token generation
- Implements CRUD for products/items
- Serves HTML dashboard at `/`
- Serves the repo's Markdown docs at `/documentation/{doc_id}`
- Sends asynchronous logs to Log Service

**Log Service** (port 8010)
- FastAPI log aggregator
- Receives log events from Auth Service
- Stores logs in memory (max 500 entries) and appends to `logs/service.log`
- Serves HTML console for real-time log viewing
- Provides REST endpoint to query logs

**PostgreSQL** (port 5432)
- Single Postgres 16 server hosting two isolated databases
- Databases are created once via `postgres-init/01-create-databases.sql` on first container startup
- Has a `pg_isready` healthcheck; `auth-service` won't start until it passes

### Networking

All three containers run inside Docker Compose's default bridge network. The Auth Service connects to the Log Service via `LOG_SERVICE_URL=http://log-service:8010`, and to Postgres via `POSTGRES_HOST=postgres`.

### Databases

**PostgreSQL (two separate databases, one server)**

1. **`auth_db`** – User authentication & profiles
   - Table: `users` (id, username, email, hashed_password, role, created_at)
   - Persisted via Docker volume `postgres_data`

2. **`items_db`** – Product inventory (CRUD)
   - Table: `items` (id, name, description, price, is_offer, owner_id)
   - Persisted via the same `postgres_data` volume (different database, same server)

Without Docker / without `POSTGRES_HOST`, both fall back to local SQLite files with the same table structure.

---

## API Reference

All endpoints are documented interactively at `http://localhost:8000/docs` (Swagger UI, with a custom theme).

### Authentication Endpoints

#### `POST /auth/register`
**Register a new user** (creates account with role = `user`)

**Request body:**
```json
{
  "username": "john_doe",
  "email": "john@example.com",
  "password": "secure_password_123"
}
```

**Response (201 Created):**
```json
{
  "id": 2,
  "username": "john_doe",
  "email": "john@example.com",
  "role": "user",
  "created_at": "2026-07-02T10:30:45.123Z"
}
```

**cURL example:**
```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "email": "john@example.com",
    "password": "secure_password_123"
  }'
```

---

#### `POST /auth/login`
**Authenticate and receive JWT token** (Bearer token format)

**Request body (form-data):**
```
username=admin
password=admin123
```

**Response (200 OK):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**How to use the token:**
1. Copy the `access_token` value
2. Attach it to subsequent requests in the `Authorization` header:
   ```
   Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```
3. In Swagger UI: Click "Authorize" button, paste token, click "Authorize"

**cURL example:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123"
```

**Token expiry:** 60 minutes from issuance (`ACCESS_TOKEN_EXPIRE_MINUTES` in `auth-service/app.py`)

---

#### `GET /auth/me`
**Get current authenticated user's profile**

**Headers required:**
```
Authorization: Bearer <token>
```

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "admin",
  "email": "admin@example.com",
  "role": "admin",
  "created_at": "2026-07-01T00:00:00.000Z"
}
```

**cURL example:**
```bash
curl -X GET http://localhost:8000/auth/me \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

#### `POST /auth/change-password`
**Change the authenticated user's password**

**Headers required:**
```
Authorization: Bearer <token>
```

**Request body:**
```json
{
  "current_password": "admin123",
  "new_password": "newpassword456"
}
```

**Response (200 OK):**
```json
{"status": "success", "message": "Contraseña actualizada correctamente."}
```

**Error responses:** 400 if `current_password` doesn't match, 422 if `new_password` is under 6 characters.

---

#### `GET /auth/users`
**List all users** (admin only)

**Headers required:**
```
Authorization: Bearer <token>  (admin token)
```

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "role": "admin",
    "created_at": "2026-07-01T00:00:00.000Z"
  },
  {
    "id": 2,
    "username": "john_doe",
    "email": "john@example.com",
    "role": "user",
    "created_at": "2026-07-02T10:30:45.123Z"
  }
]
```

**Authorization:** Admin role required. Non-admin request returns 403 Forbidden.

---

### Items Endpoints (CRUD)

#### `GET /api/items`
**List all items**

**Headers required:**
```
Authorization: Bearer <token>
```

**Query parameters:**
- `skip` (int, optional): Pagination offset (default 0)
- `limit` (int, optional): Max results (default 100)

**Response (200 OK):**
```json
[
  {
    "id": 1,
    "name": "Teclado Mecánico",
    "description": "RGB con switches cherry brown",
    "price": 89.99,
    "is_offer": true,
    "owner_id": 1
  },
  {
    "id": 3,
    "name": "Monitor 4K",
    "description": "IPS 27\" HDR 144Hz",
    "price": 349.99,
    "is_offer": true,
    "owner_id": 1
  }
]
```

**cURL example:**
```bash
curl -X GET "http://localhost:8000/api/items?skip=0&limit=10" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

#### `GET /api/items/{item_id}`
**Retrieve single item by ID**

**Path parameter:** `item_id` (integer)

**Headers required:**
```
Authorization: Bearer <token>
```

**Error responses:**
- 404 Not Found: Item doesn't exist
- 401 Unauthorized: Invalid/missing token

---

#### `POST /api/items`
**Create a new item** (creates with owner_id = current user)

**Headers required:**
```
Authorization: Bearer <token>
Content-Type: application/json
```

**Request body:**
```json
{
  "name": "Wireless Mouse",
  "description": "2.4GHz USB receiver, ergonomic",
  "price": 49.99,
  "is_offer": false
}
```

**Response (201 Created):**
```json
{
  "id": 4,
  "name": "Wireless Mouse",
  "description": "2.4GHz USB receiver, ergonomic",
  "price": 49.99,
  "is_offer": false,
  "owner_id": 1
}
```

**Validation:**
- `name`: required, 2-50 characters
- `description`: optional, up to 200 characters
- `price`: required, must be > 0
- `is_offer`: optional, boolean (default false)

**cURL example:**
```bash
curl -X POST http://localhost:8000/api/items \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Wireless Mouse",
    "description": "2.4GHz USB receiver, ergonomic",
    "price": 49.99,
    "is_offer": false
  }'
```

---

#### `PUT /api/items/{item_id}`
**Update an item** (admin only, partial update)

**Headers required:**
```
Authorization: Bearer <token>  (admin token)
Content-Type: application/json
```

**Request body (all fields optional):**
```json
{
  "price": 59.99,
  "is_offer": true
}
```

**Authorization:** Admin role required. Non-admin returns 403 Forbidden.

---

#### `DELETE /api/items/{item_id}`
**Delete an item** (admin only)

**Response (200 OK):**
```json
{"status": "success", "message": "Artículo 3 eliminado."}
```

**Authorization:** Admin role required. Non-admin returns 403 Forbidden.

**cURL example:**
```bash
curl -X DELETE http://localhost:8000/api/items/3 \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### System Endpoints

#### `GET /api/health`
**Check service health & uptime** (no authentication required)

**Response (200 OK):**
```json
{
  "status": "healthy",
  "uptime_seconds": 1234.56,
  "platform": "Linux-6.6.0-x86_64-with-glibc2.36",
  "python_version": "3.12.3 (main, Apr 15 2024, 18:34:47) [GCC 12.2.0]"
}
```

Also displayed live in the dashboard as "Tiempo Activo", refreshed every 30 seconds.

**cURL example:**
```bash
curl http://localhost:8000/api/health
```

---

## Database Design

### Schema Overview

**Database: `auth_db`**

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR NOT NULL,
    role VARCHAR(20) DEFAULT 'user',  -- 'user' or 'admin'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Default seed data (only inserted if empty):**
```
id=1, username='admin', email='admin@example.com',
role='admin', hashed_password=(bcrypt of 'admin123')
```

---

**Database: `items_db`**

```sql
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    description VARCHAR(200),
    price FLOAT NOT NULL,
    is_offer BOOLEAN DEFAULT FALSE,
    owner_id INTEGER
);
```

**Default seed data (only inserted if empty, 3 sample items with owner_id=1):**
```
1 | Teclado Mecánico | RGB con switches cherry brown | 89.99  | true  | 1
2 | Mouse Gamer       | Inalámbrico de alta precisión | 59.99  | false | 1
3 | Monitor 4K        | IPS 27" HDR 144Hz              | 349.99 | true  | 1
```

---

### Entity Relationship

```
Users (1) ───────→ (Many) Items
  id                       id
  username                 name
  email                    description
  hashed_password          price
  role                     is_offer
  created_at               owner_id (logical reference, no DB-level FK
                                       — different database entirely)
```

`owner_id` links an item to the user who created it, but since `auth_db` and `items_db` are separate Postgres databases, there is no enforced foreign key constraint — it's a logical relationship maintained by the application.

---

## Authentication & Authorization

### JWT Token Flow

```
1. User calls POST /auth/login
   - Sends username + password (form-data)
   - Backend validates against hashed password in users table

2. Backend generates JWT token
   - Payload: { "sub": username, "role": role, "exp": timestamp_in_60_minutes }
   - Secret: hardcoded in auth-service/app.py (SECRET_KEY) — known placeholder, not env-configurable yet
   - Algorithm: HS256 (HMAC SHA256)

3. Backend returns { "access_token": "...", "token_type": "bearer" }

4. Client stores token in localStorage

5. Client makes authenticated request
   - Attaches header: "Authorization: Bearer <token>"

6. Backend endpoint dependency: get_current_user()
   - Decodes JWT using same secret & algorithm
   - Verifies signature & expiry
   - Returns user object to endpoint
   - If token invalid → 401 Unauthorized

7. Endpoint checks user.role (if required)
   - require_admin dependency checks user.role == 'admin'
   - If non-admin → 403 Forbidden
```

### Role-Based Access Control (RBAC)

**Role Matrix** (yes/no = whether the role can call that endpoint):

| Endpoint | Admin | User | Action |
|----------|-------|------|--------|
| POST /auth/register | yes | yes | Register new account (no auth required) |
| POST /auth/login | yes | yes | Get JWT token (no auth required) |
| GET /auth/me | yes | yes | View own profile |
| POST /auth/change-password | yes | yes | Change own password |
| GET /auth/users | yes | no | List all users (admin only) |
| GET /api/items | yes | yes | List items |
| POST /api/items | yes | yes | Create item (owner = current user) |
| PUT /api/items/{id} | yes | no | Update item (admin only) |
| DELETE /api/items/{id} | yes | no | Delete item (admin only) |

**Key points:**
- All authenticated endpoints require a valid JWT in the `Authorization: Bearer` header.
- Non-admin users cannot modify or delete items, even their own.
- The dashboard restricts UI elements based on role (delete button only visible to admins).

### Default Credentials

For development/testing:
- **Username:** `admin`
- **Password:** `admin123`
- **Role:** `admin`

---

## Development Workflow

### Testing Endpoints

#### Via Swagger UI (Easiest)

1. Open browser to `http://localhost:8000/docs`
2. Click "Authorize" button (top right)
3. Paste token from login response
4. Click "Authorize"
5. Click any endpoint to expand it
6. Fill request body (if needed)
7. Click "Try it out" then "Execute"
8. See response immediately

#### Via cURL

**Example: Login and list items**

```bash
# Step 1: Login and capture token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# Step 2: Use token in request
curl -X GET http://localhost:8000/api/items \
  -H "Authorization: Bearer $TOKEN"
```

#### Via Python

```python
import requests

API_URL = "http://localhost:8000"

login_resp = requests.post(f"{API_URL}/auth/login", data={
    "username": "admin",
    "password": "admin123"
})
token = login_resp.json()["access_token"]

headers = {"Authorization": f"Bearer {token}"}
items = requests.get(f"{API_URL}/api/items", headers=headers)
print(items.json())
```

---

## Background Logging

### What Gets Logged

Auth Service sends log entries to Log Service (via `send_log()`, a `BackgroundTasks` call) for:

1. User registration (success and failed attempts on duplicate username/email)
2. User login (success and failed attempts)
3. Password changes (success and failed attempts)
4. Item creation, update, deletion

### Log Format

Log entries are sent as JSON to `POST /logs`:

```json
{
  "service": "auth-service",
  "level": "INFO",
  "message": "Usuario registrado exitosamente: 'john_doe' con rol 'user'.",
  "timestamp": "2026-07-02T10:30:45.123Z"
}
```

### Why Asynchronous?

Auth Service uses FastAPI's `BackgroundTasks` to send logs without blocking the API response — the client gets an instant response even if Log Service is slow or temporarily unreachable.

### Failure Mode

If Log Service is unreachable, logs are silently lost (no retry queue, no persistence) — the API response still succeeds since logging never blocks the request. Adding a message queue (RabbitMQ) for delivery guarantees is Week 6 work, not yet implemented.

---

## Command & Script Reference

Every script and non-obvious command used in this project, and what it actually does.

| Command / script | What it does |
|---|---|
| `docker compose up -d --build` | Builds images (if changed) and starts all 3 containers (`postgres`, `auth-service`, `log-service`) in the background. Safe to re-run — Compose only rebuilds/recreates what changed. |
| `docker compose build auth-service` | Rebuilds only the Auth Service image from `auth-service/Dockerfile`. Required after **any** edit to `auth-service/app.py` — code is `COPY`'d at build time, not mounted live. |
| `docker compose up -d auth-service` | Recreates the `auth-service` container from the (possibly just-rebuilt) image, without touching the other two services. |
| `docker compose logs -f` | Streams logs from all containers, live. Add a service name (`docker compose logs -f auth-service`) to filter to one. |
| `docker compose down` | Stops and removes all containers and the network. Named volumes (`postgres_data`, `log_data`) survive this — data is not lost. |
| `docker compose down -v` | Same as above, but also deletes the volumes — this **wipes the databases and log file**. Use only when you intentionally want a clean slate. |
| `docker volume rm python-docker-service_postgres_data` | Deletes only the Postgres volume (containers must be stopped first). Forces the `postgres-init` scripts to re-run and the seed data to be recreated on next `up`. |
| `docker exec postgres psql -U postgres -l` | Lists all databases inside the running Postgres container — use to confirm `auth_db` and `items_db` exist. |
| `docker exec postgres psql -U postgres -d auth_db -c "SELECT * FROM users;"` | Runs a raw SQL query directly against `auth_db` without going through the API — useful for debugging. |
| `run_local.bat` | Windows batch script. Opens two separate command-prompt windows, each running `uvicorn --reload` for one service, using the `venv` at the repo root. No Postgres involved — services fall back to local SQLite automatically since `POSTGRES_HOST` is never set in this path. |
| `python test_crud.py` | Standalone smoke test (not pytest). Runs a sequential CRUD cycle (list, create, fetch by id, update, delete, list again) against `/api/items` on `http://127.0.0.1:8000`. The server must already be running. It does **not** cover auth/login — only the items CRUD. |
| `postgres-init/01-create-databases.sql` | Not run manually — the official Postgres image executes every `.sql`/`.sh` file in `/docker-entrypoint-initdb.d/` automatically, but **only on the container's first startup** (i.e. only when the `postgres_data` volume is empty). Creates `auth_db` and `items_db`. |

---

## Troubleshooting & FAQ

### "Docker Desktop isn't running"

**Error:**
```
Cannot connect to Docker daemon at unix:///var/run/docker.sock
```

**Solution:**
1. Launch Docker Desktop from Windows Start menu
2. Wait 30 seconds for daemon to start
3. Retry: `docker compose up -d`

---

### "Port 8000 already in use"

**Error:**
```
ERROR: listen tcp :8000: bind: address already in use
```

**Solution Option 1:** Kill the process using port 8000

```bash
# Windows PowerShell
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

**Solution Option 2:** Change the port in `docker-compose.yml`

```yaml
services:
  auth-service:
    ports:
      - "8001:8000"  # Changed 8000 -> 8001
```

---

### "Can't login: invalid credentials"

**Error:**
```json
{"detail": "Usuario o contraseña incorrectos."}
```

**Troubleshooting:**
1. Confirm you're using the default: `admin` / `admin123`
2. Check the user exists: `GET /auth/users` (as admin)
3. For new users, confirm registration succeeded (check Log Service console at `:8010`)

---

### "Token expired"

**Error:**
```json
{"detail": "Token inválido o expirado."}
```

**Solution:**
- Re-login at `/auth/login`
- Copy the new token
- Update "Authorize" in Swagger UI
- Tokens expire after 60 minutes by design

**To change expiry:** edit `ACCESS_TOKEN_EXPIRE_MINUTES` in `auth-service/app.py`, then rebuild.

---

### "Log Service unreachable from Auth Service"

**Error printed in Auth Service logs:**
```
[LOG ERROR] No se pudo conectar al Log Service: ...
```

**Troubleshooting:**
1. Verify Log Service container is running: `docker compose ps`
2. Check the environment variable: `docker compose config | grep LOG_SERVICE_URL`
3. Confirm both containers are on the same Docker network: `docker network ls`
4. Logging is non-blocking, so the API keeps working — check `/logs` on the Log Service to confirm what's arriving.

---

### "Items don't persist between restarts"

**Issue:** After `docker compose down`, items are gone on the next `docker compose up`.

**Troubleshooting:**
1. Confirm the volume exists: `docker volume ls | grep postgres_data`
2. Confirm you did not run `docker compose down -v` (the `-v` flag deletes volumes)
3. Inspect the data directly: `docker exec postgres psql -U postgres -d items_db -c "SELECT * FROM items;"`

---

### "FATAL: database auth_db does not exist" when starting Postgres

**Cause:** the `postgres_data` volume already existed from an earlier run that didn't have `postgres-init/` mounted, so the init script never ran.

**Solution:**
```bash
docker compose down
docker volume rm python-docker-service_postgres_data
docker compose up -d
```

---

### "Swagger UI shows an error or won't load"

**Solution:**
1. Check Auth Service is running: `curl http://localhost:8000/api/health`
2. Check the OpenAPI schema is valid JSON: `curl http://localhost:8000/openapi.json`
3. Restart: `docker compose restart auth-service`

---

### "How do I reset the databases to a clean seed state?"

**Docker (Postgres):**
```bash
docker compose down
docker volume rm python-docker-service_postgres_data
docker compose up -d
```

**Local (SQLite fallback):**
```bash
rm -f data/auth.db data/items.db
# Restart auth-service; the databases are recreated with seed data on startup
```

---

## Next Steps

- **Week 6:** Add RabbitMQ message queue for resilient async logging
- **Week 4 (remainder):** Add MongoDB for Log Service persistence
- **Week 7:** Build React frontend to replace the embedded HTML dashboard
- **Week 8:** Add Analysis Service (detection rules) and Alert Service
