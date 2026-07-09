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
import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Logging operacional del propio proceso (conexión a RabbitMQ/Redis, eventos
# consumidos, alertas disparadas) — un objeto JSON por línea en stdout, mismo
# formato que auth-service/log-service.
def log_event(level: str, category: str, message: str):
    print(json.dumps({
        "timestamp": datetime.utcnow().isoformat(),
        "service": "analysis-service",
        "level": level,
        "category": category,
        "message": message,
    }))


RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
# Sin REDIS_HOST el servicio funciona solo en memoria — mismo patrón de
# fallback que POSTGRES_HOST en auth-service y RABBITMQ_HOST en log-service.
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "https://localhost").split(",")]

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
# Con Redis configurado (Semana 9) cada evento se espeja allí (write-through)
# y al arrancar se restauran los valores — /stats sobrevive reinicios.
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

# --- Redis (Semana 9): caché/persistencia de contadores y últimos eventos ---
_redis = None


def _connect_redis(retries: int = 5, delay_seconds: float = 2.0):
    client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, decode_responses=True,
        socket_connect_timeout=3, socket_timeout=3,
    )
    for attempt in range(1, retries + 1):
        try:
            client.ping()
            log_event("INFO", "REDIS", f"Conectado a Redis en {REDIS_HOST}:{REDIS_PORT}")
            return client
        except redis.exceptions.RedisError as e:
            if attempt == retries:
                log_event("WARNING", "REDIS", f"Sin conexión tras {retries} intentos ({e}) — contadores solo en memoria.")
                return None
            log_event("INFO", "REDIS", f"Esperando a Redis... (intento {attempt}/{retries})")
            time.sleep(delay_seconds)


def _restore_stats_from_redis():
    """Recarga contadores y eventos recientes persistidos en Redis al arrancar."""
    with _stats_lock:
        _stats["total_eventos"] = int(_redis.get("analysis:total_eventos") or 0)
        _stats["por_nivel"] = Counter({k: int(v) for k, v in _redis.hgetall("analysis:por_nivel").items()})
        _stats["por_servicio"] = Counter({k: int(v) for k, v in _redis.hgetall("analysis:por_servicio").items()})
        _stats["ultimo_evento_en"] = _redis.get("analysis:ultimo_evento_en")
        _stats["alertas_generadas"] = int(_redis.get("analysis:alertas_generadas") or 0)
        _stats["alertas_por_severidad"] = Counter(
            {k: int(v) for k, v in _redis.hgetall("analysis:alertas_por_severidad").items()}
        )
        # lrange devuelve del más reciente al más antiguo (LPUSH); se invierte
        # para que el deque quede en orden de llegada, como en _on_message.
        for raw in reversed(_redis.lrange("analysis:eventos_recientes", 0, _recent_events.maxlen - 1)):
            try:
                _recent_events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    if _stats["total_eventos"]:
        log_event("INFO", "REDIS", f"Contadores restaurados: {_stats['total_eventos']} eventos, {_stats['alertas_generadas']} alertas.")


def _persist_event_to_redis(event: dict, level: str, service: str, alerts: List[dict], timestamp: str):
    """Espejo en Redis de lo que _on_message acumula en memoria (write-through)."""
    if _redis is None:
        return
    try:
        pipe = _redis.pipeline()
        pipe.incr("analysis:total_eventos")
        pipe.hincrby("analysis:por_nivel", level, 1)
        pipe.hincrby("analysis:por_servicio", service, 1)
        pipe.set("analysis:ultimo_evento_en", timestamp)
        pipe.lpush("analysis:eventos_recientes", json.dumps(event, ensure_ascii=False))
        pipe.ltrim("analysis:eventos_recientes", 0, _recent_events.maxlen - 1)
        if alerts:
            pipe.incrby("analysis:alertas_generadas", len(alerts))
            for alert in alerts:
                pipe.hincrby("analysis:alertas_por_severidad", alert["severity"], 1)
        pipe.execute()
    except redis.exceptions.RedisError as e:
        log_event("WARNING", "REDIS", f"No se pudo persistir el evento ({e}) — el contador en memoria sigue al día.")


if REDIS_HOST:
    _redis = _connect_redis()
    if _redis is not None:
        _restore_stats_from_redis()


def _wait_for_rabbitmq(retries: int = 15, delay_seconds: float = 2.0) -> pika.BlockingConnection:
    credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST, port=RABBITMQ_PORT, credentials=credentials,
        heartbeat=60, blocked_connection_timeout=30,
    )
    for attempt in range(1, retries + 1):
        try:
            connection = pika.BlockingConnection(params)
            log_event("INFO", "RABBITMQ", f"Conectado a RabbitMQ en {RABBITMQ_HOST}:{RABBITMQ_PORT}")
            return connection
        except pika.exceptions.AMQPConnectionError:
            if attempt == retries:
                raise
            log_event("INFO", "RABBITMQ", f"Esperando a RabbitMQ... (intento {attempt}/{retries})")
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
        log_event("WARNING", "ANALYSIS", f"Mensaje descartado (JSON inválido): {body[:200]!r}")
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    level = str(event.get("level", "UNKNOWN")).upper()
    service = str(event.get("service", "unknown")).lower()
    received_at = datetime.now().isoformat()

    alerts = _evaluate_event(event)
    for alert in alerts:
        channel.basic_publish(
            exchange=ALERTS_EXCHANGE,
            routing_key=f"alerts.{alert['severity']}",
            body=json.dumps(alert, ensure_ascii=False),
            properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
        )
        log_event("WARNING", "ALERTA", f"({alert['severity'].upper()}) {alert['message']} — regla '{alert['rule_id']}'")

    with _stats_lock:
        _stats["total_eventos"] += 1
        _stats["por_nivel"][level] += 1
        _stats["por_servicio"][service] += 1
        _stats["ultimo_evento_en"] = received_at
        _recent_events.append(event)
        _stats["alertas_generadas"] += len(alerts)
        for alert in alerts:
            _stats["alertas_por_severidad"][alert["severity"]] += 1

    _persist_event_to_redis(event, level, service, alerts, received_at)

    log_event("INFO", "ANALYSIS", f"Evento consumido ({method.routing_key}): [{service}] [{level}] {event.get('message', '')}")
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
            log_event("INFO", "RABBITMQ", f"Consumiendo de la cola '{ANALYSIS_QUEUE}' (binding '{BINDING_KEY}')")
            channel.start_consuming()
        except Exception as e:
            log_event("ERROR", "RABBITMQ", f"Conexión perdida ({e}); reintentando en 3s...")
            time.sleep(3)


# ANALYSIS_SKIP_CONSUMER=1 evita levantar el hilo (y su intento de conexión a
# RabbitMQ) al importar este módulo desde los tests del motor de reglas.
if not os.getenv("ANALYSIS_SKIP_CONSUMER"):
    threading.Thread(target=_consume_loop, daemon=True, name="rabbitmq-consumer").start()

app = FastAPI(
    title="Analysis Service",
    description=(
        "Microservicio de análisis de eventos: consume logs desde RabbitMQ, aplica reglas de "
        "detección (umbral, patrón, palabra clave), publica alertas con severidad y expone "
        "estadísticas agregadas persistidas en Redis."
    ),
    version="2.1.0",
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
            "persistencia": "redis" if _redis is not None else "memoria",
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
