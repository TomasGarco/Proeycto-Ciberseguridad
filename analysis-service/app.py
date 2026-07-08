import json
import os
import platform
import re
import sys
import threading
import time
from collections import Counter, defaultdict, deque
from datetime import datetime
from typing import List

import pika
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]

LOGS_EXCHANGE = "logs_events"
ANALYSIS_QUEUE = "analysis_queue"
BINDING_KEY = "logs.#"
ALERTS_EXCHANGE = "alerts_events"

# --- Motor de reglas de detección (Semana 8) ---
# Tres tipos de regla del roadmap: "umbral" (N eventos coincidentes dentro de
# una ventana deslizante), "patron" (regex sobre el mensaje) y "palabra_clave"
# (subcadena, sin distinguir mayúsculas). Cada alerta disparada se publica en
# el exchange 'alerts_events' con routing key 'alerts.<severidad>' y la
# persiste el Alert Service. Severidades sin acento: baja|media|alta|critica.
RULES = [
    {
        "id": "fuerza-bruta-login",
        "name": "Posible ataque de fuerza bruta",
        "type": "umbral",
        "severity": "critica",
        "match": "intento de inicio de sesión fallido",
        "threshold": 5,
        "window_seconds": 60,
        "per_service": False,
    },
    {
        "id": "rafaga-errores",
        "name": "Ráfaga de errores en un servicio",
        "type": "umbral",
        "severity": "alta",
        "level": "ERROR",
        "threshold": 10,
        "window_seconds": 60,
        "per_service": True,
    },
    {
        "id": "token-manipulado",
        "name": "Token JWT inválido o manipulado",
        "type": "patron",
        "severity": "alta",
        "pattern": r"token JWT inválido, expirado o manipulado",
    },
    {
        "id": "intento-inyeccion",
        "name": "Posible intento de inyección en la entrada",
        "type": "patron",
        "severity": "critica",
        "pattern": r"(' OR |DROP TABLE|<script|\.\./)",
    },
    {
        "id": "acceso-denegado",
        "name": "Acceso denegado a recurso restringido",
        "type": "palabra_clave",
        "severity": "media",
        "keywords": ["denegado", "no autorizado"],
    },
    {
        "id": "registro-fallido",
        "name": "Intento de registro fallido",
        "type": "palabra_clave",
        "severity": "baja",
        "keywords": ["registro fallido"],
    },
]

for _rule in RULES:
    if _rule["type"] == "patron":
        _rule["pattern_re"] = re.compile(_rule["pattern"], re.IGNORECASE)

# Ventanas deslizantes de las reglas de umbral (timestamps de eventos
# coincidentes). Solo las toca el hilo consumidor — no necesita lock.
_threshold_windows = defaultdict(deque)


def _evaluate_event(event: dict) -> List[dict]:
    """Aplica las reglas de detección a un evento; devuelve las alertas disparadas."""
    message = str(event.get("message", ""))
    message_lower = message.lower()
    level = str(event.get("level", "")).upper()
    service = str(event.get("service", "unknown")).lower()
    now = time.time()
    alerts = []

    for rule in RULES:
        fired = False
        detail = ""

        if rule["type"] == "umbral":
            if "match" in rule and rule["match"] not in message_lower:
                continue
            if "level" in rule and level != rule["level"]:
                continue
            key = f"{rule['id']}:{service}" if rule["per_service"] else rule["id"]
            window = _threshold_windows[key]
            window.append(now)
            while window and now - window[0] > rule["window_seconds"]:
                window.popleft()
            if len(window) >= rule["threshold"]:
                fired = True
                detail = f"{len(window)} eventos coincidentes en {rule['window_seconds']} s"
                # Vaciar la ventana actúa de cooldown: hacen falta otros N
                # eventos para volver a disparar (evita una alerta por evento).
                window.clear()
        elif rule["type"] == "patron":
            if rule["pattern_re"].search(message):
                fired = True
                detail = "el mensaje coincide con el patrón configurado"
        elif rule["type"] == "palabra_clave":
            matched = next((kw for kw in rule["keywords"] if kw in message_lower), None)
            if matched:
                fired = True
                detail = f"palabra clave detectada: '{matched}'"

        if fired:
            alerts.append({
                "rule_id": rule["id"],
                "rule_name": rule["name"],
                "rule_type": rule["type"],
                "severity": rule["severity"],
                "message": f"{rule['name']} — {detail}.",
                "service": service,
                "triggering_event": event,
                "timestamp": datetime.now().isoformat(),
            })

    return alerts


# Estado en memoria del análisis: contadores agregados + últimos eventos.
_stats_lock = threading.Lock()
_stats = {
    "total_eventos": 0,
    "por_nivel": Counter(),
    "por_servicio": Counter(),
    "ultimo_evento_en": None,
    "alertas_generadas": 0,
    "alertas_por_severidad": Counter(),
}
_recent_events = deque(maxlen=50)
_started_at = datetime.now().isoformat()
_start_time = time.time()


def _wait_for_rabbitmq(retries: int = 15, delay_seconds: float = 2.0) -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials,
        heartbeat=60, blocked_connection_timeout=30,
    )
    for attempt in range(1, retries + 1):
        try:
            connection = pika.BlockingConnection(params)
            print(f"[MQ] Conectado a RabbitMQ en {RABBITMQ_HOST}:{RABBITMQ_PORT}")
            return connection
        except pika.exceptions.AMQPConnectionError:
            if attempt == retries:
                raise
            print(f"[MQ] Esperando a RabbitMQ... (intento {attempt}/{retries})")
            time.sleep(delay_seconds)


