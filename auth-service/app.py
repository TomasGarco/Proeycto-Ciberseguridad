import os
import time
import platform
import sys
from datetime import datetime, timedelta
from typing import List, Optional

import requests
from fastapi import FastAPI, HTTPException, status, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.openapi.utils import get_openapi
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from pydantic import BaseModel, Field, field_validator
from passlib.context import CryptContext
from jose import JWTError, jwt
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ============================================================
# CONFIGURATION
# ============================================================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "changeme-super-secret-key-for-jwt-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
LOG_SERVICE_URL = os.getenv("LOG_SERVICE_URL", "http://localhost:8010")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]


def send_log(level: str, message: str):
    """
    Envía un registro al Log Service. Se ejecuta de fondo.
    """
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

# ============================================================
# DATABASE CONNECTIONS — PostgreSQL (Semana 4)
# ============================================================
# Ambas bases viven en el mismo servidor Postgres pero son bases de datos
# separadas (auth_db / items_db), preservando el aislamiento que ya tenía
# el diseño original con dos archivos SQLite independientes.
#
# Fallback a SQLite local si no hay POSTGRES_HOST — permite seguir usando
# run_local.bat sin depender de un servidor Postgres corriendo aparte.
POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

def _wait_for_postgres(engine, label: str, retries: int = 15, delay_seconds: float = 2.0):
    """Espera a que Postgres acepte conexiones (arranca más lento que el propio servicio)."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == retries:
                raise
            print(f"[DB] Esperando a que '{label}' esté disponible... (intento {attempt}/{retries})")
            time.sleep(delay_seconds)


if POSTGRES_HOST:
    ITEMS_DB_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/items_db"
    AUTH_DB_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/auth_db"
    items_engine = create_engine(ITEMS_DB_URL)
    auth_engine = create_engine(AUTH_DB_URL)
    _wait_for_postgres(items_engine, "items_db")
    _wait_for_postgres(auth_engine, "auth_db")
else:
    os.makedirs("data", exist_ok=True)
    ITEMS_DB_URL = "sqlite:///./data/items.db"
    AUTH_DB_URL = "sqlite:///./data/auth.db"
    items_engine = create_engine(ITEMS_DB_URL, connect_args={"check_same_thread": False})
    auth_engine = create_engine(AUTH_DB_URL, connect_args={"check_same_thread": False})

# ============================================================
# DATABASE 1 — Items
# ============================================================
ItemsSession = sessionmaker(autocommit=False, autoflush=False, bind=items_engine)
ItemsBase = declarative_base()


class ItemORM(ItemsBase):
    __tablename__ = "items"
    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(50), nullable=False, index=True)
    description = Column(String(200), nullable=True)
    price       = Column(Float, nullable=False)
    is_offer    = Column(Boolean, default=False)
    owner_id    = Column(Integer, nullable=True)


ItemsBase.metadata.create_all(bind=items_engine)

# ============================================================
# DATABASE 2 — Auth / Users
# ============================================================
AuthSession = sessionmaker(autocommit=False, autoflush=False, bind=auth_engine)
AuthBase = declarative_base()


class UserORM(AuthBase):
    __tablename__ = "users"
    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(50), unique=True, index=True, nullable=False)
    email           = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role            = Column(String(20), default="user")  # "user" | "admin"
    created_at      = Column(DateTime, default=datetime.utcnow)


AuthBase.metadata.create_all(bind=auth_engine)

# ============================================================
# PYDANTIC SCHEMAS
# ============================================================

class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    username: str  = Field(..., min_length=3, max_length=50,  example="john_doe")
    email:    str  = Field(...,                                example="john@example.com")
    password: str  = Field(..., min_length=6,                  example="password123")

    @field_validator("password")
    @classmethod
    def password_no_repetitiva(cls, v: str) -> str:
        """Rechaza contraseñas de caracteres repetitivos (ej: '111111', 'aaaaaa')."""
        if len(set(v)) < 3:
            raise ValueError("La contraseña no puede ser de caracteres repetitivos (ej: 111111). Usa al menos 3 caracteres distintos.")
        return v

class UserResponse(BaseModel):
    id:         int
    username:   str
    email:      str
    role:       str
    created_at: datetime
    class Config:
        from_attributes = True

class PasswordChange(BaseModel):
    current_password: str = Field(..., example="admin123")
    new_password:      str = Field(..., min_length=6, example="newpassword456")

    @field_validator("new_password")
    @classmethod
    def new_password_no_repetitiva(cls, v: str) -> str:
        """Misma regla que en el registro: sin contraseñas de caracteres repetitivos."""
        if len(set(v)) < 3:
            raise ValueError("La contraseña no puede ser de caracteres repetitivos (ej: 111111). Usa al menos 3 caracteres distintos.")
        return v

class ItemCreate(BaseModel):
    name:        str            = Field(..., min_length=2, max_length=50,  example="Auriculares Gamer")
    description: Optional[str]  = Field(None, max_length=200,             example="Sonido 7.1")
    price:       float          = Field(..., gt=0,                         example=120.00)
    is_offer:    bool           = Field(False,                             example=False)

class ItemUpdate(BaseModel):
    name:        Optional[str]   = Field(None, min_length=2, max_length=50)
    description: Optional[str]   = Field(None, max_length=200)
    price:       Optional[float] = Field(None, gt=0)
    is_offer:    Optional[bool]  = None

class ItemResponse(BaseModel):
    id:          int
    name:        str
    description: Optional[str]
    price:       float
    is_offer:    bool
    owner_id:    Optional[int]
    class Config:
        from_attributes = True

class HealthResponse(BaseModel):
    status:         str   = Field(..., example="healthy")
    uptime_seconds: float = Field(..., example=123.45)
    platform:       str   = Field(..., example="Linux-6.6.0-x86_64-with-glibc2.36")
    python_version: str   = Field(..., example="3.12.3 (main, Apr 15 2024, 18:34:47) [GCC 12.2.0]")

# ============================================================
# SECURITY UTILITIES
# ============================================================

pwd_context    = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme  = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire    = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_auth_db():
    db = AuthSession()
    try:
        yield db
    finally:
        db.close()


def get_items_db():
    db = ItemsSession()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db:    Session = Depends(get_auth_db)
) -> UserORM:
    try:
        payload  = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise ValueError()
    except (JWTError, ValueError):
        # ERROR: token inválido, expirado o manipulado — posible intento de
        # acceso no autorizado. send_log() es síncrona (Depends() sin BackgroundTasks).
        send_log("ERROR", "Intento de acceso con token JWT inválido, expirado o manipulado.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    user = db.query(UserORM).filter(UserORM.username == username).first()
    if not user:
        send_log("ERROR", f"Token válido pero el usuario '{username}' ya no existe en la base de datos.")
        raise HTTPException(status_code=401, detail="Usuario no encontrado.")
    return user


def require_admin(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    if current_user.role != "admin":
        # Auditoría: un usuario autenticado intentó una acción restringida a admin.
        # send_log() es síncrona (no hay BackgroundTasks disponible en un Depends()).
        send_log("WARNING", f"Acceso denegado: el usuario '{current_user.username}' (rol '{current_user.role}') intentó una acción que requiere rol admin.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol de administrador."
        )
    return current_user


# ============================================================
# FASTAPI APPLICATION
# ============================================================
START_TIME = time.time()

app = FastAPI(
    title="Python CRUD API Service",
    description="""
## API CRUD con Autenticación JWT y Dos Bases de Datos PostgreSQL

### Primeros pasos:
1. Registra un usuario en **`/auth/register`**
2. Inicia sesión en **`/auth/login`** para obtener un token JWT
3. Haz clic en **Authorize** y pega tu token para acceder a los endpoints protegidos

### Roles:
| Rol | Permisos |
|-----|----------|
| `user` | Listar y crear items |
| `admin` | Listar, crear, actualizar y eliminar items + ver todos los usuarios |

### Credenciales de prueba (admin por defecto):
- **Usuario:** `admin`
- **Contraseña:** `admin123`

### Bases de Datos:
- **`auth_db`** (PostgreSQL) → Usuarios, credenciales y roles
- **`items_db`** (PostgreSQL) → Inventario de productos

