import json
import os
import platform
import sys
import threading
import time
from collections import Counter, deque
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

# Estado en memoria del análisis (Semana 6: consumo + conteo básico).
# El motor de reglas de detección (umbral, patrón, palabra clave) y la
# evaluación de severidad llegan en la Semana 8.
_stats_lock = threading.Lock()
_stats = {
    "total_eventos": 0,
    "por_nivel": Counter(),
    "por_servicio": Counter(),
    "ultimo_evento_en": None,
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
    """Procesa un evento de log consumido de la cola."""
    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        print(f"[ANALYSIS] Mensaje descartado (JSON inválido): {body[:200]!r}")
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    level = str(event.get("level", "UNKNOWN")).upper()
    service = str(event.get("service", "unknown")).lower()

    with _stats_lock:
        _stats["total_eventos"] += 1
        _stats["por_nivel"][level] += 1
        _stats["por_servicio"][service] += 1
        _stats["ultimo_evento_en"] = datetime.now().isoformat()
        _recent_events.append(event)

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
    description="Microservicio de análisis de eventos: consume logs desde RabbitMQ y expone estadísticas agregadas.",
    version="1.0.0",
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
            "iniciado_en": _started_at,
        }


@app.get("/events/recent", response_model=List[dict], tags=["Análisis"])
def get_recent_events(limit: int = 20):
    """Últimos eventos consumidos (máximo 50 en memoria), del más reciente al más antiguo."""
    with _stats_lock:
        events = list(_recent_events)
    return events[::-1][:limit]
