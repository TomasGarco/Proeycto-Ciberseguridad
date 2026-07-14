"""
Tests de log-service. Corre con: pytest (desde log-service/, con requirements-dev.txt instalado)

MongoDB está reemplazado por un doble en memoria (ver conftest.py), así que
estos tests ejercitan los endpoints reales sin depender de ningún contenedor.

Patrón para cada test:
    1. Arrange — preparar los datos que vas a enviar
    2. Act     — hacer la llamada real con el `client` (TestClient de FastAPI)
    3. Assert  — comprobar el status code y/o el contenido de la respuesta
"""


def _create_log(client, service="auth-service", level="INFO",
                message="Usuario 'admin' ha iniciado sesión."):
    """Registra un evento vía POST /logs (abierto: lo llaman los servicios del stack)."""
    return client.post("/logs", json={"service": service, "level": level, "message": message})


def test_health_check_is_public(client):
    # Act: /api/health no exige autenticación (lo usa el healthcheck de Docker)
    response = client.get("/api/health")

    # Assert
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_create_log_succeeds(client):
    # Act
    response = _create_log(client)

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "success"
    assert body["recorded"] is True
    assert body["id"]  # el ObjectId generado por Mongo, como string


def test_create_log_without_required_fields_fails(client):
    # Act: falta level y message — Pydantic debe rechazarlo antes de tocar la BD
    response = client.post("/logs", json={"service": "auth-service"})

    # Assert
    assert response.status_code == 422


def test_get_logs_without_token_fails(client):
    # Act: GET /logs exige JWT (Semana 10), sin header Authorization
    response = client.get("/logs")

    # Assert
    assert response.status_code == 401


def test_get_logs_with_invalid_token_fails(client):
    # Act: un token que no firmó auth-service no debe pasar
    response = client.get("/logs", headers={"Authorization": "Bearer token-basura"})

    # Assert
    assert response.status_code == 401


def test_get_logs_returns_created_log(client, auth_headers):
    # Arrange
    created = _create_log(client, message="Evento de prueba end-to-end")
    assert created.status_code == 201

    # Act
    response = client.get("/logs", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["message"] == "Evento de prueba end-to-end"
    assert logs[0]["_id"]  # el ObjectId viaja serializado como string


def test_get_logs_filters_by_service_and_level(client, auth_headers):
    # Arrange: tres eventos, solo uno coincide con ambos filtros
    _create_log(client, service="auth-service", level="INFO")
    _create_log(client, service="auth-service", level="ERROR", message="Login fallido")
    _create_log(client, service="log-service", level="INFO")

    # Act: el filtro es case-insensitive ("error" encuentra "ERROR")
    response = client.get("/logs?service=auth-service&level=error", headers=auth_headers)

    # Assert
    assert response.status_code == 200
    logs = response.json()
    assert len(logs) == 1
    assert logs[0]["message"] == "Login fallido"


def test_get_logs_respects_limit(client, auth_headers):
    # Arrange
    for i in range(5):
        _create_log(client, message=f"evento {i}")

    # Act
    response = client.get("/logs?limit=3", headers=auth_headers)

    # Assert: se conservan los 3 más recientes, devueltos en orden cronológico
    logs = response.json()
    assert [log["message"] for log in logs] == ["evento 2", "evento 3", "evento 4"]