Ambas bases corren en el mismo servidor Postgres pero permanecen aisladas —
mismo diseño que antes con dos archivos SQLite independientes. Si no hay
servidor Postgres disponible (`POSTGRES_HOST` sin definir), el servicio cae
automáticamente a SQLite local (`data/auth.db` / `data/items.db`).
    """,
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_tags=[
        {"name": "Auth",   "description": "Registro, login y gestión de usuarios."},
        {"name": "Items",  "description": "CRUD de productos — requieren token JWT."},
        {"name": "System", "description": "Diagnóstico y estado del servicio."},
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom Swagger UI with Professional Theme
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="Python CRUD API Service",
        version="2.0.0",
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# ============================================================
# SEED INITIAL DATA (only if tables are empty)
# ============================================================

def seed_data():
    # Default admin user
    adb = AuthSession()
    try:
        if not adb.query(UserORM).filter(UserORM.username == "admin").first():
            adb.add(UserORM(
                username="admin",
                email="admin@example.com",
                hashed_password=hash_password("admin123"),
                role="admin"
            ))
            adb.commit()
    finally:
        adb.close()

    # Default items
    idb = ItemsSession()
    try:
        if idb.query(ItemORM).count() == 0:
            idb.add_all([
                ItemORM(name="Teclado Mecánico",  description="RGB con switches cherry brown",  price=89.99,  is_offer=True,  owner_id=1),
                ItemORM(name="Mouse Gamer",        description="Inalámbrico de alta precisión",  price=59.99,  is_offer=False, owner_id=1),
                ItemORM(name="Monitor 4K",         description="IPS 27\" HDR 144Hz",            price=349.99, is_offer=True,  owner_id=1),
            ])
            idb.commit()
    finally:
        idb.close()


seed_data()

# ============================================================
# CUSTOM SWAGGER UI ENDPOINT WITH PROFESSIONAL THEME
# ============================================================

LUCIDE_FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24' "
    "viewBox='0 0 24 24' fill='none' stroke='%23059669' stroke-width='2' "
    "stroke-linecap='round' stroke-linejoin='round'%3E"
    "%3Cpolyline points='4 17 10 11 4 5'%3E%3C/polyline%3E"
    "%3Cline x1='12' y1='19' x2='20' y2='19'%3E%3C/line%3E%3C/svg%3E"
)


SWAGGER_CUSTOM_CSS = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    :root {
        --brand: #10b981;
        --brand-dark: #34d399;
        --brand-soft: rgba(16,185,129,0.12);
        --ink: #f3f4f6;
        --muted: #9ca3af;
        --border: #262626;
        --bg: #000000;
        --card: #0a0a0a;
    }
    body, .swagger-ui { font-family: 'Plus Jakarta Sans', sans-serif !important; background: var(--bg); font-size: 16px; }
    .swagger-ui, .swagger-ui .scheme-container { background: var(--bg); color: var(--ink); }
    .swagger-ui .scheme-container { box-shadow: none; border-bottom: 1px solid var(--border); }

    /* Tamaños de texto — Swagger no define ninguno propio, hereda 12-13px por defecto */
    .swagger-ui .info .title { font-size: 2.1rem !important; }
    .swagger-ui .info { font-size: 1rem; }
    .swagger-ui .opblock-tag { font-size: 1.35rem !important; padding: 12px 0 !important; }
    .swagger-ui .opblock-tag small { font-size: 0.85rem !important; }
    .swagger-ui .opblock .opblock-summary-method { font-size: 0.85rem !important; min-width: 80px; }
    .swagger-ui .opblock .opblock-summary-path, .swagger-ui .opblock .opblock-summary-path__deprecated { font-size: 1rem !important; }
    .swagger-ui .opblock .opblock-summary-description { font-size: 0.92rem !important; }
    .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-external-docs-wrapper p, .swagger-ui .opblock-title_normal p { font-size: 0.95rem !important; }
    .swagger-ui .tab li { font-size: 0.95rem !important; }
    .swagger-ui .parameter__name { font-size: 0.95rem !important; }
    .swagger-ui .parameter__type, .swagger-ui .parameter__deprecated, .swagger-ui .parameter__in { font-size: 0.85rem !important; }
    .swagger-ui table thead tr td, .swagger-ui table thead tr th { font-size: 0.85rem !important; }
    .swagger-ui table tbody tr td { font-size: 0.92rem !important; }
    .swagger-ui .response-col_description__inner p, .swagger-ui .response-col_links { font-size: 0.92rem !important; }
    .swagger-ui .responses-table .response-col_status { font-size: 0.95rem !important; }
    .swagger-ui .model-title, .swagger-ui .model { font-size: 0.92rem !important; }
    .swagger-ui .btn { font-size: 0.9rem !important; }
    .swagger-ui .opblock-body pre.microlight, .swagger-ui .highlight-code, .swagger-ui .body-param textarea { font-size: 0.88rem !important; line-height: 1.55 !important; }

    /* Topbar */
    .swagger-ui .topbar { background: var(--card); box-shadow: 0 1px 3px rgba(0,0,0,0.4); padding: 10px 0; border-bottom: 1px solid var(--border); }
    .swagger-ui .topbar .download-url-wrapper .select-label { color: var(--ink); }
    .swagger-ui .topbar .download-url-wrapper input[type=text] { border-radius: 6px; background: var(--bg); color: var(--ink); border-color: var(--border); }
    .swagger-ui .topbar .download-url-wrapper .download-url-button { background: var(--brand); border-radius: 6px; color: #000; }

    /* Title / info block */
    .swagger-ui .info .title { font-family: 'Plus Jakarta Sans', sans-serif; color: var(--ink); font-weight: 800; }
    .swagger-ui .info .title small.version-stamp { background: var(--brand); }
    .swagger-ui .info .title small.version-stamp span { background: var(--brand); color: #000; }
    .swagger-ui .info a, .swagger-ui .info li, .swagger-ui .info p, .swagger-ui .info table { color: var(--muted); }
    .swagger-ui .info a { color: var(--brand); }
    .swagger-ui .info code { background: var(--brand-soft); color: var(--brand-dark); border-radius: 4px; padding: 2px 6px; }

    /* Section headers (tags) */
    .swagger-ui .opblock-tag { font-family: 'Plus Jakarta Sans', sans-serif; color: var(--ink); border-bottom: 1px solid var(--border); font-weight: 700; }
    .swagger-ui .opblock-tag:hover { background: var(--brand-soft); }
    .swagger-ui .opblock-tag small { color: var(--muted); }
    .swagger-ui .opblock-tag-section h3, .swagger-ui .opblock-tag-section svg { color: var(--ink); fill: var(--ink); }

    /* Operation blocks by method */
    .swagger-ui .opblock { border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); border: 1px solid var(--border); background: var(--card); }
    .swagger-ui .opblock .opblock-section-header { background: var(--card); box-shadow: none; border-bottom: 1px solid var(--border); }
    .swagger-ui .opblock.opblock-post { background: rgba(16,185,129,0.05); border-color: rgba(16,185,129,0.3); }
    .swagger-ui .opblock.opblock-post .opblock-summary-method { background: var(--brand); color: #000; }
    .swagger-ui .opblock.opblock-post .opblock-summary { border-color: rgba(16,185,129,0.3); }
    .swagger-ui .opblock.opblock-get { background: rgba(56,189,248,0.05); border-color: rgba(56,189,248,0.3); }
    .swagger-ui .opblock.opblock-get .opblock-summary-method { background: #38bdf8; color: #000; }
    .swagger-ui .opblock.opblock-get .opblock-summary { border-color: rgba(56,189,248,0.3); }
    .swagger-ui .opblock.opblock-put { background: rgba(245,158,11,0.05); border-color: rgba(245,158,11,0.3); }
    .swagger-ui .opblock.opblock-put .opblock-summary-method { background: #f59e0b; color: #000; }
    .swagger-ui .opblock.opblock-put .opblock-summary { border-color: rgba(245,158,11,0.3); }
    .swagger-ui .opblock.opblock-delete { background: rgba(239,68,68,0.05); border-color: rgba(239,68,68,0.3); }
    .swagger-ui .opblock.opblock-delete .opblock-summary-method { background: #ef4444; color: #000; }
    .swagger-ui .opblock.opblock-delete .opblock-summary { border-color: rgba(239,68,68,0.3); }
    .swagger-ui .opblock .opblock-summary-method { border-radius: 6px; font-weight: 700; }
    .swagger-ui .opblock .opblock-summary-path, .swagger-ui .opblock .opblock-summary-path__deprecated { color: var(--ink); }
    .swagger-ui .opblock .opblock-summary-description { color: var(--muted); }
    .swagger-ui .opblock-description-wrapper p, .swagger-ui .opblock-external-docs-wrapper p, .swagger-ui .opblock-title_normal p { color: var(--muted); }
    .swagger-ui .tab li, .swagger-ui .parameter__name, .swagger-ui .parameter__type, .swagger-ui .parameter__deprecated, .swagger-ui .parameter__in { color: var(--ink); }
    .swagger-ui .opblock-body pre.microlight, .swagger-ui .highlight-code { background: var(--bg) !important; color: var(--ink); }
    .swagger-ui .response-col_description__inner p, .swagger-ui .response-col_links { color: var(--muted); }
    .swagger-ui .parameters-col_description input, .swagger-ui .body-param textarea { background: var(--bg); color: var(--ink); border-color: var(--border); }
    .swagger-ui select { background: var(--bg); color: var(--ink); border-color: var(--border); }
    .swagger-ui .opblock-body select { background: var(--bg); }

    /* Buttons */
    .swagger-ui .btn.execute { background: var(--brand); color: #000; border-color: var(--brand); border-radius: 6px; font-weight: 600; }
    .swagger-ui .btn.execute:hover { background: var(--brand-dark); }
    .swagger-ui .btn.authorize { color: var(--brand); border-color: var(--brand); border-radius: 6px; font-weight: 600; background: transparent; }
    .swagger-ui .btn.authorize svg { fill: var(--brand); }
    .swagger-ui .btn.try-out__btn { border-radius: 6px; background: var(--bg); color: var(--ink); border-color: var(--border); }
    .swagger-ui .btn.cancel { color: #ef4444; border-color: #ef4444; background: transparent; }
    .swagger-ui button.btn { color: var(--ink); }

    /* Response codes */
    .swagger-ui .responses-table .response-col_status { font-weight: 700; color: var(--ink); }
    .swagger-ui table thead tr td, .swagger-ui table thead tr th { color: var(--muted); border-color: var(--border); }
    .swagger-ui table tbody tr td { border-color: var(--border); color: var(--ink); }
    .swagger-ui .model-box { background: var(--brand-soft); border-radius: 8px; }
    .swagger-ui .model, .swagger-ui .model-title, .swagger-ui .model-toggle:after { color: var(--ink); }
    .swagger-ui section.models { border-color: var(--border); background: var(--card); }
    .swagger-ui section.models.is-open h4 { border-color: var(--border); color: var(--ink); }
    .swagger-ui section.models .model-container { background: var(--bg); }

    /* Auth modal */
    .swagger-ui .dialog-ux .modal-ux { background: var(--card); border-color: var(--border); }
    .swagger-ui .dialog-ux .modal-ux-header, .swagger-ui .dialog-ux .modal-ux-content { border-color: var(--border); color: var(--ink); }
    .swagger-ui .dialog-ux .modal-ux-header h3 { color: var(--ink); }
    .swagger-ui .auth-container input[type=text], .swagger-ui .auth-container input[type=password] { background: var(--bg); color: var(--ink); border-color: var(--border); }
    .swagger-ui .auth-container h4, .swagger-ui .auth-container .errors span { color: var(--ink); }

    /* Scrollbar (webkit) for a tidier feel */
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-thumb { background: #333; border-radius: 8px; }
    ::-webkit-scrollbar-track { background: transparent; }
</style>
"""


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    swagger_html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " — Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_favicon_url=LUCIDE_FAVICON,
    )
    themed_body = swagger_html.body.decode("utf-8").replace(
        "</head>", SWAGGER_CUSTOM_CSS + "</head>"
    )
    return HTMLResponse(content=themed_body)


@app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
async def swagger_ui_redirect():
    return get_swagger_ui_oauth2_redirect_html()

# ============================================================
# AUTH ENDPOINTS
# ============================================================

