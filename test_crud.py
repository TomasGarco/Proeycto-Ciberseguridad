"""Prueba de humo del CRUD de items contra el Auth Service.

Los endpoints /api/items están protegidos con JWT (y PUT/DELETE requieren rol
admin), así que el script primero inicia sesión y usa ese token en todas las
peticiones. Credenciales por variables de entorno (por defecto, el usuario
seed local admin/admin123):

    set TEST_USERNAME=admin
    set TEST_PASSWORD=admin123
    py test_crud.py

Apunta al Auth Service directo (:8000, sin pasar por nginx). Con el stack en
Docker las rutas son las mismas.
"""

import json
import os
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000"
BASE_URL = f"{BASE}/api/items"
USERNAME = os.getenv("TEST_USERNAME", "admin")
PASSWORD = os.getenv("TEST_PASSWORD", "admin123")


def login() -> str:
    """Devuelve el access_token JWT. /auth/login espera form-urlencoded."""
    body = urllib.parse.urlencode({"username": USERNAME, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req) as response:
        token = json.loads(response.read().decode())["access_token"]
        print(f"Login exitoso como '{USERNAME}'.")
        return token


def run_test():
    print("=== Iniciando Pruebas de API CRUD ===")

    token = login()
    auth = {"Authorization": f"Bearer {token}"}

    # 1. GET (Listar items)
    req = urllib.request.Request(BASE_URL, headers=auth, method="GET")
    with urllib.request.urlopen(req) as response:
        items = json.loads(response.read().decode())
        print(f"\nGET /api/items exitoso. Cantidad inicial: {len(items)}")
        for item in items:
            print(f"  - [{item['id']}] {item['name']}: ${item['price']}")

    # 2. POST (Crear item)
    new_item_data = {
        "name": "Silla Gamer",
        "description": "Silla ergonomica reclinable con soporte lumbar",
        "price": 199.99,
        "is_offer": True
    }
    data_bytes = json.dumps(new_item_data).encode('utf-8')
    req = urllib.request.Request(
        BASE_URL,
        data=data_bytes,
        headers={'Content-Type': 'application/json', **auth},
        method="POST"
    )
    with urllib.request.urlopen(req) as response:
        created_item = json.loads(response.read().decode())
        created_id = created_item['id']
        print(f"\nPOST /api/items exitoso. Item creado:")
        print(f"  - [{created_id}] {created_item['name']}: ${created_item['price']} (Oferta: {created_item['is_offer']})")

    # 3. GET /api/items/{id} (Obtener item creado)
    req = urllib.request.Request(f"{BASE_URL}/{created_id}", headers=auth, method="GET")
    with urllib.request.urlopen(req) as response:
        fetched_item = json.loads(response.read().decode())
        print(f"\nGET /api/items/{created_id} exitoso. Verificación:")
        print(f"  - Nombre: {fetched_item['name']}, Precio: ${fetched_item['price']}")

    # 4. PUT /api/items/{id} (Actualizar item — requiere rol admin)
    update_data = {
        "price": 179.99,
        "name": "Silla Gamer Pro"
    }
    update_bytes = json.dumps(update_data).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/{created_id}",
        data=update_bytes,
        headers={'Content-Type': 'application/json', **auth},
        method="PUT"
    )
    with urllib.request.urlopen(req) as response:
        updated_item = json.loads(response.read().decode())
        print(f"\nPUT /api/items/{created_id} exitoso. Cambios:")
        print(f"  - Nuevo Nombre: {updated_item['name']}, Nuevo Precio: ${updated_item['price']}")

    # 5. DELETE /api/items/{id} (Eliminar item — requiere rol admin)
    req = urllib.request.Request(f"{BASE_URL}/{created_id}", headers=auth, method="DELETE")
    with urllib.request.urlopen(req) as response:
        delete_result = json.loads(response.read().decode())
        print(f"\nDELETE /api/items/{created_id} exitoso. Resultado:")
        print(f"  - Status: {delete_result['status']}, Mensaje: {delete_result['message']}")

    # 6. GET (Listar final y verificar eliminación)
    req = urllib.request.Request(BASE_URL, headers=auth, method="GET")
    with urllib.request.urlopen(req) as response:
        final_items = json.loads(response.read().decode())
        print(f"\nGET /api/items exitoso. Cantidad final: {len(final_items)}")

    print("\n=== Todas las pruebas CRUD finalizaron con éxito! ===")

if __name__ == "__main__":
    run_test()
