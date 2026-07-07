import urllib.request
import json

BASE_URL = "http://127.0.0.1:8000/api/items"

def run_test():
    print("=== Iniciando Pruebas de API CRUD ===")
    
    # 1. GET (Listar items)
    req = urllib.request.Request(BASE_URL, method="GET")
    with urllib.request.urlopen(req) as response:
        items = json.loads(response.read().decode())
        print(f"GET /api/items exitoso. Cantidad inicial: {len(items)}")
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
        headers={'Content-Type': 'application/json'}, 
        method="POST"
    )
    with urllib.request.urlopen(req) as response:
        created_item = json.loads(response.read().decode())
        created_id = created_item['id']
        print(f"\nPOST /api/items exitoso. Item creado:")
        print(f"  - [{created_id}] {created_item['name']}: ${created_item['price']} (Oferta: {created_item['is_offer']})")

    # 3. GET /api/items/{id} (Obtener item creado)
    req = urllib.request.Request(f"{BASE_URL}/{created_id}", method="GET")
    with urllib.request.urlopen(req) as response:
        fetched_item = json.loads(response.read().decode())
        print(f"\nGET /api/items/{created_id} exitoso. Verificación:")
        print(f"  - Nombre: {fetched_item['name']}, Precio: ${fetched_item['price']}")

    # 4. PUT /api/items/{id} (Actualizar item)
    update_data = {
        "price": 179.99,
        "name": "Silla Gamer Pro"
    }
    update_bytes = json.dumps(update_data).encode('utf-8')
    req = urllib.request.Request(
        f"{BASE_URL}/{created_id}",
        data=update_bytes,
        headers={'Content-Type': 'application/json'},
        method="PUT"
    )
    with urllib.request.urlopen(req) as response:
        updated_item = json.loads(response.read().decode())
        print(f"\nPUT /api/items/{created_id} exitoso. Cambios:")
        print(f"  - Nuevo Nombre: {updated_item['name']}, Nuevo Precio: ${updated_item['price']}")

    # 5. DELETE /api/items/{id} (Eliminar item)
    req = urllib.request.Request(f"{BASE_URL}/{created_id}", method="DELETE")
    with urllib.request.urlopen(req) as response:
        delete_result = json.loads(response.read().decode())
        print(f"\nDELETE /api/items/{created_id} exitoso. Resultado:")
        print(f"  - Status: {delete_result['status']}, Mensaje: {delete_result['message']}")

    # 6. GET (Listar final y verificar eliminación)
    req = urllib.request.Request(BASE_URL, method="GET")
    with urllib.request.urlopen(req) as response:
        final_items = json.loads(response.read().decode())
        print(f"\nGET /api/items exitoso. Cantidad final: {len(final_items)}")
        
    print("\n=== Todas las pruebas CRUD finalizaron con éxito! ===")

if __name__ == "__main__":
    run_test()
