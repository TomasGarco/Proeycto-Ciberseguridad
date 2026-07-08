"""
Fixtures compartidas para los tests del motor de reglas.

app.py arranca un hilo que se conecta a RabbitMQ (y, si REDIS_HOST está
definido, a Redis) apenas se importa el módulo. ANALYSIS_SKIP_CONSUMER=1
evita ese hilo aquí: los tests ejercitan _evaluate_event() y RULES
directamente, sin depender de ningún servicio externo.
"""
import os
import sys

os.environ["ANALYSIS_SKIP_CONSUMER"] = "1"
os.environ.pop("REDIS_HOST", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture(autouse=True)
def reglas_sin_estado():
    """Vacía las ventanas deslizantes de las reglas de umbral antes de cada test.

    Sin esto, un test de fuerza bruta dejaría timestamps en _threshold_windows
    que contaminarían el siguiente test.
    """
    import app

    app._threshold_windows.clear()
    yield
    app._threshold_windows.clear()