@app.post(
    "/auth/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Auth"],
    summary="Registrar nuevo usuario",
    responses={
        400: {"description": "Usuario o email ya registrado", "content": {"application/json": {"example": {"detail": "El usuario o email ya existe."}}}},
        422: {"description": "Datos de entrada inválidos (username < 3, email malformado, password < 6 o de caracteres repetitivos)"},
    },
)
def register(user_data: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_auth_db)):
    """
    Crea una cuenta de usuario con rol **`user`** por defecto. El rol `admin` no puede
    asignarse desde este endpoint — solo existe el usuario semilla `admin`/`admin123`.

    - **username**: único, entre 3 y 50 caracteres
    - **email**: único, debe contener `@`
    - **password**: mínimo 6 caracteres y al menos 3 caracteres distintos — se rechazan
      contraseñas repetitivas como `111111` (se almacena hasheada con bcrypt, nunca en texto plano)

    Al registrarse correctamente, usa **`/auth/login`** para obtener tu token JWT.
    """
    if db.query(UserORM).filter(
        (UserORM.username == user_data.username) | (UserORM.email == user_data.email)
    ).first():
        background_tasks.add_task(send_log, "WARNING", f"Intento de registro fallido: el usuario o email '{user_data.username}/{user_data.email}' ya existe.")
        raise HTTPException(status_code=400, detail="El usuario o email ya existe.")

    user = UserORM(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        role="user"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    background_tasks.add_task(send_log, "INFO", f"Usuario registrado exitosamente: '{user.username}' con rol '{user.role}'.")
    return user


@app.post(
    "/auth/login",
    response_model=Token,
    tags=["Auth"],
    summary="Iniciar sesión — obtener token JWT",
    responses={
        401: {"description": "Credenciales inválidas", "content": {"application/json": {"example": {"detail": "Usuario o contraseña incorrectos."}}}},
    },
)
def login(
    background_tasks: BackgroundTasks,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_auth_db)
):
    """
    Autentica al usuario y devuelve un **token JWT Bearer** con validez de 60 minutos
    (ver `ACCESS_TOKEN_EXPIRE_MINUTES`). El token incluye `sub` (username) y `role`
    en el payload, firmado con HS256.

    **Nota:** este endpoint recibe `application/x-www-form-urlencoded` (OAuth2 password
    flow estándar), no JSON — campos `username` y `password`.

    Usa el token resultante en el botón **Authorize** de Swagger o como header:
    `Authorization: Bearer <token>`

    Credenciales de demo: `admin` / `admin123`.
    """
    user = db.query(UserORM).filter(UserORM.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        background_tasks.add_task(send_log, "WARNING", f"Intento de inicio de sesión fallido para el usuario: '{form_data.username}'")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    token = create_access_token({"sub": user.username, "role": user.role})
    background_tasks.add_task(send_log, "INFO", f"Inicio de sesión exitoso para el usuario: '{user.username}' con rol '{user.role}'")
    return {"access_token": token, "token_type": "bearer"}


@app.get(
    "/auth/me",
    response_model=UserResponse,
    tags=["Auth"],
    summary="Perfil del usuario autenticado",
    responses={401: {"description": "Token ausente, inválido o expirado"}},
)
def get_me(current_user: UserORM = Depends(get_current_user)):
    """
    Retorna los datos del usuario actual (id, username, email, role, created_at)
    decodificados a partir del token JWT enviado en el header `Authorization`.
    Útil para que el frontend valide la sesión y conozca el rol activo.
    """
    return current_user


@app.post(
    "/auth/change-password",
    tags=["Auth"],
    summary="Cambiar contraseña del usuario autenticado",
    responses={
        400: {"description": "Contraseña actual incorrecta", "content": {"application/json": {"example": {"detail": "La contraseña actual es incorrecta."}}}},
        401: {"description": "Token ausente, inválido o expirado"},
        422: {"description": "new_password con menos de 6 caracteres"},
    },
)
def change_password(
    data: PasswordChange,
    background_tasks: BackgroundTasks,
    current_user: UserORM = Depends(get_current_user),
    db: Session = Depends(get_auth_db)
):
    """
    Cambia la contraseña del usuario autenticado. Requiere enviar la contraseña
    **actual** para verificarla antes de aplicar la nueva (mínimo 6 caracteres).
    Los tokens ya emitidos siguen siendo válidos hasta su expiración natural —
    este endpoint no los revoca.
    """
    if not verify_password(data.current_password, current_user.hashed_password):
        background_tasks.add_task(send_log, "WARNING", f"Intento fallido de cambio de contraseña para '{current_user.username}': contraseña actual incorrecta.")
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")

    current_user.hashed_password = hash_password(data.new_password)
    db.commit()
    background_tasks.add_task(send_log, "INFO", f"El usuario '{current_user.username}' cambió su contraseña.")
    return {"status": "success", "message": "Contraseña actualizada correctamente."}


@app.get(
    "/auth/users",
    response_model=List[UserResponse],
    tags=["Auth"],
    summary="Listar todos los usuarios (solo Admin)",
    responses={
        401: {"description": "Token ausente, inválido o expirado"},
        403: {"description": "El usuario autenticado no tiene rol admin", "content": {"application/json": {"example": {"detail": "Acceso denegado. Se requiere rol de administrador."}}}},
    },
)
def list_users(
    _: UserORM = Depends(require_admin),
    db: Session = Depends(get_auth_db)
):
    """Lista todos los usuarios registrados, incluyendo su rol y fecha de alta. **Requiere rol de administrador.**"""
    return db.query(UserORM).all()


# ============================================================
# ITEMS CRUD ENDPOINTS (JWT PROTECTED)
# ============================================================

@app.get(
    "/api/items",
    response_model=List[ItemResponse],
    tags=["Items"],
    summary="Listar todos los artículos",
    responses={401: {"description": "Token ausente, inválido o expirado"}},
)
def get_items(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_items_db),
    _: UserORM = Depends(get_current_user)
):
    """
    Devuelve el inventario paginado (`skip`/`limit`). **Requiere autenticación**
    (cualquier rol: `user` o `admin`). Consulta `items_db`, independiente
    de la base de usuarios.
    """
    return db.query(ItemORM).offset(skip).limit(limit).all()


@app.get(
    "/api/items/{item_id}",
    response_model=ItemResponse,
    tags=["Items"],
    summary="Obtener artículo por ID",
    responses={
        401: {"description": "Token ausente, inválido o expirado"},
        404: {"description": "El artículo no existe", "content": {"application/json": {"example": {"detail": "Artículo 99 no encontrado."}}}},
    },
)
def get_item(
    item_id: int,
    db: Session = Depends(get_items_db),
    _: UserORM = Depends(get_current_user)
):
    """Busca un artículo por su ID. **Requiere autenticación.**"""
    item = db.query(ItemORM).filter(ItemORM.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Artículo {item_id} no encontrado.")
    return item


@app.post(
    "/api/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Items"],
    summary="Crear nuevo artículo",
    responses={
        401: {"description": "Token ausente, inválido o expirado"},
        422: {"description": "Datos inválidos (name < 2 chars, price <= 0)"},
    },
)
def create_item(
    item_data: ItemCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_items_db),
    current_user: UserORM = Depends(get_current_user)
):
    """
    Crea un nuevo artículo asociado (`owner_id`) al usuario autenticado.
    **Requiere autenticación** — cualquier rol puede crear artículos.
    """
    item = ItemORM(
        name=item_data.name,
        description=item_data.description,
        price=item_data.price,
        is_offer=item_data.is_offer,
        owner_id=current_user.id
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    background_tasks.add_task(send_log, "INFO", f"Usuario '{current_user.username}' creó el artículo '{item.name}' (ID: {item.id}, Precio: ${item.price:,.0f} COP).")
    return item


@app.put(
    "/api/items/{item_id}",
    response_model=ItemResponse,
    tags=["Items"],
    summary="Actualizar artículo (solo Admin)",
    responses={
        401: {"description": "Token ausente, inválido o expirado"},
        403: {"description": "El usuario autenticado no tiene rol admin"},
        404: {"description": "El artículo no existe"},
    },
)
def update_item(
    item_id: int,
    item_data: ItemUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_items_db),
    current_user: UserORM = Depends(require_admin)
):
    """
    Actualiza parcialmente un artículo — solo se modifican los campos enviados
    (`ItemUpdate` acepta todos los campos como opcionales). **Requiere rol de administrador.**
    """
    item = db.query(ItemORM).filter(ItemORM.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Artículo {item_id} no encontrado.")
    if item_data.name        is not None: item.name        = item_data.name
    if item_data.description is not None: item.description = item_data.description
    if item_data.price       is not None: item.price       = item_data.price
    if item_data.is_offer    is not None: item.is_offer    = item_data.is_offer
    db.commit()
    db.refresh(item)
    changes = {k: v for k, v in item_data.model_dump().items() if v is not None}
    background_tasks.add_task(send_log, "INFO", f"Administrador '{current_user.username}' actualizó el artículo ID {item_id}. Cambios: {changes}.")
    return item


@app.delete(
    "/api/items/{item_id}",
    tags=["Items"],
    summary="Eliminar artículo (solo Admin)",
    responses={
        401: {"description": "Token ausente, inválido o expirado"},
        403: {"description": "El usuario autenticado no tiene rol admin"},
        404: {"description": "El artículo no existe"},
    },
)
def delete_item(
    item_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_items_db),
    current_user: UserORM = Depends(require_admin)
):
    """Elimina permanentemente un artículo. **Requiere rol de administrador.**"""
    item = db.query(ItemORM).filter(ItemORM.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Artículo {item_id} no encontrado.")
    name = item.name
    db.delete(item)
    db.commit()
    background_tasks.add_task(send_log, "WARNING", f"Administrador '{current_user.username}' eliminó el artículo '{name}' (ID: {item_id}).")
    return {"status": "success", "message": f"Artículo {item_id} eliminado."}


# ============================================================
# SYSTEM ENDPOINTS
# ============================================================

@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Estado del servicio",
)
def health_check():
    """
    Endpoint de diagnóstico sin autenticación — útil para healthchecks de Docker/orquestadores.
    Retorna estado, tiempo de actividad en segundos desde el arranque del proceso
    (`uptime_seconds`, reflejado en el dashboard), plataforma y versión de Python.
    """
    return HealthResponse(
        status="healthy",
        uptime_seconds=round(time.time() - START_TIME, 2),
        platform=platform.platform(),
        python_version=sys.version
    )


# ============================================================
# INTERACTIVE DASHBOARD
# ============================================================

