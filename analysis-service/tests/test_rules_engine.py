"""
Tests del motor de reglas de detección (RULES + _evaluate_event en app.py).

Corre con: pytest (desde analysis-service/, con requirements-dev.txt instalado).
No requiere RabbitMQ, Redis ni Docker — _evaluate_event() es una función pura
sobre un dict de evento; ver conftest.py para cómo se evita levantar el hilo
consumidor al importar app.py.
"""
from app import _evaluate_event


def _evento(service="auth-service", level="WARNING", message=""):
    return {"service": service, "level": level, "message": message}


# ------------------------------------------------------------------
# Regla de umbral: fuerza-bruta-login
# ------------------------------------------------------------------

def test_evento_aislado_no_dispara_ninguna_regla():
    """Un evento INFO normal, sin coincidencias, no debe generar alertas."""
    evento = _evento(level="INFO", message="Inicio de sesión exitoso para el usuario: 'admin'")
    assert _evaluate_event(evento) == []


def test_cuatro_logins_fallidos_no_disparan_fuerza_bruta():
    """El umbral es 5 — con 4 intentos todavía no debe dispararse la alerta."""
    evento = _evento(message="Intento de inicio de sesión fallido para el usuario: 'atacante'")
    alertas = []
    for _ in range(4):
        alertas = _evaluate_event(evento)
    assert alertas == []


def test_quinto_login_fallido_dispara_fuerza_bruta_critica():
    """El 5to intento fallido en la ventana de 60s dispara la regla, severidad crítica."""
    evento = _evento(message="Intento de inicio de sesión fallido para el usuario: 'atacante'")
    alertas = []
    for _ in range(5):
        alertas = _evaluate_event(evento)

    ids = [a["rule_id"] for a in alertas]
    assert "fuerza-bruta-login" in ids
    disparada = next(a for a in alertas if a["rule_id"] == "fuerza-bruta-login")
    assert disparada["severity"] == "critica"
    assert disparada["rule_type"] == "umbral"


def test_cooldown_evita_alerta_duplicada_en_el_sexto_evento():
    """Al disparar, la ventana se vacía — el evento 6 no debe volver a disparar
    la misma regla inmediatamente después (haría falta otra racha de 5)."""
    evento = _evento(message="Intento de inicio de sesión fallido para el usuario: 'atacante'")
    for _ in range(5):
        _evaluate_event(evento)

    alertas_sexto_evento = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas_sexto_evento]
    assert "fuerza-bruta-login" not in ids


def test_fuerza_bruta_es_independiente_por_usuario_en_el_mensaje():
    """La regla cuenta por texto de mensaje coincidente, no filtra por usuario:
    5 fallos IGUALES disparan sin importar a qué usuario mencionen — documenta
    el comportamiento real (no hay agrupación por username en la regla)."""
    evento_a = _evento(message="Intento de inicio de sesión fallido para el usuario: 'user_a'")
    for _ in range(4):
        _evaluate_event(evento_a)

    evento_b = _evento(message="Intento de inicio de sesión fallido para el usuario: 'user_b'")
    alertas = _evaluate_event(evento_b)

    ids = [a["rule_id"] for a in alertas]
    assert "fuerza-bruta-login" in ids


# ------------------------------------------------------------------
# Regla de umbral por servicio: rafaga-errores
# ------------------------------------------------------------------

def test_rafaga_errores_requiere_diez_en_el_mismo_servicio():
    evento = _evento(service="log-service", level="ERROR", message="fallo de conexión a MongoDB")
    alertas = []
    for _ in range(10):
        alertas = _evaluate_event(evento)

    ids = [a["rule_id"] for a in alertas]
    assert "rafaga-errores" in ids
    disparada = next(a for a in alertas if a["rule_id"] == "rafaga-errores")
    assert disparada["severity"] == "alta"


