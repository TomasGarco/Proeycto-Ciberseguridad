"""
Tests de la configuración de reglas en caliente (GET /rules + PATCH /rules/{id}).

Corre con: pytest (desde analysis-service/, con requirements-dev.txt instalado).
No requiere RabbitMQ ni Redis: sin REDIS_HOST el estado de las reglas vive solo
en memoria (el conftest ya lo garantiza) y el TestClient ejercita la API real.
"""
import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app import JWT_SECRET_KEY, RULES, _evaluate_event, app


@pytest.fixture()
def client():
    return TestClient(app)


def _headers(role):
    """Header Authorization con un JWT firmado con la misma clave que el
    servicio usa para verificar — simula un token emitido por auth-service."""
    token = jwt.encode({"sub": "tester", "role": role}, JWT_SECRET_KEY, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_patch_regla_sin_token_devuelve_401(client):
    response = client.patch("/rules/intento-inyeccion", json={"enabled": False})
    assert response.status_code == 401


def test_patch_regla_con_rol_analista_devuelve_403(client):
    response = client.patch(
        "/rules/intento-inyeccion", json={"enabled": False}, headers=_headers("analista")
    )
    assert response.status_code == 403


def test_patch_regla_inexistente_devuelve_404(client):
    response = client.patch(
        "/rules/no-existe", json={"enabled": False}, headers=_headers("admin")
    )
    assert response.status_code == 404


def test_get_rules_incluye_estado_enabled(client):
    response = client.get("/rules", headers=_headers("analista"))

    assert response.status_code == 200
    rules = response.json()
    assert len(rules) == len(RULES)
    assert all("enabled" in rule for rule in rules)


def test_regla_desactivada_no_dispara_y_reactivada_vuelve_a_disparar(client):
    evento = {"service": "auth-service", "level": "WARNING",
              "message": "entrada sospechosa: DROP TABLE users"}

    # Con la regla activa (estado inicial), el evento dispara intento-inyeccion
    assert any(a["rule_id"] == "intento-inyeccion" for a in _evaluate_event(evento))

    # Act: el admin la desactiva desde la API
    response = client.patch(
        "/rules/intento-inyeccion", json={"enabled": False}, headers=_headers("admin")
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    # Assert: el mismo evento ya no genera la alerta
    assert not any(a["rule_id"] == "intento-inyeccion" for a in _evaluate_event(evento))

    # Y al reactivarla, vuelve a disparar
    client.patch("/rules/intento-inyeccion", json={"enabled": True}, headers=_headers("admin"))
    assert any(a["rule_id"] == "intento-inyeccion" for a in _evaluate_event(evento))
