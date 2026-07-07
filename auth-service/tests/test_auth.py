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


# ------------------------------------------------------------------
# TU TURNO: completa este primer test.
#
# Objetivo: registrar un usuario nuevo y confirmar que el Auth Service
# responde con éxito.
#
# Pistas:
#   - El endpoint de registro es POST /auth/register (revisa app.py, sección
#     "AUTH ENDPOINTS", para ver el modelo UserCreate: qué campos exige).
#   - client.post("/auth/register", json={...}) hace la llamada.
#   - Un registro exitoso responde 201 (Created) — revisa el decorador del
#     endpoint en app.py para confirmar el status_code exacto.
#   - Puedes usar _unique_username() de arriba para el campo "username".
# ------------------------------------------------------------------
def test_register_new_user_succeeds(client):
    # TODO: arma el payload (username, email, password) y haz el POST.
    # TODO: assert response.status_code == ???
    pass


# ------------------------------------------------------------------
# Los siguientes casos quedan como guía para después de este primero —
# no hay código todavía, solo qué deberían probar:
#
# def test_register_duplicate_username_fails(client):
#     Registrar el mismo username dos veces -> la segunda vez debe fallar
#     (revisa qué status code y detail devuelve app.py en ese caso).
#
# def test_login_with_wrong_password_fails(client):
#     POST /auth/login con una contraseña incorrecta -> 401.
#
# def test_login_returns_valid_token(client):
#     Login correcto -> la respuesta trae "access_token" y "token_type".
#
# def test_protected_endpoint_without_token_fails(client):
#     Llamar a un endpoint protegido (ej. GET /auth/users) sin header
#     Authorization -> 401.
#
# def test_non_admin_cannot_access_admin_endpoint(client):
#     Un usuario con rol "user" intenta GET /auth/users (solo admin) -> 403.
# ------------------------------------------------------------------