def _on_message(channel, method, properties, body):
    """Procesa un evento de log: actualiza contadores, aplica las reglas de
    detección y publica las alertas disparadas en el exchange 'alerts_events'.

    La publicación reutiliza el canal del hilo consumidor: _on_message corre
    en ese mismo hilo, así que no hay problema de thread-safety ni hace falta
    abrir una conexión por alerta (a diferencia del log-service, cuyas rutas
    FastAPI corren en un threadpool).
    """
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        print(f"[ANALYSIS] Mensaje descartado (JSON inválido): {body[:200]!r}")
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    level = str(event.get("level", "UNKNOWN")).upper()
    service = str(event.get("service", "unknown")).lower()

    alerts = _evaluate_event(event)
    for alert in alerts:
        channel.basic_publish(
            exchange=ALERTS_EXCHANGE,
            routing_key=f"alerts.{alert['severity']}",
            body=json.dumps(alert, ensure_ascii=False),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        print(f"[ALERTA] ({alert['severity'].upper()}) {alert['message']} — regla '{alert['rule_id']}'")

    with _stats_lock:
        _stats["total_eventos"] += 1
        _stats["por_nivel"][level] += 1
        _stats["por_servicio"][service] += 1
        _stats["ultimo_evento_en"] = datetime.now().isoformat()
        _recent_events.append(event)
        _stats["alertas_generadas"] += len(alerts)
        for alert in alerts:
            _stats["alertas_por_severidad"][alert["severity"]] += 1

    print(f"[ANALYSIS] Evento consumido ({method.routing_key}): [{service}] [{level}] {event.get('message', '')}")
    channel.basic_ack(delivery_tag=method.delivery_tag)


def _consume_loop():
    """
    Bucle del hilo consumidor: conecta a RabbitMQ, declara exchange/cola y
    consume indefinidamente. Si la conexión se cae, reintenta desde cero.
    """
    while True:
        try:
            connection = _wait_for_rabbitmq()
            channel = connection.channel()
            channel.exchange_declare(exchange=LOGS_EXCHANGE, exchange_type="topic", durable=True)
            channel.exchange_declare(exchange=ALERTS_EXCHANGE, exchange_type="topic", durable=True)
            channel.queue_declare(queue=ANALYSIS_QUEUE, durable=True)
            channel.queue_bind(queue=ANALYSIS_QUEUE, exchange=LOGS_EXCHANGE, routing_key=BINDING_KEY)
            channel.basic_qos(prefetch_count=10)
            channel.basic_consume(queue=ANALYSIS_QUEUE, on_message_callback=_on_message)
            print(f"[MQ] Consumiendo de la cola '{ANALYSIS_QUEUE}' (binding '{BINDING_KEY}')")
            channel.start_consuming()
        except Exception as e:
            print(f"[MQ] Conexión perdida ({e}); reintentando en 3s...")
            time.sleep(3)


threading.Thread(target=_consume_loop, daemon=True, name="rabbitmq-consumer").start()

app = FastAPI(
    title="Analysis Service",
    description=(
        "Microservicio de análisis de eventos: consume logs desde RabbitMQ, aplica reglas de "
        "detección (umbral, patrón, palabra clave), publica alertas con severidad y expone "
        "estadísticas agregadas."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    status: str = Field(..., example="healthy")
    uptime_seconds: float = Field(..., example=123.45)
    platform: str = Field(..., example="Linux-6.6.0-x86_64")
    python_version: str = Field(..., example="3.12.0")


@app.get("/health", tags=["System"])
def health():
    """Estado del Analysis Service (formato legado, se mantiene por compatibilidad)."""
    return {"status": "ok", "service": "analysis-service", "iniciado_en": _started_at}


@app.get("/api/health", response_model=HealthResponse, tags=["System"], summary="Estado del servicio")
def health_check():
    """Endpoint de diagnóstico sin autenticación — útil para healthchecks de Docker/orquestadores."""
    return HealthResponse(
        status="healthy",
        uptime_seconds=round(time.time() - _start_time, 2),
        platform=platform.platform(),
        python_version=sys.version,
    )


@app.get("/stats", tags=["Análisis"])
def get_stats():
    """Estadísticas agregadas de los eventos consumidos desde RabbitMQ."""
    with _stats_lock:
        return {
            "total_eventos": _stats["total_eventos"],
            "por_nivel": dict(_stats["por_nivel"]),
            "por_servicio": dict(_stats["por_servicio"]),
            "ultimo_evento_en": _stats["ultimo_evento_en"],
            "alertas_generadas": _stats["alertas_generadas"],
            "alertas_por_severidad": dict(_stats["alertas_por_severidad"]),
            "iniciado_en": _started_at,
        }


@app.get("/rules", response_model=List[dict], tags=["Análisis"])
def get_rules():
    """Reglas de detección configuradas en el motor de análisis."""
    return [{k: v for k, v in rule.items() if k != "pattern_re"} for rule in RULES]


@app.get("/events/recent", response_model=List[dict], tags=["Análisis"])
def get_recent_events(limit: int = 20):
    """Últimos eventos consumidos (máximo 50 en memoria), del más reciente al más antiguo."""
    with _stats_lock:
        events = list(_recent_events)
    return events[::-1][:limit]