# Lucide icons (https://lucide.dev) as inline SVG, 16x16, stroke-based.
# Used to replace emoji markers (ICON_*) in the dashboard HTML below.
LUCIDE_ICONS = {
    "ICON_TERMINAL":      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>',
    "ICON_EYE":           '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
    "ICON_EYE_OFF":       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path><line x1="2" y1="2" x2="22" y2="22"></line></svg>',
    "ICON_ARROW_RIGHT":   '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>',
    "ICON_DATABASE":      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"></ellipse><path d="M3 5V19A9 3 0 0 0 21 19V5"></path><path d="M3 12A9 3 0 0 0 21 12"></path></svg>',
    "ICON_CHECK_SMALL":   '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    "ICON_PACKAGE":       '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="m7.5 4.27 9 5.15"></path><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"></path><path d="m3.3 7 8.7 5 8.7-5"></path><path d="M12 22V12"></path></svg>',
    "ICON_REFRESH":       '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>',
    "ICON_PLUS_CIRCLE":   '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="16"></line><line x1="8" y1="12" x2="16" y2="12"></line></svg>',
    "ICON_KEY_ROUND":     '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="M2.586 17.414A2 2 0 0 0 2 18.828V21a1 1 0 0 0 1 1h3a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h1a1 1 0 0 0 1-1v-1a1 1 0 0 1 1-1h.172a2 2 0 0 0 1.414-.586l.814-.814a6.5 6.5 0 1 0-4-4z"></path><circle cx="16.5" cy="7.5" r=".5" fill="currentColor"></circle></svg>',
    "ICON_LINK":          '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>',
    "ICON_BOOK":          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>',
    "ICON_MONITOR":       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><rect x="2" y="3" width="20" height="14" rx="2"></rect><line x1="8" y1="21" x2="16" y2="21"></line><line x1="12" y1="17" x2="12" y2="21"></line></svg>',
    "ICON_ACTIVITY":      '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>',
    "ICON_LOG_OUT":       '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>',
    "ICON_FILE_TEXT":     '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"></path><path d="M14 2v4a2 2 0 0 0 2 2h4"></path><path d="M10 9H8"></path><path d="M16 13H8"></path><path d="M16 17H8"></path></svg>',
    "ICON_MAP":           '<svg xmlns="http://www.w3.org/2000/svg" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px;"><path d="M14.106 5.553a2 2 0 0 0 1.788 0l3.659-1.83A1 1 0 0 1 21 4.619v12.764a1 1 0 0 1-.553.894l-4.553 2.277a2 2 0 0 1-1.788 0l-4.212-2.106a2 2 0 0 0-1.788 0l-3.659 1.83A1 1 0 0 1 3 19.381V6.618a1 1 0 0 1 .553-.894l4.553-2.277a2 2 0 0 1 1.788 0z"></path><path d="M15 5.764v15"></path><path d="M9 3.236v15"></path></svg>',
}

# ============================================================
# DOCUMENTATION VIEWER — renders the repo's .md files in-browser
# ============================================================

DOCS_MAP = {
    "summary":     ("Resumen del Proyecto",        "docs/PROJECT_SUMMARY.md"),
    "readme":      ("README",                       "README.md"),
    "visual":      ("Guía Visual de Arquitectura",   "docs/ARCHITECTURE_VISUAL_GUIDE.md"),
    "auth-arch":   ("Arquitectura del Auth Service", "docs/AUTH_SERVICE_ARCHITECTURE.md"),
}


