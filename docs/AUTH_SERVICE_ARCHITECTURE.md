# Auth Service — Arquitectura Completa

Este documento explica **línea por línea** qué hace el Auth Service, cómo funciona, y todas sus componentes.

---

## Tabla de Contenidos

1. [Estructura General](#estructura-general)
2. [Configuración Inicial](#configuración-inicial)
3. [Base de Datos](#base-de-datos)
4. [Modelos ORM](#modelos-orm)
5. [Esquemas Pydantic](#esquemas-pydantic)
6. [Funciones de Utilidad](#funciones-de-utilidad)
7. [Endpoints de Autenticación](#endpoints-de-autenticación)
8. [Endpoints de Items (CRUD)](#endpoints-de-items-crud)
9. [Endpoint de Sistema](#endpoint-de-sistema)
10. [Dashboard HTML](#dashboard-html)

---

## Estructura General

```
auth-service/
├── app.py                    # Archivo principal (1000+ líneas)
│   ├── Imports              # Librerías requeridas
│   ├── Configuration        # Variables globales
│   ├── send_log()           # Función auxiliar para logging
│   ├── Database Setup       # SQLAlchemy configuration
│   ├── ORM Models           # UserORM, ItemORM
│   ├── Pydantic Schemas     # UserCreate, ItemResponse, etc.
│   ├── FastAPI App          # Inicialización de la app
│   ├── Authentication       # JWT, hashing, dependencies
│   ├── Seed Data            # Datos iniciales
│   ├── Swagger UI Custom    # Tema profesional
│   ├── Endpoints            # /auth/*, /api/items/*, /api/health
│   └── Dashboard HTML       # Interfaz web renderizada
└── requirements.txt         # Dependencias
└── Dockerfile              # Imagen Docker
```

---

## Configuración Inicial

### Imports Principales

```python
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine
from passlib.context import CryptContext
from jose import jwt, JWTError
```

**¿Qué hace cada uno?**
- **FastAPI**: Framework web para crear APIs REST
- **HTTPException**: Excepciones HTTP personalizadas (401, 403, 404, etc.)
- **Depends**: Sistema de inyección de dependencias de FastAPI
- **BackgroundTasks**: Ejecuta tareas en background sin bloquear la respuesta
- **SQLAlchemy**: ORM para interactuar con SQL
- **CryptContext**: Encripción segura de contraseñas (bcrypt)
- **jwt**: Codificación/decodificación de tokens JWT

### Variables de Configuración

> Tabla generada automáticamente desde `auth-service/app.py` — no editar a mano, correr `python scripts/gen_docs.py` tras cambiar el código.

<!-- AUTO-GENERATED:START:auth-config -->
| Variable | Origen | Env var | Default |
|---|---|---|---|
| `SECRET_KEY` | variable de entorno | `JWT_SECRET_KEY` | `changeme-super-secret-key-for-jwt-in-production` |
| `ALGORITHM` | **hardcoded en el código** | - | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | **hardcoded en el código** | - | `60` |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | **hardcoded en el código** | - | `60` |
| `LOGIN_RATE_LIMIT_BLOCK_SECONDS` | **hardcoded en el código** | - | `60` |
| `REGISTER_RATE_LIMIT_WINDOW_SECONDS` | **hardcoded en el código** | - | `300` |
| `LOG_SERVICE_URL` | variable de entorno | `LOG_SERVICE_URL` | `http://localhost:8010` |
| `POSTGRES_HOST` | variable de entorno | `POSTGRES_HOST` | `None` |
| `POSTGRES_PORT` | variable de entorno | `POSTGRES_PORT` | `5432` |
| `POSTGRES_USER` | variable de entorno | `POSTGRES_USER` | `postgres` |
| `POSTGRES_PASSWORD` | variable de entorno | `POSTGRES_PASSWORD` | `postgres` |
<!-- AUTO-GENERATED:END:auth-config -->

**Explicación (mantenimiento manual — no se genera del código):**
- `SECRET_KEY`: Clave privada para firmar tokens JWT. Viene de la variable de entorno `JWT_SECRET_KEY` (Semana 10: se generó un secreto real de 256 bits en `.env`; solo `.env.example` conserva el placeholder de ejemplo). La misma clave la usan Log, Analysis y Alert Service para *verificar* los tokens que este servicio firma.
- `ALGORITHM`: Algoritmo de firma (HS256 = HMAC con SHA-256)
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token válido por 60 minutos
- `LOG_SERVICE_URL`: URL del Log Service para enviar logs (por defecto localhost:8010)

### Función send_log()

```python
def send_log(level: str, message: str):
    """Envía un registro al Log Service. Se ejecuta de fondo."""
    if not LOG_SERVICE_URL:
        return
    try:
        payload = {
            "service": "auth-service",
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().isoformat()
        }
        res = requests.post(f"{LOG_SERVICE_URL}/logs", json=payload, timeout=2.0)
        if res.status_code != 201:
            print(f"[LOG ERROR] El servicio de logs respondió con código {res.status_code}")
    except Exception as e:
        print(f"[LOG ERROR] No se pudo conectar al Log Service: {e}")
```

**¿Qué hace?**
1. Toma un nivel de log (INFO, WARNING, ERROR, DEBUG) y un mensaje
2. Crea un payload JSON con servicio, nivel, mensaje y timestamp
3. Envía un POST a `http://localhost:8010/logs`
4. Si falla, imprime un error en consola (no rompe la ejecución)

**¿Cuándo se usa?**
- Cuando un usuario se registra: `send_log("INFO", f"Usuario '{username}' registrado")`
- Cuando hay error: `send_log("WARNING", "Intento de login fallido")`
- Cuando se crea/actualiza/elimina un item

---

## Base de Datos

> **Actualizado (Semana 4):** el motor de base de datos pasó de SQLite a **PostgreSQL**. El código real vive en `auth-service/app.py` — el snippet de abajo es una versión simplificada con fines didácticos; para el detalle exacto (reintentos de conexión, fallback) consulta el archivo fuente directamente.

### Inicialización

```python
POSTGRES_HOST = os.getenv("POSTGRES_HOST")  # "postgres" dentro de Docker Compose

if POSTGRES_HOST:
    # Producción / Docker: dos bases de datos Postgres separadas,
    # creadas de antemano por postgres-init/01-create-databases.sql
    auth_engine  = create_engine("postgresql+psycopg2://postgres:postgres@postgres:5432/auth_db")
    items_engine = create_engine("postgresql+psycopg2://postgres:postgres@postgres:5432/items_db")
else:
    # Fallback: SQLite local, para desarrollo sin Docker (run_local.bat)
    os.makedirs("data", exist_ok=True)
    auth_engine  = create_engine("sqlite:///data/auth.db", connect_args={"check_same_thread": False})
    items_engine = create_engine("sqlite:///data/items.db", connect_args={"check_same_thread": False})

AuthSession  = sessionmaker(bind=auth_engine)
ItemsSession = sessionmaker(bind=items_engine)
```

**¿Qué hace?**
- Si hay `POSTGRES_HOST` (definido en `docker-compose.yml`), conecta a dos bases de datos **PostgreSQL separadas** en el mismo servidor:
  - `auth_db`: Usuarios, credenciales, roles
  - `items_db`: Productos/inventario
- Si no hay `POSTGRES_HOST`, crea carpeta `data/` y usa SQLite local con los mismos dos archivos que antes (`data/auth.db`, `data/items.db`) — mismo diseño, distinto motor.
- Antes de crear las tablas, `_wait_for_postgres()` reintenta la conexión hasta 15 veces (con pausas de 2s) — Postgres puede tardar unos segundos en aceptar conexiones tras arrancar, incluso pasando su healthcheck de Docker.
- `sessionmaker`: Factory para crear sesiones de base de datos.

### Creación de Tablas

```python
Base.metadata.create_all(bind=auth_engine)
Base.metadata.create_all(bind=items_engine)
```

**¿Qué hace?**
- Ejecuta `CREATE TABLE IF NOT EXISTS` para UserORM en auth.db
- Ejecuta `CREATE TABLE IF NOT EXISTS` para ItemORM en items.db
- Si las tablas ya existen, no hace nada

---

## Modelos ORM

> Tablas generadas automáticamente desde `auth-service/app.py` — no editar a mano, correr `python scripts/gen_docs.py` tras cambiar el código.

<!-- AUTO-GENERATED:START:auth-orm -->
**`ItemORM`** (tabla `items`)

| Columna | Tipo | Restricciones |
|---|---|---|
| id | `Integer` | primary_key=True, index=True |
| name | `String(50)` | nullable=False, index=True |
| description | `String(200)` | nullable=True |
| price | `Float` | nullable=False |
| is_offer | `Boolean` | default=False |
| owner_id | `Integer` | nullable=True |

**`UserORM`** (tabla `users`)

| Columna | Tipo | Restricciones |
|---|---|---|
| id | `Integer` | primary_key=True, index=True |
| username | `String(50)` | unique=True, index=True, nullable=False |
| email | `String(100)` | unique=True, index=True, nullable=False |
| hashed_password | `String` | nullable=False |
| role | `String(20)` | default=analista |
| created_at | `DateTime` | default=datetime.utcnow |
| password_changed_at | `DateTime` | nullable=True |
<!-- AUTO-GENERATED:END:auth-orm -->

**Ejemplo de registro (UserORM):**
```
id=1, username="admin", email="admin@localhost", hashed_password="$2b$12$...", role="admin", created_at="2026-07-02T10:30:00"
```

**Ejemplo de registro (ItemORM):**
```
id=1, name="Laptop Gaming", description="RTX 3090", price=2500.00, is_offer=True, owner_id=1
```

---

## Esquemas Pydantic

Los esquemas Pydantic **validan** los datos que llegan en las requests y los que se envían en las responses.

> Tablas generadas automáticamente desde `auth-service/app.py` — no editar a mano, correr `python scripts/gen_docs.py` tras cambiar el código. Incluye todos los modelos definidos en el archivo (también `PasswordChange` y `HealthResponse`, antes ausentes de este documento).

<!-- AUTO-GENERATED:START:auth-pydantic -->
**`Token`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| access_token | `str` | - | - |
| token_type | `str` | - | - |

**`UserCreate`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| username | `str` | min_length=3, max_length=50 | - |
| email | `str` | - | - |
| password | `str` | min_length=8 | - |

**`UserResponse`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| id | `int` | - | - |
| username | `str` | - | - |
| email | `str` | - | - |
| role | `str` | - | - |
| created_at | `datetime` | - | - |

**`UserRoleUpdate`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| role | `str` | - | - |

**`PasswordChange`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| current_password | `str` | - | - |
| new_password | `str` | min_length=8 | - |

**`ItemCreate`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| name | `str` | min_length=2, max_length=50 | - |
| description | `Optional[str]` | max_length=200 | - |
| price | `float` | gt=0 | - |
| is_offer | `bool` | - | False |

**`ItemUpdate`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| name | `Optional[str]` | min_length=2, max_length=50 | - |
| description | `Optional[str]` | max_length=200 | - |
| price | `Optional[float]` | gt=0 | - |
| is_offer | `Optional[bool]` | - | - |

**`ItemResponse`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| id | `int` | - | - |
| name | `str` | - | - |
| description | `Optional[str]` | - | - |
| price | `float` | - | - |
| is_offer | `bool` | - | - |
| owner_id | `Optional[int]` | - | - |

**`HealthResponse`**

| Campo | Tipo | Restricciones | Default |
|---|---|---|---|
| status | `str` | - | - |
| uptime_seconds | `float` | - | - |
| platform | `str` | - | - |
| python_version | `str` | - | - |
<!-- AUTO-GENERATED:END:auth-pydantic -->

**Ejemplos de uso (mantenimiento manual):**

```json
POST /auth/register  →  UserCreate
{ "username": "john_doe", "email": "john@example.com", "password": "password123" }

Response  →  UserResponse
{ "id": 2, "username": "john_doe", "email": "john@example.com", "role": "analista", "created_at": "2026-07-02T11:00:00" }

POST /api/items  →  ItemCreate
{ "name": "Auriculares", "description": "Inalámbricos con cancelación de ruido", "price": 120.00, "is_offer": true }

Response  →  ItemResponse
{ "id": 1, "name": "Auriculares", "description": "Inalámbricos con cancelación de ruido", "price": 120.00, "is_offer": true, "owner_id": 2 }

POST /auth/login  →  Token
{ "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "token_type": "bearer" }
```

---

## Funciones de Utilidad

### hash_password() - Encriptar contraseña

```python
def hash_password(password: str) -> str:
    return pwd_context.hash(password)
```

**¿Qué hace?**
- Toma una contraseña en texto plano
- La encripta usando bcrypt
- Retorna un hash que se guarda en la BD

**Ejemplo:**
```
Input:  "password123"
Output: "$2b$12$N9qo8uLO.....R.O/8e" (60 caracteres)
```

### verify_password() - Verificar contraseña

```python
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
```

**¿Qué hace?**
- Toma la contraseña en texto plano y el hash guardado
- Verifica que coincidan (sin desencriptar)
- Retorna True/False

**Ejemplo:**
```python
# En /auth/login
if verify_password("password123", usuario.hashed_password):
    # Login exitoso
else:
    # Contraseña incorrecta
```

### create_access_token() - Generar JWT

```python
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
```

**¿Qué hace?**
1. Copia los datos (username, role, user_id)
2. Calcula tiempo de expiración (60 minutos por defecto)
3. Agrega claim "exp" (expiration time)
4. Codifica todo con la SECRET_KEY usando HS256
5. Retorna el token como string

**Ejemplo:**
```python
# En /auth/login
token = create_access_token(data={
    "sub": usuario.username,
    "user_id": usuario.id,
    "role": usuario.role
})
# Retorna: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInVzZXJfaWQiOjEsInJvbGUiOiJhZG1pbiIsImV4cCI6MTY4NDQyMzIwMH0._5s..."
```

### get_current_user() - Dependency para proteger endpoints

```python
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_auth_db)) -> UserORM:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = db.query(UserORM).filter(UserORM.username == username).first()
    if user is None:
        raise credentials_exception
    return user
```

**¿Qué hace?**
1. Extrae el token del header `Authorization: Bearer <token>`
2. Lo decodifica con la SECRET_KEY
3. Obtiene el "sub" (subject = username)
4. Busca el usuario en la BD
5. Si todo es válido, retorna el usuario
6. Si falla cualquier paso, retorna 401 Unauthorized

**¿Cuándo se usa?**
```python
@app.get("/auth/me")
def get_me(_: UserORM = Depends(get_current_user)):
    # Solo usuarios autenticados pueden llegar acá
    return _
```

### require_admin() - Dependency para endpoints solo admin

```python
async def require_admin(user: UserORM = Depends(get_current_user)) -> UserORM:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden acceder a este recurso"
        )
    return user
```

**¿Qué hace?**
1. Valida que el usuario esté autenticado (usa `get_current_user`)
2. Verifica que tenga rol "admin"
3. Si no es admin, retorna 403 Forbidden

**¿Cuándo se usa?**
```python
@app.put("/api/items/{item_id}")
def update_item(item_id: int, _: UserORM = Depends(require_admin)):
    # Solo admins pueden actualizar items
```

---

## Referencia Rápida de Endpoints

> Tabla generada automáticamente desde `auth-service/app.py` — cubre **todos** los endpoints reales del código (incluye `/auth/change-password` y `GET /api/items/{item_id}`, antes ausentes de este documento). No editar a mano, correr `python scripts/gen_docs.py` tras cambiar el código. El detalle narrativo de cada endpoint principal sigue abajo.

<!-- AUTO-GENERATED:START:auth-endpoints -->
| Método | Ruta | Tags | Función | Resumen |
|---|---|---|---|---|
| `POST` | `/auth/register` | Auth | `register()` | Registrar nuevo usuario |
| `POST` | `/auth/login` | Auth | `login()` | Iniciar sesión — obtener token JWT |
| `GET` | `/auth/me` | Auth | `get_me()` | Perfil del usuario autenticado |
| `POST` | `/auth/change-password` | Auth | `change_password()` | Cambiar contraseña del usuario autenticado |
| `GET` | `/auth/users` | Auth | `list_users()` | Listar todos los usuarios (solo Admin) |
| `PATCH` | `/auth/users/{user_id}/role` | Auth | `update_user_role()` | Cambiar el rol de un usuario (solo Admin) |
| `GET` | `/api/items` | Items | `get_items()` | Listar todos los artículos |
| `GET` | `/api/items/{item_id}` | Items | `get_item()` | Obtener artículo por ID |
| `POST` | `/api/items` | Items | `create_item()` | Crear nuevo artículo |
| `PUT` | `/api/items/{item_id}` | Items | `update_item()` | Actualizar artículo (solo Admin) |
| `DELETE` | `/api/items/{item_id}` | Items | `delete_item()` | Eliminar artículo (solo Admin) |
| `GET` | `/api/health` | System | `health_check()` | Estado del servicio |
<!-- AUTO-GENERATED:END:auth-endpoints -->

## Endpoints de Autenticación

### POST /auth/register - Registrar nuevo usuario

**Request:**
```json
{
    "username": "john_doe",
    "email": "john@example.com",
    "password": "password123"
}
```

**Response (201 Created):**
```json
{
    "id": 2,
    "username": "john_doe",
    "email": "john@example.com",
    "role": "analista",
    "created_at": "2026-07-02T11:00:00"
}
```

**¿Qué hace en el código?**
```python
@app.post("/auth/register", response_model=UserResponse, status_code=201, tags=["Auth"])
def register(user_data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_auth_db)):
    # 1. Verifica que usuario/email no existan
    if db.query(UserORM).filter(
        (UserORM.username == user_data.username) | (UserORM.email == user_data.email)
    ).first():
        background_tasks.add_task(send_log, "WARNING", f"Intento de registro fallido: '{user_data.username}' ya existe")
        raise HTTPException(status_code=400, detail="El usuario o email ya existe")
    
    # 2. Crea nuevo usuario con contraseña hasheada
    user = UserORM(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role="analista"  # Por defecto rol "analista"
    )
    
    # 3. Guarda en BD
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # 4. Envía log en background (no espera)
    background_tasks.add_task(send_log, "INFO", f"Usuario '{user_data.username}' registrado exitosamente")
    
    # 5. Retorna usuario creado
    return user
```

---

### POST /auth/login - Obtener token JWT

**Request (form data):**
```
username=admin&password=admin123
```

**Response (200 OK):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer"
}
```

**Cómo usar el token:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**¿Qué hace en el código?**
```python
@app.post("/auth/login", response_model=Token, tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), 
          background_tasks: BackgroundTasks, db: Session = Depends(get_auth_db)):
    
    # 1. Busca usuario por username
    user = db.query(UserORM).filter(UserORM.username == form_data.username).first()
    
    # 2. Si no existe o contraseña es incorrecta, falla
    if not user or not verify_password(form_data.password, user.hashed_password):
        background_tasks.add_task(send_log, "WARNING", f"Intento de login fallido: '{form_data.username}'")
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    
    # 3. Genera token JWT con datos del usuario
    access_token = create_access_token(data={
        "sub": user.username,
        "user_id": user.id,
        "role": user.role
    })
    
    # 4. Envía log en background
    background_tasks.add_task(send_log, "INFO", f"Usuario '{user.username}' inició sesión")
    
    # 5. Retorna token
    return {"access_token": access_token, "token_type": "bearer"}
```

---

### GET /auth/me - Obtener perfil del usuario autenticado

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response (200 OK):**
```json
{
    "id": 1,
    "username": "admin",
    "email": "admin@localhost",
    "role": "admin",
    "created_at": "2026-07-02T10:30:00"
}
```

**¿Qué hace en el código?**
```python
@app.get("/auth/me", response_model=UserResponse, tags=["Auth"])
def get_me(_: UserORM = Depends(get_current_user)):
    # get_current_user valida el token y retorna el usuario
    # Este endpoint simplemente lo devuelve
    return _
```

---

### GET /auth/users - Listar todos los usuarios (solo admin)

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response (200 OK):**
```json
[
    {
        "id": 1,
        "username": "admin",
        "email": "admin@localhost",
        "role": "admin",
        "created_at": "2026-07-02T10:30:00"
    },
    {
        "id": 2,
        "username": "john_doe",
        "email": "john@example.com",
        "role": "analista",
        "created_at": "2026-07-02T11:00:00"
    }
]
```

**¿Qué hace en el código?**
```python
@app.get("/auth/users", response_model=List[UserResponse], tags=["Auth"])
def list_users(_: UserORM = Depends(require_admin), db: Session = Depends(get_auth_db)):
    # require_admin verifica que sea admin y esté autenticado
    # Luego retorna todos los usuarios
    return db.query(UserORM).all()
```

---

## Endpoints de Items (CRUD)

### GET /api/items - Listar todos los items

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Query parameters:**
```
?skip=0&limit=100
```

**Response (200 OK):**
```json
[
    {
        "id": 1,
        "name": "Laptop Gaming",
        "description": "RTX 3090",
        "price": 2500.00,
        "is_offer": true,
        "owner_id": 1
    },
    {
        "id": 2,
        "name": "Mouse Gamer",
        "description": "Inalámbrico",
        "price": 59.99,
        "is_offer": false,
        "owner_id": 1
    }
]
```

**¿Qué hace en el código?**
```python
@app.get("/api/items", response_model=List[ItemResponse], tags=["Items"])
def get_items(skip: int = 0, limit: int = 100,
              db: Session = Depends(get_items_db),
              _: UserORM = Depends(get_current_user)):
    # Valida autenticación
    # Retorna items paginados (skip + limit)
    return db.query(ItemORM).offset(skip).limit(limit).all()
```

---

### POST /api/items - Crear nuevo item

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Request:**
```json
{
    "name": "Teclado Mecánico",
    "description": "RGB con switches cherry brown",
    "price": 89.99,
    "is_offer": true
}
```

**Response (201 Created):**
```json
{
    "id": 3,
    "name": "Teclado Mecánico",
    "description": "RGB con switches cherry brown",
    "price": 89.99,
    "is_offer": true,
    "owner_id": 1
}
```

**¿Qué hace en el código?**
```python
@app.post("/api/items", response_model=ItemResponse, status_code=201, tags=["Items"])
def create_item(item_data: ItemCreate, 
                background_tasks: BackgroundTasks,
                db: Session = Depends(get_items_db),
                current_user: UserORM = Depends(get_current_user)):
    
    # 1. Crea nuevo item asignando el usuario actual como owner
    item = ItemORM(
        name=item_data.name,
        description=item_data.description,
        price=item_data.price,
        is_offer=item_data.is_offer,
        owner_id=current_user.id  # ← Importante
    )
    
    # 2. Guarda en BD
    db.add(item)
    db.commit()
    db.refresh(item)
    
    # 3. Envía log
    background_tasks.add_task(send_log, "INFO", 
        f"Usuario '{current_user.username}' creó item: '{item.name}' (${item.price})")
    
    # 4. Retorna item creado
    return item
```

---

### PUT /api/items/{item_id} - Actualizar item (solo admin)

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Request:**
```json
{
    "name": "Teclado Mecánico v2",
    "price": 99.99,
    "is_offer": false
}
```

**Response (200 OK):**
```json
{
    "id": 3,
    "name": "Teclado Mecánico v2",
    "description": "RGB con switches cherry brown",
    "price": 99.99,
    "is_offer": false,
    "owner_id": 1
}
```

**¿Qué hace en el código?**
```python
@app.put("/api/items/{item_id}", response_model=ItemResponse, tags=["Items"])
def update_item(item_id: int, item_data: ItemUpdate,
                background_tasks: BackgroundTasks,
                db: Session = Depends(get_items_db),
                _: UserORM = Depends(require_admin)):
    
    # 1. Busca item por ID
    item = db.query(ItemORM).filter(ItemORM.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    
    # 2. Actualiza campos que vinieron en el request
    if item_data.name:
        item.name = item_data.name
    if item_data.description is not None:
        item.description = item_data.description
    if item_data.price:
        item.price = item_data.price
    if item_data.is_offer is not None:
        item.is_offer = item_data.is_offer
    
    # 3. Guarda cambios
    db.commit()
    db.refresh(item)
    
    # 4. Envía log
    background_tasks.add_task(send_log, "INFO", f"Admin actualizó item: '{item.name}'")
    
    # 5. Retorna item actualizado
    return item
```

---

### DELETE /api/items/{item_id} - Eliminar item (solo admin)

**Headers requeridos:**
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Response (200 OK):**
```json
{}
```

**¿Qué hace en el código?**
```python
@app.delete("/api/items/{item_id}", tags=["Items"])
def delete_item(item_id: int,
                background_tasks: BackgroundTasks,
                db: Session = Depends(get_items_db),
                _: UserORM = Depends(require_admin)):
    
    # 1. Busca item
    item = db.query(ItemORM).filter(ItemORM.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item no encontrado")
    
    # 2. Obtiene nombre antes de eliminar (para el log)
    item_name = item.name
    
    # 3. Elimina
    db.delete(item)
    db.commit()
    
    # 4. Envía log
    background_tasks.add_task(send_log, "INFO", f"Admin eliminó item: '{item_name}'")
    
    # 5. Retorna vacío (204 No Content)
    return {}
```

---

## Endpoint de Sistema

### GET /api/health - Estado del servicio

**Response (200 OK):**
```json
{
    "status": "healthy",
    "uptime_seconds": 3456.78,
    "platform": "Linux-6.6.0-x86_64-with-glibc2.36",
    "python_version": "3.12.3 (main, Apr 15 2024, 18:34:47) [GCC 12.2.0]"
}
```

**¿Qué hace en el código?**
```python
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
def health_check():
    return HealthResponse(
        status="healthy",
        uptime_seconds=round(time.time() - START_TIME, 2),
        platform=platform.platform(),
        python_version=sys.version
    )
```

**¿Cuándo se usa?**
- Diagnóstico manual: confirmar que el servicio responde
- Debugging: ver uptime y versión de Python/plataforma
- Se muestra en vivo en el dashboard como "Tiempo Activo": se sincroniza una vez con este endpoint al iniciar sesión y luego corre como un contador local (1 tick/segundo) en el navegador, sin volver a llamar al servidor
- No requiere autenticación — útil para healthchecks de Docker/orquestadores

---

## Dashboard HTML

El dashboard es una página HTML embebida en el endpoint GET `/`:

### Qué se muestra

```
┌─────────────────────────────────────────┐
│  Python CRUD API Service                │  ← Título con icono Lucide
├─────────────────────────────────────────┤
│  Tiempo Activo | Usuario | Rol | Items  │  ← Estadísticas en vivo
├─────────────────────────────────────────┤
│  Bases de Datos Conectadas              │
│  [OK] auth_db (Usuarios . Auth)         │
│  [OK] items_db (Inventario . CRUD)      │
├─────────────────────────────────────────┤
│  Inventario de Productos                │
│  ┌─────────────────────────────────────┐ │
│  │ Teclado Mecánico    │ $89.99   (x)  │ │  (x) = eliminar, solo admin
│  │ Mouse Gamer         │ $59.99   (x)  │ │
│  │ Monitor 4K          │ $349.99  (x)  │ │
│  └─────────────────────────────────────┘ │
├─────────────────────────────────────────┤
│  Nuevo Producto                          │
│  Nombre: [________________]              │
│  Descripción: [_______________________]  │
│  Precio: [$___________]                  │
│  [ ] Es una oferta especial              │
│  [Guardar Producto]                      │
├─────────────────────────────────────────┤
│  Cambiar Contraseña                      │
│  Contraseña actual: [________]           │
│  Nueva contraseña: [________]            │
│  [Actualizar Contraseña]                 │
├─────────────────────────────────────────┤
│  Accesos                                 │
│  [Swagger UI]  [Log Console]             │
├─────────────────────────────────────────┤
│  Documentación del Proyecto              │
│  [Resumen] [README] [Contexto] [Visual] │
│  [Arquitectura Auth Service]             │
└─────────────────────────────────────────┘
```

### Funcionalidades

1. Tabla de items con precio y estado de oferta
2. Formulario para crear items, con validación en cliente
3. Botón para eliminar items (solo admins)
4. Login y registro con toggle de mostrar/ocultar contraseña, validación en tiempo real y confirmación de contraseña
5. Formulario para cambiar la contraseña del usuario autenticado
6. Estadística de tiempo activo del servicio, refrescada cada 30 segundos
7. Panel de documentación: enlaces a los `.md` del repo, renderizados en `/documentation/{id}` sin salir del navegador
8. Enlaces a Swagger UI y a la consola del Log Service

### Tecnologías usadas

- **HTML5**: estructura semántica, generada como un único string Python (sin motor de templates)
- **CSS3**: variables, grid, flexbox — sin frameworks externos
- **JavaScript vanilla**: sin dependencias externas
  - Fetch API para peticiones HTTP
  - Manejo dinámico del DOM
- **Lucide Icons**: SVGs inline embebidos directamente en el HTML — sin CDN, sin JS de terceros
- **JWT**: almacenado en `localStorage`

---

## Flujo Completo: De registro a crear item

```
1. Usuario accede a http://localhost:8000
   ↓
2. Se muestra dashboard (no autenticado)
   - Formulario de login aparece
   ↓
3. Usuario ingresa admin / admin123
   ↓
4. Cliente hace POST /auth/login
   - Backend: verifica contraseña
   - Backend: genera JWT
   - Backend: envía log al Log Service (background)
   ↓
5. Cliente recibe token
   - localStorage: guarda token
   - Dashboard: se actualiza con items
   ↓
6. Usuario llena formulario de nuevo item
   ↓
7. Cliente hace POST /api/items con token en header
   - Backend: valida token (get_current_user)
   - Backend: crea item en BD
   - Backend: asigna owner_id del usuario
   - Backend: envía log al Log Service
   ↓
8. Cliente recibe item creado
   - Dashboard: agrega fila nueva a tabla
   - Tabla actualiza en tiempo real
```

---

## Resumen de Seguridad

| Aspecto | Implementación |
|---------|-----------------|
| **Contraseñas** | Hasheadas con bcrypt (no texto plano) |
| **Tokens** | JWT (HS256) firmados con `JWT_SECRET_KEY` — env var, no hardcodeada |
| **Expiración** | 60 minutos (configurable) |
| **Roles** | RBAC: "analista" vs "admin" |
| **Endpoints protegidos** | La mayoría requiere `Depends(get_current_user)`; `/auth/register`, `/auth/login`, `/api/health` quedan públicos a propósito |
| **Rate limiting** | Login: 5 fallos/60s bloquean 60s por usuario. Registro (Semana 10): 10 registros/5min bloquean por IP |
| **CORS** | Restringido a `CORS_ORIGINS` (por defecto `https://localhost`, un solo origen — no "todos los orígenes") |
| **HTTPS** | Este servicio en sí habla HTTP plano dentro de la red interna de Docker; el navegador entra por HTTPS a través de nginx (dashboard-service, puerto 443, Semana 10) — TLS termina ahí, no acá |
| **Base de datos** | PostgreSQL (Docker) con fallback a SQLite local sin Docker |

---

## Errores Comunes y Cómo Resolverlos

### 401 Unauthorized en GET /auth/me
**Problema:** Token expirado o inválido
**Solución:** Re-login en `/auth/login`

### 403 Forbidden en PUT /api/items/{id}
**Problema:** Tu usuario no es admin
**Solución:** Usa cuenta admin o pide a admin que actualice

### 400 Bad Request en POST /auth/register
**Problema:** Usuario o email ya existe
**Solución:** Elige otro username/email

### 404 Not Found en GET /api/items/{id}
**Problema:** Item no existe o fue eliminado
**Solución:** Verifica el ID en la lista

---

## Links Útiles

- **Swagger UI:** http://localhost:8000/docs
- **Dashboard:** http://localhost:8000
- **Health Check:** http://localhost:8000/api/health
- **Log Service:** http://localhost:8010
- **OpenAPI Schema:** http://localhost:8000/openapi.json

---

## Comandos y Scripts

Referencia rápida de comandos usados con este servicio específico. Para la lista completa de comandos del proyecto (incluyendo Postgres y troubleshooting), ver [`WEEKS_1-2_IMPLEMENTATION.md`](WEEKS_1-2_IMPLEMENTATION.md#command--script-reference).

| Comando | Qué hace |
|---|---|
| `docker compose build auth-service` | Reconstruye la imagen de Auth Service — obligatorio después de editar `auth-service/app.py`, ya que el código se copia en tiempo de build, no se monta en vivo. |
| `docker compose up -d auth-service` | Recrea el contenedor de Auth Service con la imagen ya reconstruida. |
| `docker compose logs -f auth-service` | Sigue en vivo la salida de este servicio (útil para ver los `print()` de `send_log()` cuando falla el Log Service). |
| `docker exec auth-service ls /app` | Inspecciona los archivos dentro del contenedor en ejecución — útil para confirmar que los volúmenes de documentación (`docs/`, `README.md`, etc.) están montados. |
| `curl http://localhost:8000/api/health` | Prueba manual del endpoint de salud, sin necesidad de token. |
| `python test_crud.py` | Smoke test del CRUD de items (no cubre auth) — requiere que el servicio ya esté corriendo. |

## Referencia de Log Service

> Endpoints generados automáticamente desde `log-service/app.py`.

<!-- AUTO-GENERATED:START:log-endpoints -->
| Método | Ruta | Tags | Función | Resumen |
|---|---|---|---|---|
| `GET` | `/api/health` | System | `health_check()` | Estado del servicio |
| `POST` | `/logs` | Logs | `create_log()` | Registra un evento de log enviado por cualquier microservicio en MongoDB. |
| `GET` | `/logs` | Logs | `get_logs()` | Retorna logs de MongoDB con opciones de filtrado. **Requiere estar autenticado.** |
<!-- AUTO-GENERATED:END:log-endpoints -->

## Roadmap — ya completado

Este documento describía originalmente el estado de Semana 4. Todo lo que en su momento era "próximo paso" ya se hizo: RabbitMQ para mensajería asíncrona (Semana 6), dashboard React (Semana 7), Analysis Service y Alert Service (Semana 8), Redis como caché (Semana 9), y los refinamientos de seguridad — roles `analista`/`admin`, JWT en los 4 backends, HTTPS, rate limiting general, backups — de la Semana 10. Ver **[`docs/PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md)** para el resumen completo y actualizado del roadmap.

