"""
Fixtures compartidas para los tests de auth-service.

app.py corre en modo SQLite cuando no hay POSTGRES_HOST — aquí forzamos
además una carpeta de datos temporal y aislada, para que correr los tests
no toque data/auth.db ni data/items.db de tu entorno local de desarrollo.
"""
import os
import sys

os.environ.setdefault("POSTGRES_HOST", "")  # fuerza el fallback a SQLite
os.chdir(os.path.dirname(os.path.dirname(__file__)))  # data/ relativa a auth-service/, no a tests/

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import app  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(app)