@app.get("/documentation/{doc_id}", response_class=HTMLResponse, include_in_schema=False)
def view_documentation(doc_id: str):
    """Renderiza un archivo .md del repositorio como HTML navegable (Markdown vía marked.js)."""
    if doc_id not in DOCS_MAP:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    title, rel_path = DOCS_MAP[doc_id]
    file_path = os.path.join(os.path.dirname(__file__), rel_path)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Archivo '{rel_path}' no disponible en este contenedor.")

    nav_links = "".join(
        f'<a href="/documentation/{k}" class="doc-nav-link{" active" if k == doc_id else ""}">{v[0]}</a>'
        for k, v in DOCS_MAP.items()
    )

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__ — Documentación</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
    :root { --primary:#10b981; --primary-soft:rgba(16,185,129,0.12); --border:#262626; --text:#f3f4f6; --muted:#9ca3af; --bg:#000000; --card:#0a0a0a; }
    * { box-sizing:border-box; }
    body { font-family:'Plus Jakarta Sans',sans-serif; margin:0; background:var(--bg); color:var(--text); display:flex; min-height:100vh; }
    nav { width:260px; flex-shrink:0; background:var(--card); border-right:1px solid var(--border); padding:20px 12px; position:sticky; top:0; height:100vh; overflow-y:auto; }
    nav a.back { display:flex; align-items:center; gap:6px; font-size:0.8rem; color:var(--muted); text-decoration:none; margin-bottom:16px; padding:8px 10px; }
    nav a.back:hover { color:var(--text); }
    .doc-nav-link { display:block; padding:10px 12px; border-radius:8px; font-size:0.85rem; color:var(--text); text-decoration:none; margin-bottom:2px; }
    .doc-nav-link:hover { background:var(--primary-soft); }
    .doc-nav-link.active { background:var(--primary); color:#000; font-weight:600; }
    main { flex:1; padding:40px 48px; max-width:900px; }
    #content h1 { font-size:2rem; border-bottom:2px solid var(--border); padding-bottom:12px; }
    #content h2 { font-size:1.4rem; margin-top:2em; color:var(--primary); }
    #content h3 { font-size:1.1rem; margin-top:1.5em; }
    #content code { background:var(--primary-soft); color:var(--primary); padding:2px 6px; border-radius:4px; font-size:0.85em; }
    #content pre { background:var(--card); color:var(--text); padding:16px; border-radius:10px; overflow-x:auto; border:1px solid var(--border); }
    #content pre code { background:none; color:inherit; padding:0; }
    #content table { border-collapse:collapse; width:100%; margin:1em 0; }
    #content th, #content td { border:1px solid var(--border); padding:8px 12px; text-align:left; font-size:0.9rem; }
    #content th { background:var(--primary-soft); }
    #content a { color:var(--primary); }
    #content blockquote { border-left:3px solid var(--primary); margin:1em 0; padding:4px 16px; background:var(--primary-soft); border-radius:0 8px 8px 0; }
    #content img { max-width:100%; }
</style>
</head>
<body>
<nav>
    <a href="/" class="back">&larr; Volver al Dashboard</a>
    __NAV_LINKS__
</nav>
<main>
    <div id="content">Cargando...</div>
</main>
<script>
    const raw = __MD_JSON__;
    document.getElementById('content').innerHTML = marked.parse(raw);
</script>
</body>
</html>"""

    import json
    html = html.replace("__TITLE__", title)
    html = html.replace("__NAV_LINKS__", nav_links)
    html = html.replace("__MD_JSON__", json.dumps(md_content))

    response = HTMLResponse(content=html)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def read_root():
    html_content = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Python CRUD API v2 — Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #000000;
            --card: #0a0a0a;
            --border: #262626;
            --primary: #10b981;
            --primary-hover: #34d399;
            --primary-soft: rgba(16,185,129,0.12);
            --secondary: #9ca3af;
            --success: #10b981;
            --danger: #ef4444;
            --danger-soft: rgba(239,68,68,0.12);
            --warning: #f59e0b;
            --text: #f3f4f6;
            --muted: #9ca3af;
        }
        * { box-sizing:border-box; margin:0; padding:0; }
        body {
            font-family:'Plus Jakarta Sans',sans-serif;
            background:var(--bg); color:var(--text);
            min-height:100vh; display:flex; flex-direction:column;
            align-items:center; padding:32px 20px;
            overflow-x:hidden; position:relative;
        }

        .container { width:100%; max-width:1040px; display:flex; flex-direction:column; gap:20px; }

        /* Header */
        header {
            background:var(--card); border:1px solid var(--border);
            border-radius:20px; box-shadow:0 1px 3px rgba(0,0,0,0.04);
            padding:20px 28px; display:flex; justify-content:space-between; align-items:center;
        }
        .brand h1 {
            font-size:1.35rem; font-weight:700;
            color:var(--primary); display:flex; align-items:center; gap:10px;
        }
        .brand h1 i { width:28px; height:28px; }
        .brand p { font-size:0.72rem; color:var(--muted); margin-top:3px; }

        .badge {
            display:inline-flex; align-items:center; gap:6px;
            padding:7px 16px; border-radius:8px; font-size:0.8rem; font-weight:600;
            box-shadow:0 2px 8px rgba(0,0,0,0.08);
        }
        .badge-green  { background:linear-gradient(135deg, rgba(22,163,74,0.15), rgba(22,163,74,0.08)); border:1px solid rgba(22,163,74,0.4); color:#15803d; }
        .badge-indigo { background:linear-gradient(135deg, rgba(2,132,199,0.15), rgba(2,132,199,0.08)); border:1px solid rgba(2,132,199,0.4); color:#0369a1; }
        .badge-purple { background:linear-gradient(135deg, rgba(124,58,237,0.15), rgba(124,58,237,0.08)); border:1px solid rgba(124,58,237,0.4); color:#7c3aed; }
        .dot { width:8px; height:8px; border-radius:50%; background:currentColor; animation:pulse 1.8s infinite; }
        @keyframes pulse { 0%,100% { transform:scale(0.85); opacity:0.5; } 50% { transform:scale(1.15); opacity:1; } }

        /* Auth Gate */
        #auth-gate { display:flex; flex-direction:column; align-items:center; gap:20px; }
        .auth-card {
            background:var(--card); border:1px solid var(--border);
            border-radius:20px; box-shadow:0 1px 3px rgba(0,0,0,0.04);
            padding:32px; width:100%; max-width:420px;
            display:flex; flex-direction:column; gap:18px;
        }
        .tabs { display:flex; gap:8px; }
        .tab-btn {
            flex:1; padding:12px 14px; border-radius:8px; font-size:0.85rem;
            font-weight:600; cursor:pointer; border:1px solid var(--border); transition:all 0.2s;
            background:rgba(255,255,255,0.03); color:var(--text);
            pointer-events:auto; position:relative; z-index:10;
        }
        .tab-btn:hover:not(.active) { background:rgba(255,255,255,0.06); }
        .tab-btn.active { background:var(--primary); color:#fff; border-color:transparent; }
        .tab-content { display:none; flex-direction:column; gap:14px; }
        .tab-content.active { display:flex; }
        .hint { font-size:0.7rem; color:var(--muted); text-align:center; }
        .hint strong { color:var(--text); }

        /* Main App */
        #main-app { display:none; flex-direction:column; gap:20px; }

        /* Stats */
        .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:14px; }
        .stat {
            background:var(--card); border:1px solid var(--border);
            border-radius:14px; box-shadow:0 1px 3px rgba(0,0,0,0.04); padding:18px;
        }
        .stat-lbl { font-size:0.68rem; text-transform:uppercase; color:var(--muted); letter-spacing:0.05em; }
        .stat-val { font-size:1.25rem; font-weight:700; margin-top:6px; }

        /* Grid */
        .grid-2 { display:grid; grid-template-columns:1.2fr 0.8fr; gap:20px; }
        @media(max-width:700px) { .grid-2 { grid-template-columns:1fr; } }
        .panel {
            background:var(--card); border:1px solid var(--border);
            border-radius:20px; box-shadow:0 1px 3px rgba(0,0,0,0.04);
            padding:28px; display:flex; flex-direction:column; gap:18px;
        }
        .panel-title {
            font-size:0.95rem; font-weight:700;
            border-bottom:1px solid var(--border); padding-bottom:14px;
            display:flex; justify-content:space-between; align-items:center; gap:8px;
        }
        .panel-title .ic { color:var(--primary); flex-shrink:0; }

        /* Items */
        .items-list { display:flex; flex-direction:column; gap:10px; max-height:400px; overflow-y:auto; padding-right:4px; }
        .item-card {
            background:var(--bg); border:1px solid var(--border);
            border-radius:10px; padding:14px;
            display:flex; justify-content:space-between; align-items:center; transition:all 0.2s;
        }
        .item-card:hover { border-color:var(--primary); transform:translateX(3px); }
        .item-name { font-weight:600; font-size:0.88rem; }
        .item-desc { font-size:0.73rem; color:var(--muted); margin-top:2px; max-width:260px; }
        .item-price { font-size:0.83rem; font-weight:700; color:#a5b4fc; white-space:nowrap; }
        .offer-tag {
            background:linear-gradient(135deg, #fbbf24, #f59e0b);
            color:white; font-size:0.7rem; font-weight:700;
            padding:5px 12px; border-radius:6px; margin-left:8px;
            box-shadow:0 4px 12px rgba(245,158,11,0.3);
            text-transform:uppercase; letter-spacing:0.05em;
        }
        .item-actions { display:flex; gap:5px; align-items:center; flex-shrink:0; }
        .btn-sm {
            border-radius:6px; width:27px; height:27px;
            display:flex; align-items:center; justify-content:center;
            cursor:pointer; border:1px solid transparent; font-size:0.82rem; transition:all 0.2s;
        }
        .btn-del { background:rgba(239,68,68,0.1); border-color:rgba(239,68,68,0.3); color:var(--danger); }
        .btn-del:hover { background:var(--danger); color:white; }

        /* Form */
        .form-group { display:flex; flex-direction:column; gap:6px; }
        label { font-size:0.68rem; text-transform:uppercase; color:var(--muted); letter-spacing:0.05em; }
        input[type=text],input[type=email],input[type=password],input[type=number] {
            background:#0a0a0a; border:1px solid var(--border);
            border-radius:6px; padding:10px 12px; color:var(--text);
            font-family:inherit; font-size:0.9rem; width:100%;
            box-sizing:border-box;
        }
        input:focus { outline:none; border-color:var(--primary); border-width:2px; }
        input::placeholder { color:var(--muted); }
        .check-label { display:flex; align-items:center; gap:7px; font-size:0.78rem; color:var(--muted); cursor:pointer; }
        input[type=checkbox] { accent-color:var(--primary); width:14px; height:14px; }
        .form-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }

        /* Password field with visibility toggle */
        .pw-wrap { position:relative; display:flex; }
        .pw-wrap input { padding-right:40px; }
        .pw-toggle {
            position:absolute; right:0; top:0; height:100%; width:38px;
            display:flex; align-items:center; justify-content:center;
            cursor:pointer; color:var(--muted); background:none; border:none;
        }
        .pw-toggle:hover { color:var(--text); }

        /* Field validation state */
        .form-group.valid input { border-color:var(--success); }
        .form-group.invalid input { border-color:var(--danger); }
        .field-msg { font-size:0.7rem; min-height:14px; }
        .field-msg.err { color:var(--danger); }
        .field-msg.ok { color:var(--success); }

        /* Password strength meter */
        .pw-strength { display:flex; gap:4px; margin-top:2px; }
        .pw-strength span { height:4px; flex:1; border-radius:2px; background:var(--border); transition:background 0.2s; }
        .pw-strength.weak span:nth-child(1) { background:var(--danger); }
        .pw-strength.medium span:nth-child(1),
        .pw-strength.medium span:nth-child(2) { background:var(--warning); }
        .pw-strength.strong span { background:var(--success); }

        /* Buttons */
        .btn {
            display:flex; align-items:center; justify-content:center;
            padding:12px 20px; border-radius:6px; font-size:0.85rem;
            font-weight:600; cursor:pointer; transition:all 0.2s;
            text-decoration:none; border:none; gap:6px; font-family:inherit;
            width:100%; pointer-events:auto; position:relative; z-index:10;
        }
        .btn-primary { background:var(--primary); color:white; border:none; pointer-events:auto; }
        .btn-primary:hover { background:#047857; }
        .btn-secondary { background:rgba(255,255,255,0.05); border:1px solid var(--border); color:var(--text); }
        .btn-secondary:hover { background:rgba(255,255,255,0.08); }
        .btn-danger { background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); color:var(--danger); }
        .btn-danger:hover { background:var(--danger); color:white; }

        /* Misc */
        .empty { text-align:center; padding:30px; color:var(--muted); font-size:0.82rem; font-style:italic; }
        .msg-err {
            color:white; background:rgba(220,38,38,0.9); padding:12px 14px;
            border-radius:8px; font-size:0.82rem; text-align:center;
            border-left:4px solid #dc2626; display:none; margin:8px 0;
        }
        .msg-ok {
            color:white; background:rgba(5,150,105,0.9); padding:12px 14px;
            border-radius:8px; font-size:0.82rem; text-align:center;
            border-left:4px solid #059669; display:none; margin:8px 0;
        }

        /* Toasts: notificaciones no bloqueantes, reemplazan a alert() nativo */
        #toast-container {
            position:fixed; top:20px; right:20px; z-index:9999;
            display:flex; flex-direction:column; gap:10px; max-width:340px;
        }
        .toast {
            display:flex; align-items:flex-start; gap:10px;
            background:var(--card); border:1px solid var(--border);
            border-left:4px solid var(--danger); border-radius:10px;
            padding:14px 16px; box-shadow:0 8px 24px rgba(0,0,0,0.12);
            font-size:0.85rem; color:var(--text);
            animation:toast-in 0.25s ease-out;
        }
        .toast.toast-success { border-left-color:var(--success); }
        .toast.toast-warning { border-left-color:var(--warning); }
        .toast.toast-error   { border-left-color:var(--danger); }
        .toast .toast-icon { flex-shrink:0; width:18px; height:18px; margin-top:1px; }
        .toast.toast-success .toast-icon { color:var(--success); }
        .toast.toast-warning .toast-icon { color:var(--warning); }
        .toast.toast-error   .toast-icon { color:var(--danger); }
        .toast .toast-msg { flex:1; line-height:1.4; }
        .toast .toast-close {
            background:none; border:none; cursor:pointer; color:var(--muted);
            font-size:1rem; line-height:1; padding:0; flex-shrink:0;
        }
        .toast.toast-out { animation:toast-out 0.2s ease-in forwards; }
        @keyframes toast-in { from { opacity:0; transform:translateX(30px); } to { opacity:1; transform:translateX(0); } }
        @keyframes toast-out { from { opacity:1; transform:translateX(0); } to { opacity:0; transform:translateX(30px); } }

        .mono {
            font-family:monospace; font-size:0.7rem;
            background:var(--bg); padding:10px; border-radius:8px;
            border:1px solid var(--border); color:var(--success);
            white-space:pre-wrap; max-height:90px; overflow-y:auto; display:none;
        }
        .user-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
        .db-badges { display:flex; gap:8px; flex-wrap:wrap; }
        .db-badge {
            font-size:0.68rem; padding:3px 10px; border-radius:6px; font-weight:600;
            background:rgba(22,163,74,0.08); border:1px solid rgba(22,163,74,0.2); color:var(--success);
        }

        /* Documentation panel */
        .docs-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
        .doc-card {
            display:flex; align-items:center; gap:10px; padding:14px 16px;
            background:var(--bg); border:1px solid var(--border); border-radius:10px;
            text-decoration:none; color:var(--text); font-size:0.85rem; font-weight:600;
            transition:all 0.2s;
        }
        .doc-card:hover { border-color:var(--primary); background:var(--primary-soft); transform:translateY(-1px); }
        .doc-card.featured { background:var(--primary-soft); border-color:var(--primary); color:var(--primary-hover); }
        .doc-card .ic { color:var(--primary); flex-shrink:0; }

        /* Environment variables panel */
        .env-legend { display:flex; flex-wrap:wrap; gap:14px; margin-bottom:16px; font-size:0.75rem; color:var(--muted); }
        .env-legend-item { display:flex; align-items:center; gap:6px; }
        .env-swatch { width:9px; height:9px; border-radius:3px; flex-shrink:0; }
        .env-swatch.env-secret { background:#ef4444; }
        .env-swatch.env-config { background:#f59e0b; }
        .env-group { margin-bottom:18px; }
        .env-group-title {
            font-size:0.78rem; font-weight:700; text-transform:uppercase; letter-spacing:0.04em;
            color:var(--text); border-bottom:1px solid var(--border); padding-bottom:8px; margin-bottom:10px;
        }
        .env-group-note { font-size:0.72rem; font-weight:400; text-transform:none; letter-spacing:normal; color:var(--muted); margin-left:6px; }
        .env-card {
            background:var(--bg); border:1px solid var(--border); border-radius:10px;
            padding:12px 14px; margin-bottom:8px;
        }
        .env-card summary {
            cursor:pointer; list-style:none; display:flex; align-items:center; gap:10px; flex-wrap:wrap;
        }
        .env-card summary::-webkit-details-marker { display:none; }
        .env-card summary::before { content:"▸"; color:var(--muted); font-size:0.7rem; transition:transform 0.15s; }
        .env-card[open] summary::before { transform:rotate(90deg); }
        .env-name { font-family:monospace; font-size:0.83rem; font-weight:700; color:var(--text); }
        .env-tag {
            font-size:0.62rem; font-weight:700; text-transform:uppercase; letter-spacing:0.03em;
            padding:2px 8px; border-radius:5px; border:1px solid transparent;
        }
        .env-tag.env-secret { color:#ff8a80; background:rgba(239,68,68,0.12); border-color:rgba(239,68,68,0.35); }
        .env-tag.env-config { color:#ffcc66; background:rgba(245,158,11,0.12); border-color:rgba(245,158,11,0.35); }
        .env-body { margin-top:10px; padding-top:10px; border-top:1px solid var(--border); }
        .env-body p { font-size:0.82rem; color:var(--muted); margin:0 0 8px; line-height:1.5; }
        .env-body code { font-family:monospace; font-size:0.78rem; background:var(--card); border:1px solid var(--border); border-radius:4px; padding:1px 6px; color:var(--text); }
        .env-meta { font-size:0.78rem; color:var(--muted); margin-bottom:3px; }
        .env-meta span { margin-right:6px; }
        .env-footnote { font-size:0.78rem; color:var(--muted); margin-top:4px; }
        .env-footnote code { font-family:monospace; background:var(--bg); border:1px solid var(--border); border-radius:4px; padding:1px 6px; }
    </style>
</head>
<body>
<div id="toast-container"></div>
<div class="container">

    <!-- HEADER -->
    <header>
        <div class="brand">
            <h1>ICON_TERMINAL Python CRUD API Service</h1>
            <p>FastAPI · SQLAlchemy · JWT Auth · PostgreSQL (×2) · Docker · v2.0.0</p>
        </div>
        <div id="hdr-right">
            <span class="badge badge-green"><span class="dot"></span>ONLINE</span>
        </div>
    </header>

    <!-- AUTH GATE -->
    <div id="auth-gate">
        <div class="auth-card">
            <div class="tabs">
                <button class="tab-btn active" type="button" id="btn-login-tab">Iniciar Sesión</button>
                <button class="tab-btn" type="button" id="btn-register-tab">Registrarse</button>
            </div>

            <div id="tab-login" class="tab-content active">
                <div class="form-group">
                    <label>Usuario</label>
                    <input id="l-user" type="text" placeholder="Ej: admin" value="admin" autocomplete="username" required>
                </div>
                <div class="form-group">
                    <label>Contraseña</label>
                    <div class="pw-wrap">
                        <input id="l-pass" type="password" placeholder="Contraseña" value="admin123" autocomplete="current-password" required>
                        <button type="button" class="pw-toggle" data-target="l-pass">ICON_EYE</button>
                    </div>
                </div>
                <div id="l-err" class="msg-err"></div>
                <button class="btn btn-primary" type="button" id="btn-login">Entrar ICON_ARROW_RIGHT</button>
            </div>

            <div id="tab-register" class="tab-content">
                <div class="form-group" id="rg-user-group">
                    <label>Usuario</label>
                    <input id="r-user" type="text" placeholder="Mínimo 3 caracteres" autocomplete="username" required>
                    <div class="field-msg" id="rg-user-msg"></div>
                </div>
                <div class="form-group" id="rg-email-group">
                    <label>Email</label>
                    <input id="r-email" type="email" placeholder="correo@ejemplo.com" autocomplete="email" required>
                    <div class="field-msg" id="rg-email-msg"></div>
                </div>
                <div class="form-group" id="rg-pass-group">
                    <label>Contraseña</label>
                    <div class="pw-wrap">
                        <input id="r-pass" type="password" placeholder="Mínimo 6 caracteres" autocomplete="new-password" required>
                        <button type="button" class="pw-toggle" data-target="r-pass">ICON_EYE</button>
                    </div>
                    <div class="pw-strength" id="rg-pass-strength"><span></span><span></span><span></span></div>
                    <div class="field-msg" id="rg-pass-msg"></div>
                </div>
                <div class="form-group" id="rg-confirm-group">
                    <label>Confirmar Contraseña</label>
                    <div class="pw-wrap">
                        <input id="r-confirm" type="password" placeholder="Repite la contraseña" autocomplete="new-password" required>
                        <button type="button" class="pw-toggle" data-target="r-confirm">ICON_EYE</button>
                    </div>
                    <div class="field-msg" id="rg-confirm-msg"></div>
                </div>
                <div id="r-msg" class="msg-err"></div>
                <button class="btn btn-primary" type="button" id="btn-register">Crear Cuenta ICON_ARROW_RIGHT</button>
            </div>
        </div>
    </div>

    <!-- MAIN APP -->
    <div id="main-app">

        <!-- Stats Row -->
        <div class="stats">
            <div class="stat">
                <div class="stat-lbl">Usuario Activo</div>
                <div class="stat-val" id="s-user" style="font-size:1rem;">--</div>
            </div>
            <div class="stat">
                <div class="stat-lbl">Rol</div>
                <div class="stat-val" id="s-role" style="font-size:1rem;">--</div>
            </div>
            <div class="stat">
                <div class="stat-lbl">Productos</div>
                <div class="stat-val" id="s-items">0</div>
            </div>
            <div class="stat">
                <div class="stat-lbl">Tiempo Activo</div>
                <div class="stat-val" id="s-uptime" style="font-size:1rem;">--</div>
            </div>
        </div>

        <!-- DB Info Banner -->
        <div class="panel" style="padding:16px 24px; flex-direction:row; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
            <span style="font-size:0.8rem; color:var(--muted); font-weight:600; display:flex; align-items:center; gap:6px;">ICON_DATABASE Bases de Datos Conectadas</span>
            <div class="db-badges">
                <span class="db-badge">ICON_CHECK_SMALL __DB_BADGE_AUTH__ &nbsp;(Usuarios · Auth)</span>
                <span class="db-badge">ICON_CHECK_SMALL __DB_BADGE_ITEMS__ (Inventario · CRUD)</span>
            </div>
        </div>

        <!-- Content Grid -->
        <div class="grid-2">
            <!-- Items Panel -->
            <div class="panel">
                <div class="panel-title">
                    <span style="display:flex; align-items:center; gap:8px;">ICON_PACKAGE Inventario de Productos</span>
                    <button class="btn btn-secondary" type="button" id="btn-refresh-items" style="padding:5px 10px; font-size:0.7rem; width:auto;">ICON_REFRESH Refrescar</button>
                </div>
                <div id="items-box" class="items-list">
                    <div class="empty">Cargando...</div>
                </div>
            </div>

            <!-- Right Panel -->
            <div class="panel">
                <div class="panel-title"><span style="display:flex; align-items:center; gap:8px;">ICON_PLUS_CIRCLE Nuevo Producto</span></div>
                <form id="create-form" style="display:flex;flex-direction:column;gap:12px;">
                    <div class="form-group">
                        <label>Nombre</label>
                        <input id="f-name" type="text" placeholder="Ej. Silla Gamer" required>
                    </div>
                    <div class="form-group">
                        <label>Descripción</label>
                        <input id="f-desc" type="text" placeholder="Descripción breve">
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Precio (COP)</label>
                            <input id="f-price" type="number" step="1" min="1" placeholder="99900" required>
                        </div>
                        <div class="form-group" style="justify-content:flex-end;padding-bottom:8px;">
                            <label class="check-label">
                                <input id="f-offer" type="checkbox"> ¿Oferta?
                            </label>
                        </div>
                    </div>
                    <button type="submit" class="btn btn-primary">Guardar Producto</button>
                </form>

                <div class="panel-title" style="margin-top:4px;"><span style="display:flex; align-items:center; gap:8px;">ICON_KEY_ROUND Cambiar Contraseña</span></div>
                <form id="pw-change-form" style="display:flex;flex-direction:column;gap:12px;">
                    <div class="form-group">
                        <label>Contraseña Actual</label>
                        <div class="pw-wrap">
                            <input id="pw-current" type="password" placeholder="Contraseña actual" autocomplete="current-password" required>
                            <button type="button" class="pw-toggle" data-target="pw-current">ICON_EYE</button>
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Nueva Contraseña</label>
                        <div class="pw-wrap">
                            <input id="pw-new" type="password" placeholder="Mínimo 6 caracteres" autocomplete="new-password" required>
                            <button type="button" class="pw-toggle" data-target="pw-new">ICON_EYE</button>
                        </div>
                    </div>
                    <div id="pw-change-msg" class="msg-err"></div>
                    <button type="submit" class="btn btn-secondary">Actualizar Contraseña</button>
                </form>

                <div class="panel-title" style="margin-top:4px;"><span style="display:flex; align-items:center; gap:8px;">ICON_LINK Accesos</span></div>
                <a href="/docs" target="_blank" class="btn btn-primary">
                    ICON_BOOK Swagger UI — Documentación API
                </a>
                <a href="http://localhost:8010" target="_blank" class="btn btn-secondary" style="margin-top: 8px;">
                    ICON_MONITOR Consola de Logs Centralizada
                </a>
                <button class="btn btn-secondary" type="button" id="btn-test-health">ICON_ACTIVITY Probar /api/health</button>
                <div id="health-out" class="mono"></div>
                <button class="btn btn-danger" type="button" id="btn-logout">ICON_LOG_OUT Cerrar Sesión</button>
            </div>

            <!-- Documentation Panel -->
            <div class="panel" style="grid-column: 1 / -1;">
                <div class="panel-title"><span style="display:flex; align-items:center; gap:8px;">ICON_MAP Documentación del Proyecto</span></div>
                <div class="docs-grid">
                    __DOCS_LINKS__
                </div>
            </div>

            <!-- Environment Variables Panel -->
            <div class="panel" style="grid-column: 1 / -1;">
                <div class="panel-title"><span style="display:flex; align-items:center; gap:8px;">ICON_KEY_ROUND Variables de Entorno del Stack</span></div>
                <div class="env-legend">
                    <span class="env-legend-item"><span class="env-swatch env-secret"></span>Secreto — nunca compartir</span>
                    <span class="env-legend-item"><span class="env-swatch env-config"></span>Configuración</span>
                </div>

                <div class="env-group">
                    <div class="env-group-title">PostgreSQL <span class="env-group-note">usuarios e items</span></div>
                    <details class="env-card">
                        <summary><span class="env-name">POSTGRES_USER</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Usuario administrador de la base de datos Postgres. Lo crea el propio contenedor al arrancar por primera vez.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>postgres</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>postgres</code>, <code>auth-service</code></div>
                        </div>
                    </details>
                    <details class="env-card">
                        <summary><span class="env-name">POSTGRES_PASSWORD</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Contraseña de ese usuario. Antes estaba escrita directo en <code>docker-compose.yml</code>; ahora vive solo en <code>.env</code>, que no se sube a git.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>postgres</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>postgres</code>, <code>auth-service</code></div>
                        </div>
                    </details>
                </div>

                <div class="env-group">
                    <div class="env-group-title">MongoDB <span class="env-group-note">logs crudos (logs_db.logs)</span></div>
                    <details class="env-card">
                        <summary><span class="env-name">MONGO_INITDB_ROOT_USERNAME</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Usuario root de Mongo (nombre largo exigido por la imagen oficial). Dentro de <code>log-service</code> se recibe como <code>MONGO_USERNAME</code>.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>root</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>mongodb</code>, <code>log-service</code></div>
                        </div>
                    </details>
                    <details class="env-card">
                        <summary><span class="env-name">MONGO_INITDB_ROOT_PASSWORD</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Contraseña del usuario root de Mongo. Dentro de <code>log-service</code> se recibe como <code>MONGO_PASSWORD</code>.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>root</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>mongodb</code>, <code>log-service</code></div>
                        </div>
                    </details>
                </div>

                <div class="env-group">
                    <div class="env-group-title">RabbitMQ <span class="env-group-note">mensajería log-service → analysis-service</span></div>
                    <details class="env-card">
                        <summary><span class="env-name">RABBITMQ_DEFAULT_USER</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Usuario con el que log-service publica eventos y analysis-service los consume. Antes era implícito (guest/guest de la imagen); ahora es explícito y configurable.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>guest</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>rabbitmq</code>, <code>log-service</code>, <code>analysis-service</code></div>
                        </div>
                    </details>
                    <details class="env-card">
                        <summary><span class="env-name">RABBITMQ_DEFAULT_PASS</span><span class="env-tag env-secret">Secreto</span></summary>
                        <div class="env-body">
                            <p>Contraseña de ese usuario de mensajería.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>guest</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>rabbitmq</code>, <code>log-service</code>, <code>analysis-service</code></div>
                        </div>
                    </details>
                </div>

                <div class="env-group">
                    <div class="env-group-title">Autenticación y CORS <span class="env-group-note">quién entra y desde dónde</span></div>
                    <details class="env-card">
                        <summary><span class="env-name">JWT_SECRET_KEY</span><span class="env-tag env-secret">Secreto — el más sensible</span></summary>
                        <div class="env-body">
                            <p>Clave con la que auth-service firma cada token de sesión (JWT). Si se filtra, cualquiera podría fabricar un token válido de admin sin contraseña. Antes estaba escrita directo en el código Python.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>changeme-super-secret-key-for-jwt-in-production</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>auth-service</code> únicamente</div>
                        </div>
                    </details>
                    <details class="env-card">
                        <summary><span class="env-name">CORS_ORIGINS</span><span class="env-tag env-config">Configuración</span></summary>
                        <div class="env-body">
                            <p>Orígenes (dominios) autorizados a llamar la API desde el navegador. Antes los 3 servicios Python aceptaban cualquier origen (<code>*</code>); ahora solo el dashboard real.</p>
                            <div class="env-meta"><span>Valor dev:</span><code>http://localhost:3000</code></div>
                            <div class="env-meta"><span>Se usa en:</span><code>auth-service</code>, <code>log-service</code>, <code>analysis-service</code></div>
                        </div>
                    </details>
                </div>

                <p class="env-footnote">Los valores reales viven en <code>.env</code> (no se sube a git). <code>.env.example</code> es la plantilla pública que muestra qué variables existen sin exponer valores de producción.</p>
            </div>
        </div>
    </div>
</div>

<script>
    const ICONS = {
        arrowRight: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>',
        eye: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"></path><circle cx="12" cy="12" r="3"></circle></svg>',
        eyeOff: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.88 9.88a3 3 0 1 0 4.24 4.24"></path><path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68"></path><path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61"></path><line x1="2" y1="2" x2="22" y2="22"></line></svg>',
        crown: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="m2 4 3 12h14l3-12-6 7-4-7-4 7-6-7Z"></path></svg>',
        user: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
        trash: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"></path><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"></path><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>',
        checkCircle: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><path d="M21.801 10A10 10 0 1 1 17 3.335"></path><path d="m9 11 3 3L22 4"></path></svg>',
        xCircle: '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><circle cx="12" cy="12" r="10"></circle><path d="m15 9-6 6"></path><path d="m9 9 6 6"></path></svg>',
        activity: '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>',
    };

    const API = '';
    let token = localStorage.getItem('jwt') || null;
    let me = null;
    let uptimeInterval = null;
    let uptimeSeconds = 0;

    function switchTab(tabName) {
        const tabs = ['login', 'register'];
        tabs.forEach((name) => {
            const btn = document.getElementById('btn-' + name + '-tab');
            const content = document.getElementById('tab-' + name);
            if (name === tabName) {
                btn.classList.add('active');
                content.classList.add('active');
            } else {
                btn.classList.remove('active');
                content.classList.remove('active');
            }
        });
    }

    function authHeaders() {
        return {
            'Authorization': 'Bearer ' + token,
            'Content-Type': 'application/json'
        };
    }

    function showApp() {
        document.getElementById('auth-gate').style.display = 'none';
        document.getElementById('main-app').style.display = 'flex';
    }

    function showAuth() {
        document.getElementById('auth-gate').style.display = 'flex';
        document.getElementById('main-app').style.display = 'none';
        document.getElementById('hdr-right').innerHTML = '<span class="badge badge-green"><span class="dot"></span>ONLINE</span>';
    }

    async function doLogin() {
        const errEl = document.getElementById('l-err');
        errEl.textContent = '';
        errEl.style.display = 'none';

        const username = document.getElementById('l-user').value.trim();
        const password = document.getElementById('l-pass').value;

        if (!username || !password) {
            showError(errEl, 'Usuario y contraseña requeridos');
            return;
        }

        const loginBtn = document.getElementById('btn-login');
        loginBtn.disabled = true;
        loginBtn.textContent = 'Cargando...';

        try {
            const fd = new FormData();
            fd.append('username', username);
            fd.append('password', password);

            const resp = await fetch(API + '/auth/login', { method: 'POST', body: fd });
            if (!resp.ok) throw new Error('Login fallido');

            const data = await resp.json();
            token = data.access_token;
            localStorage.setItem('jwt', token);

            showSuccess(errEl, '¡Login exitoso! Entrando al dashboard...');
            await loadMeAndApp();
        } catch (error) {
            showError(errEl, error.message);
            loginBtn.disabled = false;
            loginBtn.textContent = 'Entrar ' + ICONS.arrowRight;
        }
    }

    function passwordScore(pw) {
        let score = 0;
        if (pw.length >= 6) score++;
        if (pw.length >= 10) score++;
        if (/[A-Z]/.test(pw) && /[0-9]/.test(pw)) score++;
        if (/[^A-Za-z0-9]/.test(pw)) score++;
        return Math.min(score, 3);
    }

    function updateFieldState(groupId, msgId, valid, message) {
        const group = document.getElementById(groupId);
        const msg = document.getElementById(msgId);
        group.classList.remove('valid', 'invalid');
        if (message === '') {
            msg.textContent = '';
            msg.className = 'field-msg';
            return;
        }
        group.classList.add(valid ? 'valid' : 'invalid');
        msg.textContent = message;
        msg.className = 'field-msg ' + (valid ? 'ok' : 'err');
    }

    function validateRegisterField(field) {
        const username = document.getElementById('r-user').value.trim();
        const email = document.getElementById('r-email').value.trim();
        const password = document.getElementById('r-pass').value;
        const confirm = document.getElementById('r-confirm').value;

        if (field === 'user' || field === 'all') {
            if (!username) updateFieldState('rg-user-group', 'rg-user-msg', false, '');
            else if (username.length < 3) updateFieldState('rg-user-group', 'rg-user-msg', false, 'Mínimo 3 caracteres');
            else updateFieldState('rg-user-group', 'rg-user-msg', true, 'Usuario válido');
        }
        if (field === 'email' || field === 'all') {
            if (!email) updateFieldState('rg-email-group', 'rg-email-msg', false, '');
            else if (!email.includes('@') || !email.includes('.')) updateFieldState('rg-email-group', 'rg-email-msg', false, 'Email inválido');
            else updateFieldState('rg-email-group', 'rg-email-msg', true, 'Email válido');
        }
        if (field === 'pass' || field === 'all') {
            const strengthEl = document.getElementById('rg-pass-strength');
            if (!password) {
                updateFieldState('rg-pass-group', 'rg-pass-msg', false, '');
                strengthEl.className = 'pw-strength';
            } else if (password.length < 6) {
                updateFieldState('rg-pass-group', 'rg-pass-msg', false, 'Mínimo 6 caracteres');
                strengthEl.className = 'pw-strength weak';
            } else {
                const score = passwordScore(password);
                const labels = ['Débil', 'Aceptable', 'Buena', 'Fuerte'];
                const cls = score <= 1 ? 'weak' : (score === 2 ? 'medium' : 'strong');
                strengthEl.className = 'pw-strength ' + cls;
                updateFieldState('rg-pass-group', 'rg-pass-msg', true, 'Seguridad: ' + labels[score]);
            }
        }
        if (field === 'confirm' || field === 'all') {
            if (!confirm) updateFieldState('rg-confirm-group', 'rg-confirm-msg', false, '');
            else if (confirm !== password) updateFieldState('rg-confirm-group', 'rg-confirm-msg', false, 'Las contraseñas no coinciden');
            else updateFieldState('rg-confirm-group', 'rg-confirm-msg', true, 'Las contraseñas coinciden');
        }
    }

    async function doRegister() {
        const el = document.getElementById('r-msg');
        el.textContent = '';
        el.style.display = 'none';

        const username = document.getElementById('r-user').value.trim();
        const email = document.getElementById('r-email').value.trim();
        const password = document.getElementById('r-pass').value;
        const confirm = document.getElementById('r-confirm').value;

        validateRegisterField('all');

        if (!username || username.length < 3) {
            showError(el, 'Usuario: mínimo 3 caracteres');
            return;
        }
        if (!email || !email.includes('@') || !email.includes('.')) {
            showError(el, 'Email inválido');
            return;
        }
        if (!password || password.length < 6) {
            showError(el, 'Contraseña: mínimo 6 caracteres');
            return;
        }
        if (confirm !== password) {
            showError(el, 'Las contraseñas no coinciden');
            return;
        }

        const registerBtn = document.getElementById('btn-register');
        const originalText = registerBtn.textContent;
        registerBtn.textContent = 'Creando...';
        registerBtn.disabled = true;

        try {
            const response = await fetch(API + '/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    username: username,
                    email: email,
                    password: password
                })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Error al registrar');
            }

            showSuccess(el, '¡Usuario "' + data.username + '" creado exitosamente!');
            document.getElementById('r-user').value = '';
            document.getElementById('r-email').value = '';
            document.getElementById('r-pass').value = '';
            document.getElementById('r-confirm').value = '';
            ['rg-user-group', 'rg-email-group', 'rg-pass-group', 'rg-confirm-group'].forEach(id => {
                document.getElementById(id).classList.remove('valid', 'invalid');
            });
            document.getElementById('rg-pass-strength').className = 'pw-strength';
            await new Promise(resolve => setTimeout(resolve, 1200));
            switchTab('login');
            document.getElementById('l-user').value = data.username;
            document.getElementById('l-pass').value = '';
        } catch (error) {
            showError(el, error.message);
        } finally {
            registerBtn.textContent = originalText;
            registerBtn.disabled = false;
        }
    }

    function showError(element, message) {
        element.className = 'msg-err';
        element.textContent = message;
        element.style.display = 'block';
    }

    function showSuccess(element, message) {
        element.className = 'msg-ok';
        element.textContent = message;
        element.style.display = 'block';
    }

    const TOAST_ICONS = {
        error: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
        warning: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        success: '<svg class="toast-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
    };

    // Notificación no bloqueante (reemplaza a alert() nativo). type: 'error' | 'warning' | 'success'
    function showToast(message, type) {
        type = type || 'error';
        const container = document.getElementById('toast-container');
        if (!container) { return; }

        const toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.innerHTML = (TOAST_ICONS[type] || TOAST_ICONS.error) +
            '<div class="toast-msg"></div>' +
            '<button class="toast-close" type="button" aria-label="Cerrar">&times;</button>';
        toast.querySelector('.toast-msg').textContent = message;

        function dismiss() {
            toast.classList.add('toast-out');
            setTimeout(function () { toast.remove(); }, 200);
        }

        toast.querySelector('.toast-close').onclick = dismiss;
        container.appendChild(toast);
        setTimeout(dismiss, 5000);
    }

    async function loadMeAndApp() {
        try {
            const resp = await fetch(API + '/auth/me', { headers: authHeaders() });
            if (!resp.ok) {
                throw new Error('Error al cargar usuario: ' + resp.status);
            }

            const data = await resp.json();
            me = data;
            document.getElementById('s-user').textContent = me.username;
            document.getElementById('s-role').innerHTML = (me.role === 'admin' ? ICONS.crown : ICONS.user) + ' ' + (me.role === 'admin' ? 'Admin' : 'User');
            document.getElementById('hdr-right').innerHTML = '<span class="badge badge-green"><span class="dot"></span>' + me.username + '</span>';

            showApp();
            loadItems();
            loadUptime();
            if (uptimeInterval) clearInterval(uptimeInterval);
            uptimeInterval = setInterval(tickUptime, 1000);
        } catch (error) {
            showToast('Error: ' + error.message, 'error');
            doLogout();
        }
    }

    function formatUptime(seconds) {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        if (h > 0) return h + 'h ' + m + 'min';
        if (m > 0) return m + 'min ' + s + 's';
        return s + 's';
    }

    function tickUptime() {
        uptimeSeconds++;
        document.getElementById('s-uptime').innerHTML = ICONS.activity + ' ' + formatUptime(uptimeSeconds);
    }

    async function loadUptime() {
        try {
            const resp = await fetch(API + '/api/health');
            if (!resp.ok) throw new Error('health check failed');
            const data = await resp.json();
            uptimeSeconds = data.uptime_seconds;
            document.getElementById('s-uptime').innerHTML = ICONS.activity + ' ' + formatUptime(uptimeSeconds);
        } catch (error) {
            document.getElementById('s-uptime').textContent = '--';
        }
    }

    function doLogout() {
        token = null;
        me = null;
        if (uptimeInterval) {
            clearInterval(uptimeInterval);
            uptimeInterval = null;
        }
        localStorage.removeItem('jwt');
        showAuth();
    }

    async function loadItems() {
        const box = document.getElementById('items-box');

        try {
            const response = await fetch(API + '/api/items', {
                headers: authHeaders()
            });

            if (!response.ok) {
                throw new Error('No autorizado');
            }

            const items = await response.json();
            document.getElementById('s-items').textContent = items.length;

            if (!items.length) {
                box.innerHTML = '<div class="empty">Sin productos registrados.</div>';
                return;
            }

            box.innerHTML = '';

            items.forEach((item) => {
                const isAdmin = me && me.role === 'admin';
                const offer = item.is_offer ? '<span class="offer-tag">OFERTA</span>' : '';
                const delBtn = isAdmin ? '<button class="btn-sm btn-del" type="button" onclick="delItem(' + item.id + ')" title="Eliminar">' + ICONS.trash + '</button>' : '';

                const div = document.createElement('div');
                div.className = 'item-card';
                const priceFormatted = new Intl.NumberFormat('es-CO', { style: 'currency', currency: 'COP', maximumFractionDigits: 0 }).format(item.price);
                div.innerHTML = '<div><div class="item-name">' + item.name + offer + '</div><div class="item-desc">' + (item.description || 'Sin descripción') + '</div></div><div class="item-actions"><span class="item-price">' + priceFormatted + '</span>' + delBtn + '</div>';
                box.appendChild(div);
            });

        } catch (error) {
            box.innerHTML = '<div class="empty" style="color:var(--danger)">Error: ' + error.message + '</div>';
        }
    }

    async function delItem(id) {
        if (!confirm('¿Eliminar este producto?')) {
            return;
        }

        try {
            const response = await fetch(API + '/api/items/' + id, {
                method: 'DELETE',
                headers: authHeaders()
            });

            if (response.ok) {
                showToast('Producto eliminado correctamente.', 'success');
                loadItems();
            } else {
                showToast('Error al eliminar (¿tienes rol admin?)', 'error');
            }
        } catch (error) {
            showToast('Error: ' + error.message, 'error');
        }
    }

    async function testHealth() {
        const el = document.getElementById('health-out');

        try {
            const response = await fetch(API + '/api/health');
            const data = await response.json();
            el.style.display = 'block';
            el.style.color = 'var(--success)';
            el.textContent = JSON.stringify(data, null, 2);
        } catch (error) {
            el.style.display = 'block';
            el.style.color = 'var(--danger)';
            el.textContent = 'Error: ' + error.message;
        }
    }

    // Event Listeners - ATTACHMENTS MUST BE IN GLOBAL SCOPE
    const loginTabBtn = document.getElementById('btn-login-tab');
    const registerTabBtn = document.getElementById('btn-register-tab');
    const loginBtn = document.getElementById('btn-login');
    const registerBtn = document.getElementById('btn-register');
    const createForm = document.getElementById('create-form');
    const refreshBtn = document.getElementById('btn-refresh-items');
    const healthBtn = document.getElementById('btn-test-health');
    const logoutBtn = document.getElementById('btn-logout');

    if (loginTabBtn) {
        loginTabBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            switchTab('login');
            return false;
        };
    }

    if (registerTabBtn) {
        registerTabBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            switchTab('register');
            return false;
        };
    }

    if (loginBtn) {
        loginBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            doLogin();
            return false;
        };
    }

    if (registerBtn) {
        registerBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            doRegister();
            return false;
        };
    }

    if (createForm) {
        createForm.onsubmit = async function(e) {
            e.preventDefault();
            try {
                const response = await fetch(API + '/api/items', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({
                        name: document.getElementById('f-name').value,
                        description: document.getElementById('f-desc').value,
                        price: parseFloat(document.getElementById('f-price').value),
                        is_offer: document.getElementById('f-offer').checked
                    })
                });
                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(JSON.stringify(errorData.detail));
                }
                document.getElementById('create-form').reset();
                showToast('Producto creado correctamente.', 'success');
                loadItems();
            } catch (error) {
                showToast('Error: ' + error.message, 'error');
            }
            return false;
        };
    }

    if (refreshBtn) {
        refreshBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            loadItems();
            return false;
        };
    }

    if (healthBtn) {
        healthBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            testHealth();
            return false;
        };
    }

    if (logoutBtn) {
        logoutBtn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            doLogout();
            return false;
        };
    }

    // Password visibility toggles (login, register, change-password)
    document.querySelectorAll('.pw-toggle').forEach(function(btn) {
        btn.onclick = function(e) {
            e.preventDefault();
            e.stopPropagation();
            const input = document.getElementById(btn.getAttribute('data-target'));
            const isHidden = input.type === 'password';
            input.type = isHidden ? 'text' : 'password';
            btn.innerHTML = isHidden ? ICONS.eyeOff : ICONS.eye;
            return false;
        };
    });

    // Real-time validation on the register form
    const rUserInput = document.getElementById('r-user');
    const rEmailInput = document.getElementById('r-email');
    const rPassInput = document.getElementById('r-pass');
    const rConfirmInput = document.getElementById('r-confirm');
    if (rUserInput) rUserInput.oninput = function() { validateRegisterField('user'); };
    if (rEmailInput) rEmailInput.oninput = function() { validateRegisterField('email'); };
    if (rPassInput) rPassInput.oninput = function() { validateRegisterField('pass'); validateRegisterField('confirm'); };
    if (rConfirmInput) rConfirmInput.oninput = function() { validateRegisterField('confirm'); };

    // Change password form
    const pwChangeForm = document.getElementById('pw-change-form');
    if (pwChangeForm) {
        pwChangeForm.onsubmit = async function(e) {
            e.preventDefault();
            const msgEl = document.getElementById('pw-change-msg');
            const currentPw = document.getElementById('pw-current').value;
            const newPw = document.getElementById('pw-new').value;

            if (newPw.length < 6) {
                showError(msgEl, 'La nueva contraseña debe tener mínimo 6 caracteres');
                return false;
            }

            try {
                const response = await fetch(API + '/auth/change-password', {
                    method: 'POST',
                    headers: authHeaders(),
                    body: JSON.stringify({ current_password: currentPw, new_password: newPw })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || 'No se pudo cambiar la contraseña');
                }
                showSuccess(msgEl, 'Contraseña actualizada correctamente');
                pwChangeForm.reset();
            } catch (error) {
                showError(msgEl, error.message);
            }
            return false;
        };
    }


    function initializeApp() {
        // Initialize
        if (token) {
            loadMeAndApp();
        } else {
            showAuth();
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeApp);
    } else {
        initializeApp();
    }
</script>
</body>
</html>"""
    docs_links_html = "".join(
        f'<a href="/documentation/{doc_id}" target="_blank" class="doc-card{" featured" if doc_id == "summary" else ""}">'
        f'<span class="ic">ICON_FILE_TEXT</span>{title}</a>'
        for doc_id, (title, _path) in DOCS_MAP.items()
    )
    html_content = html_content.replace("__DOCS_LINKS__", docs_links_html)

    if POSTGRES_HOST:
        html_content = html_content.replace("__DB_BADGE_AUTH__", "auth_db (PostgreSQL)")
        html_content = html_content.replace("__DB_BADGE_ITEMS__", "items_db (PostgreSQL)")
    else:
        html_content = html_content.replace("__DB_BADGE_AUTH__", "data/auth.db (SQLite)")
        html_content = html_content.replace("__DB_BADGE_ITEMS__", "data/items.db (SQLite)")

    for marker, svg in LUCIDE_ICONS.items():
        html_content = html_content.replace(marker, svg)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
