import json
import os
import platform
import sys
import time
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson import ObjectId
import pika

START_TIME = time.time()

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DATABASE = os.getenv("MONGO_DATABASE", "logs_db")
MONGO_USERNAME = os.getenv("MONGO_USERNAME", "root")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "root")

MONGO_URL = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"

# RabbitMQ: si RABBITMQ_HOST no está definido, el servicio funciona sin cola
# (mismo patrón de fallback que POSTGRES_HOST en auth-service).
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
LOGS_EXCHANGE = "logs_events"

CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]


def publish_event(event: dict):
    """
    Publica el evento en el exchange topic 'logs_events' de RabbitMQ con
    routing key 'logs.<nivel>' para que otros servicios (Analysis Service)
    lo consuman de forma asíncrona.

    Se abre una conexión por publicación: las rutas síncronas de FastAPI
    corren en un threadpool y BlockingConnection de pika no es thread-safe.
    Si el broker no responde, el evento no se publica pero el log ya quedó
    persistido en MongoDB — la petición HTTP no falla por esto.
    """
    if not RABBITMQ_HOST:
        return
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
        connection = pika.BlockingConnection(pika.ConnectionParameters(
            host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials,
            connection_attempts=1, socket_timeout=3,
        ))
        channel = connection.channel()
        channel.exchange_declare(exchange=LOGS_EXCHANGE, exchange_type="topic", durable=True)
        routing_key = f"logs.{event.get('level', 'info').lower()}"
        channel.basic_publish(
            exchange=LOGS_EXCHANGE,
            routing_key=routing_key,
            body=json.dumps(event, ensure_ascii=False),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        connection.close()
        print(f"[RABBITMQ] Evento publicado con routing key '{routing_key}'")
    except Exception as e:
        print(f"[RABBITMQ] No se pudo publicar el evento: {e}")

def _wait_for_mongodb(retries: int = 15, delay_seconds: float = 2.0):
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            client.admin.command('ping')
            print(f"[DB] Conectado a MongoDB en {MONGO_HOST}:{MONGO_PORT}")
            return client
        except ConnectionFailure:
            if attempt == retries:
                raise
            print(f"[DB] Esperando a MongoDB... (intento {attempt}/{retries})")
            time.sleep(delay_seconds)

mongo_client = _wait_for_mongodb()
db = mongo_client[MONGO_DATABASE]
logs_collection = db["logs"]

app = FastAPI(
    title="Centralized Log Service",
    description="Microservicio dedicado a la centralización y visualización de logs de auditoría.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LogEntry(BaseModel):
    service: str = Field(..., example="auth-service")
    level: str = Field(..., example="INFO")  # INFO | WARNING | ERROR | DEBUG
    message: str = Field(..., example="Usuario 'admin' ha iniciado sesión.")
    timestamp: Optional[str] = Field(None, example="2026-06-17T17:15:00")

class HealthResponse(BaseModel):
    status: str = Field(..., example="healthy")
    uptime_seconds: float = Field(..., example=123.45)
    platform: str = Field(..., example="Linux-6.6.0-x86_64")
    python_version: str = Field(..., example="3.12.0")

@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["System"],
    summary="Estado del servicio",
)
def health_check():
    """
    Endpoint de diagnóstico sin autenticación — útil para healthchecks de Docker/orquestadores.
    """
    return HealthResponse(
        status="healthy",
        uptime_seconds=round(time.time() - START_TIME, 2),
        platform=platform.platform(),
        python_version=sys.version,
    )

COLORS = {
    "INFO": "\033[92m",    # Green
    "WARNING": "\033[93m", # Yellow
    "ERROR": "\033[91m",   # Red
    "DEBUG": "\033[96m",   # Cyan
    "RESET": "\033[0m"
}

@app.post("/logs", status_code=status.HTTP_201_CREATED, tags=["Logs"])
def create_log(entry: LogEntry):
    """
    Registra un evento de log enviado por cualquier microservicio en MongoDB.
    """
    ts = entry.timestamp or datetime.now().isoformat()
    log_msg = f"[{ts}] [{entry.service.upper()}] [{entry.level.upper()}] - {entry.message}"

    color = COLORS.get(entry.level.upper(), COLORS["RESET"])
    print(f"{color}{log_msg}{COLORS['RESET']}")

    entry_dict = entry.model_dump()
    entry_dict["timestamp"] = ts

    try:
        result = logs_collection.insert_one(entry_dict)
    except Exception as e:
        print(f"[ERROR] No se pudo guardar el log en MongoDB: {e}")
        raise HTTPException(status_code=500, detail="Error al guardar el log")

    # insert_one muta entry_dict añadiendo el ObjectId (no serializable a JSON):
    # se publica una copia con el id ya convertido a string.
    event = {k: v for k, v in entry_dict.items() if k != "_id"}
    event["id"] = str(result.inserted_id)
    publish_event(event)

    return {"status": "success", "recorded": True, "id": str(result.inserted_id)}

@app.get("/logs", response_model=List[dict], tags=["Logs"])
def get_logs(limit: int = 100, service: Optional[str] = None, level: Optional[str] = None):
    """
    Retorna logs de MongoDB con opciones de filtrado.
    """
    try:
        query = {}
        if service:
            query["service"] = {"$regex": f"^{service}$", "$options": "i"}
        if level:
            query["level"] = {"$regex": f"^{level}$", "$options": "i"}

        logs = list(logs_collection.find(query).sort("_id", -1).limit(limit))

        for log in logs:
            log["_id"] = str(log["_id"])

        return logs[::-1]
    except Exception as e:
        print(f"[ERROR] Error al obtener logs de MongoDB: {e}")
        return []

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def read_root():
    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Log Service Monitor</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;600;700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/lucide@latest"></script>
    <style>
        :root {{
            --bg: #000000;
            --panel: #0a0a0a;
            --border: #262626;
            --text: #f3f4f6;
            --muted: #9ca3af;
            --green: #4ade80;
            --yellow: #facc15;
            --red: #f87171;
            --cyan: #38bdf8;
            --primary: #38bdf8;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: 'Plus Jakarta Sans', sans-serif;
            background: var(--bg); color: var(--text);
            padding: 24px; min-height: 100vh;
            display: flex; flex-direction: column; gap: 20px;
        }}
        header {{
            background: var(--panel); border: 1px solid var(--border);
            border-radius: 12px; padding: 16px 24px;
            display: flex; justify-content: space-between; align-items: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        }}
        h1 {{ font-size: 1.25rem; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 10px; }}
        h1 i {{ color: var(--primary); width: 24px; height: 24px; }}
        .controls {{ display: flex; gap: 10px; align-items: center; }}
        select, button {{
            background: rgba(255,255,255,0.03); border: 1px solid var(--border);
            color: var(--text); padding: 8px 14px; border-radius: 6px;
            font-size: 0.85rem; font-family: inherit; outline: none; cursor: pointer;
            transition: all 0.2s;
        }}
        select:hover, button:hover {{
            background: rgba(56,189,248,0.1); border-color: var(--primary);
            color: var(--primary);
        }}
        button {{ display: flex; align-items: center; gap: 6px; }}
        button i {{ width: 16px; height: 16px; }}
        .terminal {{
            flex: 1; background: var(--panel); border: 1px solid var(--border);
            border-radius: 12px; display: flex; flex-direction: column; overflow: hidden;
            box-shadow: 0 4px 15px rgba(0,0,0,0.4);
        }}
        .terminal-header {{
            background: rgba(255,255,255,0.03); border-bottom: 1px solid var(--border);
            padding: 12px 16px; display: flex; align-items: center; gap: 8px;
        }}
        .dot {{ width: 12px; height: 12px; border-radius: 50%; }}
        .dot-red {{ background: #f38ba8; }}
        .dot-yellow {{ background: #f9e2af; }}
        .dot-green {{ background: #a6e3a1; }}
        .terminal-title {{
            font-family: 'Fira Code', monospace; font-size: 0.8rem;
            color: var(--muted); margin-left: 10px;
        }}
        .terminal-body {{
            flex: 1; padding: 20px; overflow-y: auto;
            font-family: 'Fira Code', monospace; font-size: 0.88rem;
            line-height: 1.6; display: flex; flex-direction: column; gap: 8px;
            max-height: 60vh; min-height: 400vh;
        }}
        .log-row {{ display: flex; gap: 12px; border-bottom: 1px solid rgba(255,255,255,0.04); padding-bottom: 4px; }}
        .log-ts {{ color: var(--muted); min-width: 170px; }}
        .log-service {{ color: var(--primary); min-width: 110px; font-weight: 600; }}
        .log-level {{ min-width: 80px; font-weight: 600; text-align: center; border-radius: 4px; padding: 0 4px; }}
        .level-info {{ background: rgba(74,222,128,0.12); color: var(--green); }}
        .level-warning {{ background: rgba(250,204,21,0.12); color: var(--yellow); }}
        .level-error {{ background: rgba(248,113,113,0.12); color: var(--red); }}
        .level-debug {{ background: rgba(56,189,248,0.12); color: var(--cyan); }}
        .log-msg {{ color: var(--text); flex-grow: 1; word-break: break-all; }}
        .empty {{ color: var(--muted); text-align: center; padding: 40px; font-style: italic; }}
    </style>
</head>
<body>
    <header>
        <div>
            <h1><i class="lucide lucide-activity"></i> Consola Central de Logs</h1>
            <p style="font-size: 0.75rem; color: var(--muted); margin-top: 4px;">Monitoreo en tiempo real de microservicios</p>
        </div>
        <div class="controls">
            <select id="filter-level" onchange="loadLogs()">
                <option value="">Todos los niveles</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
                <option value="DEBUG">DEBUG</option>
            </select>
            <select id="filter-service" onchange="loadLogs()">
                <option value="">Todos los servicios</option>
                <option value="auth-service">auth-service</option>
            </select>
            <button onclick="clearConsole()"><i class="lucide lucide-trash-2"></i> Limpiar</button>
            <button onclick="loadLogs()"><i class="lucide lucide-refresh-cw"></i> Refrescar</button>
        </div>
    </header>

    <div class="terminal">
        <div class="terminal-header">
            <div class="dot dot-red"></div>
            <div class="dot dot-yellow"></div>
            <div class="dot dot-green"></div>
            <span class="terminal-title">bash - logs/service.log - auto_refresh: 2s</span>
        </div>
        <div class="terminal-body" id="console">
            <div class="empty">Esperando logs de los servicios...</div>
        </div>
    </div>

    <script>
        const consoleEl = document.getElementById('console');
        
        async function loadLogs() {{
            const level = document.getElementById('filter-level').value;
            const service = document.getElementById('filter-service').value;
            
            let url = '/logs?limit=100';
            if (level) url += `&level=${{level}}`;
            if (service) url += `&service=${{service}}`;
            
            try {{
                const r = await fetch(url);
                const logs = await r.json();
                
                if (!logs.length) {{
                    consoleEl.innerHTML = '<div class="empty">No hay registros de logs para mostrar.</div>';
                    return;
                }}
                
                consoleEl.innerHTML = '';
                logs.forEach(log => {{
                    const row = document.createElement('div');
                    row.className = 'log-row';
                    
                    const ts = log.timestamp ? log.timestamp.replace('T', ' ').substring(0, 19) : '';
                    const levelClass = `level-${{log.level.toLowerCase()}}`;
                    
                    row.innerHTML = `
                        <span class="log-ts">${{ts}}</span>
                        <span class="log-service">[${{log.service.toLowerCase()}}]</span>
                        <span class="log-level ${{levelClass}}">${{log.level.upper ? log.level.upper() : log.level}}</span>
                        <span class="log-msg">${{log.message}}</span>
                    `;
                    consoleEl.appendChild(row);
                }});
            }} catch (e) {{
                console.error("Error cargando logs:", e);
            }}
        }}

        function clearConsole() {{
            consoleEl.innerHTML = '<div class="empty">Pantalla limpia. Esperando nuevos registros...</div>';
        }}

        // Auto-refresh every 2 seconds
        setInterval(() => {{
            loadLogs();
            lucide.createIcons();
        }}, 2000);

        // Initial load
        loadLogs();
        lucide.createIcons();
    </script>
</body>
</html>
""")