def test_rafaga_errores_no_mezcla_servicios_distintos():
    """10 ERROR repartidos entre dos servicios (5 y 5) no deben disparar la
    regla en ninguno — el conteo es por servicio (per_service=True)."""
    alertas = []
    for _ in range(5):
        alertas = _evaluate_event(_evento(service="log-service", level="ERROR", message="fallo A"))
    for _ in range(5):
        alertas = _evaluate_event(_evento(service="auth-service", level="ERROR", message="fallo B"))

    ids = [a["rule_id"] for a in alertas]
    assert "rafaga-errores" not in ids


def test_rafaga_errores_ignora_niveles_distintos_de_error():
    evento = _evento(level="WARNING", message="algo sospechoso pero no crítico")
    alertas = []
    for _ in range(15):
        alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "rafaga-errores" not in ids


# ------------------------------------------------------------------
# Reglas de patrón (regex)
# ------------------------------------------------------------------

def test_token_manipulado_dispara_por_patron():
    evento = _evento(level="ERROR", message="Intento de acceso con token JWT inválido, expirado o manipulado.")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "token-manipulado" in ids
    disparada = next(a for a in alertas if a["rule_id"] == "token-manipulado")
    assert disparada["severity"] == "alta"
    assert disparada["rule_type"] == "patron"


def test_intento_inyeccion_detecta_sql_injection_clasico():
    evento = _evento(message="Login con payload sospechoso: admin' OR '1'='1")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "intento-inyeccion" in ids
    assert next(a for a in alertas if a["rule_id"] == "intento-inyeccion")["severity"] == "critica"


def test_intento_inyeccion_detecta_script_tag_sin_importar_mayusculas():
    """El regex usa re.IGNORECASE — <SCRIPT> también debe disparar."""
    evento = _evento(message="Payload recibido: <SCRIPT>alert(1)</SCRIPT>")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "intento-inyeccion" in ids


def test_patron_no_dispara_con_texto_no_relacionado():
    evento = _evento(level="ERROR", message="Timeout al conectar con la base de datos.")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "token-manipulado" not in ids
    assert "intento-inyeccion" not in ids


# ------------------------------------------------------------------
# Reglas de palabra clave
# ------------------------------------------------------------------

def test_acceso_denegado_dispara_por_palabra_clave():
    evento = _evento(level="WARNING", message="Acceso denegado: el usuario 'juan' intentó una acción que requiere rol admin.")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "acceso-denegado" in ids
    assert next(a for a in alertas if a["rule_id"] == "acceso-denegado")["severity"] == "media"


def test_registro_fallido_dispara_por_palabra_clave():
    evento = _evento(message="Intento de registro fallido: el usuario o email ya existe.")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "registro-fallido" in ids
    assert next(a for a in alertas if a["rule_id"] == "registro-fallido")["severity"] == "baja"


def test_palabra_clave_no_distingue_mayusculas():
    evento = _evento(message="ACCESO DENEGADO por rol insuficiente.")
    alertas = _evaluate_event(evento)
    ids = [a["rule_id"] for a in alertas]
    assert "acceso-denegado" in ids


# ------------------------------------------------------------------
# Estructura y metadatos de la alerta generada
# ------------------------------------------------------------------

def test_alerta_incluye_evento_original_y_servicio_en_minusculas():
    evento = _evento(service="AUTH-SERVICE", level="ERROR", message="token JWT inválido, expirado o manipulado")
    alertas = _evaluate_event(evento)
    disparada = next(a for a in alertas if a["rule_id"] == "token-manipulado")
    assert disparada["service"] == "auth-service"
    assert disparada["triggering_event"] == evento
    assert "timestamp" in disparada


def test_un_evento_puede_disparar_varias_reglas_a_la_vez():
    """Un mensaje que cae en dos categorías (denegado + patrón de inyección)
    debe generar una alerta por cada regla que coincide."""
    evento = _evento(level="WARNING", message="Acceso denegado — payload: ' OR '1'='1")
    alertas = _evaluate_event(evento)
    ids = {a["rule_id"] for a in alertas}
    assert {"acceso-denegado", "intento-inyeccion"}.issubset(ids)
