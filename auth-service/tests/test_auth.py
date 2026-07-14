"""
Tests de auth-service. Corre con: pytest (desde auth-service/, con requirements-dev.txt instalado)

Patrón para cada test:
    1. Arrange — preparar los datos que vas a enviar
    2. Act     — hacer la llamada real con el `client` (TestClient de FastAPI)
    3. Assert  — comprobar el status code y/o el contenido de la respuesta

Los endpoints reales están en app.py — usa Ctrl+F ahí para ver qué recibe
y qué devuelve cada uno antes de escribir el assert.
"""
import uuid


def _unique_username():
    """Cada test de registro necesita un usuario que no exista aún — evita choques entre tests."""
    return f"test_{uuid.uuid4().hex[:8]}"


def _register(client, username=None, password="Testing123"):
    """Registra un usuario nuevo y devuelve (username, password, response)."""
    username = username or _unique_username()
    response = client.post(
        "/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": password},
    )
    return username, password, response


def test_register_new_user_succeeds(client):
    # Arrange
    username = _unique_username()
    payload = {"username": username, "email": f"{username}@example.com", "password": "Testing123"}

    # Act
    response = client.post("/auth/register", json=payload)

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["username"] == username
    assert body["role"] == "analista"  # rol por defecto al registrarse


def test_register_duplicate_username_fails(client):
    # Arrange: registrar un usuario una primera vez
    username, password, first_response = _register(client)
    assert first_response.status_code == 201

    # Act: registrar el mismo username de nuevo (email distinto, no importa)
    response = client.post(
        "/auth/register",
        json={"username": username, "email": f"otro_{username}@example.com", "password": password},
    )

    # Assert
    assert response.status_code == 400
    assert "existe" in response.json()["detail"].lower()


def test_login_with_wrong_password_fails(client):
    # Arrange
    username, _, register_response = _register(client)
    assert register_response.status_code == 201

    # Act
    response = client.post(
        "/auth/login",
        data={"username": username, "password": "ContraseñaIncorrecta1"},
    )

    # Assert
    assert response.status_code == 401


def test_login_returns_valid_token(client):
    # Arrange
    username, password, register_response = _register(client)
    assert register_response.status_code == 201

    # Act
    response = client.post("/auth/login", data={"username": username, "password": password})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


def test_protected_endpoint_without_token_fails(client):
    # Act: /auth/users requiere autenticación, sin header Authorization
    response = client.get("/auth/users")

    # Assert
    assert response.status_code == 401


def test_non_admin_cannot_access_admin_endpoint(client):
    # Arrange: un usuario recién registrado nace con rol "analista", no "admin"
    username, password, register_response = _register(client)
    assert register_response.status_code == 201
    login_response = client.post("/auth/login", data={"username": username, "password": password})
    token = login_response.json()["access_token"]

    # Act
    response = client.get("/auth/users", headers={"Authorization": f"Bearer {token}"})

    # Assert
    assert response.status_code == 403


def test_logout_succeeds(client):
    # Arrange
    username, password, _ = _register(client)
    token = client.post("/auth/login", data={"username": username, "password": password}).json()["access_token"]

    # Act
    response = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})

    # Assert: sin Redis (los tests corren sin REDIS_HOST) la revocación en
    # servidor no aplica, pero el endpoint responde igual y lo dice.
    assert response.status_code == 200
    body = response.json()
    assert "revocada_en_servidor" in body


def test_sessions_list_requires_admin(client):
    # Arrange: usuario con rol "analista"
    username, password, _ = _register(client)
    token = client.post("/auth/login", data={"username": username, "password": password}).json()["access_token"]

    # Act
    response = client.get("/auth/sessions", headers={"Authorization": f"Bearer {token}"})

    # Assert
    assert response.status_code == 403
