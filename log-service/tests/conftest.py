"""
Fixtures compartidas para los tests de log-service.

A diferencia de auth-service (que cae a SQLite sin POSTGRES_HOST), app.py
se conecta a MongoDB al importarse y no tiene fallback local — así que aquí
se reemplaza pymongo.MongoClient por un doble en memoria ANTES de importar
app. Los tests ejercitan los endpoints reales sin ningún contenedor corriendo.
"""
import os
import re
import sys

os.environ["JWT_SECRET_KEY"] = "clave-solo-para-tests"
os.environ.pop("RABBITMQ_HOST", None)  # sin broker: publish_event() no publica nada

import pymongo
import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from jose import jwt


class _FakeInsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, field, direction):
        self._docs.sort(key=lambda d: d.get(field), reverse=(direction == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeCollection:
    """Imita lo justo de pymongo.Collection que usa app.py: insert_one
    (mutando el dict con el _id, igual que pymongo) y find con los filtros
    $regex/$options que arma GET /logs."""

    def __init__(self):
        self._docs = []

    def insert_one(self, doc):
        doc["_id"] = ObjectId()
        self._docs.append(dict(doc))
        return _FakeInsertResult(doc["_id"])

    def find(self, query=None):
        query = query or {}
        return _FakeCursor([dict(d) for d in self._docs if self._matches(d, query)])

    @staticmethod
    def _matches(doc, query):
        for field, cond in query.items():
            if isinstance(cond, dict) and "$regex" in cond:
                flags = re.IGNORECASE if "i" in cond.get("$options", "") else 0
                if not re.match(cond["$regex"], str(doc.get(field, "")), flags):
                    return False
            elif doc.get(field) != cond:
                return False
        return True


class _FakeAdmin:
    def command(self, name):
        return {"ok": 1}


class _FakeDatabase:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


class _FakeMongoClient:
    def __init__(self, *args, **kwargs):
        self.admin = _FakeAdmin()
        self._dbs = {}

    def __getitem__(self, name):
        return self._dbs.setdefault(name, _FakeDatabase())


pymongo.MongoClient = _FakeMongoClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as log_app  # noqa: E402


@pytest.fixture()
def client():
    log_app.logs_collection._docs.clear()  # cada test arranca sin logs previos
    return TestClient(log_app.app)


@pytest.fixture()
def auth_headers():
    """Header Authorization con un JWT firmado con la misma clave que el
    servicio usa para verificar (la JWT_SECRET_KEY fijada arriba) — simula
    un token emitido por auth-service."""
    token = jwt.encode(
        {"sub": "tester", "role": "analista"},
        os.environ["JWT_SECRET_KEY"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}
