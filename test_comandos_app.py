"""
Comprueba la decision: que sale accion, que sale aviso y sobre que equipo.

Sin red y sin LLM. Lo que se vigila aqui es el fallo caro: que un nombre que no
coincide con nada acabe desarmando la casa entera, y que un intent nuevo en
`ai_handler` se cuele sin que nadie haya decidido que hace la app con el.

    python test_comandos_app.py
"""
import re
import sys

import ai_handler
import comandos_app


EQUIPOS = [
    {"id": "6C_C8_40_4F_C7", "nombre": "Casa", "armado": True, "en_linea": True},
    {"id": "A4_CF_12_9B_20", "nombre": "Bodega", "armado": False, "en_linea": False},
]


def _decidir(intent, device="Casa", dispositivos=EQUIPOS):
    return comandos_app.decidir(
        {"intent": intent, "device": device, "confidence": 0.9, "reply": "ok"},
        dispositivos,
    )


# --------------------------------------------------------------------------
# Resolución de nombres
# --------------------------------------------------------------------------

def test_un_nombre_que_no_existe_no_cae_a_todos_los_equipos():
    """El bug de `_resolve_device_ids_by_name`: el que manda el desarme al
    equipo equivocado, que ademas son todos."""
    assert comandos_app.resolver("garage", EQUIPOS) is None

    r = _decidir("disarm", device="garage")
    assert r["tipo"] == "aviso", r
    assert r["motivo"] == "device_not_found"
    # Y se le dicen los que si hay, que es lo unico util que se le puede decir.
    assert "Casa" in r["texto"] and "Bodega" in r["texto"]
    assert "all" not in r


def test_resuelve_el_nombre_exacto():
    assert comandos_app.resolver("Casa", EQUIPOS) == "6C_C8_40_4F_C7"
    assert comandos_app.resolver("bodega", EQUIPOS) == "A4_CF_12_9B_20"
    # El id tambien vale como nombre: el LLM a veces lo repite tal cual.
    assert comandos_app.resolver("A4_CF_12_9B_20", EQUIPOS) == "A4_CF_12_9B_20"


def test_resuelve_un_parcial_solo_si_es_unico():
    assert comandos_app.resolver("bod", EQUIPOS) == "A4_CF_12_9B_20"
    # Dos candidatos no son una coincidencia: mejor preguntar que elegir.
    dos = EQUIPOS + [{"id": "ZZ", "nombre": "Bodega chica"}]
    assert comandos_app.resolver("bodega", dos) == "A4_CF_12_9B_20"  # gana el exacto
    assert comandos_app.resolver("bod", dos) is None


def test_all_y_lista_vacia():
    assert comandos_app.resolver("all", EQUIPOS) == "all"
    assert comandos_app.resolver(None, EQUIPOS) == "all"
    # Sin equipos no hay nada sobre lo que actuar, y "all" seria mentira.
    assert comandos_app.resolver("all", []) is None
    assert comandos_app.resolver("Casa", []) is None
    r = _decidir("arm", dispositivos=[])
    assert r["tipo"] == "aviso" and r["motivo"] == "device_not_found"


def test_lo_que_devuelve_es_el_id_nunca_el_nombre():
    r = _decidir("arm", device="Casa")
    assert r["dispositivo"] == "6C_C8_40_4F_C7"
    assert r["accion"] == "arm"
    # El nombre solo aparece en el texto, que es para leer.
    assert "Casa" in r["texto"]


# --------------------------------------------------------------------------
# La tabla de acciones
# --------------------------------------------------------------------------

def test_las_doce_intenciones_estan_decididas():
    """
    Se leen del prompt de `ai_handler`, no de una copia: si alguien añade una
    decimotercera, esta prueba se cae hasta que se decida que hace la app.
    """
    del_prompt = set(re.findall(r'(?m)^- "([a-z_]+)"', ai_handler.INTENT_SYSTEM_PROMPT))
    assert len(del_prompt) == 12, del_prompt

    conocidos = set(comandos_app.CONFIRMAR) | set(comandos_app.AVISOS) | set(comandos_app.AL_RAG)
    assert del_prompt == conocidos, del_prompt ^ conocidos

    for intent in sorted(del_prompt):
        r = _decidir(intent)
        if intent in comandos_app.AL_RAG:
            assert r is None, f"{intent} deberia ir al RAG"
        else:
            esperado = "accion" if intent in comandos_app.CONFIRMAR else "aviso"
            assert r["tipo"] == esperado, (intent, r)
            assert r["texto"], intent


def test_la_fase_1_son_cuatro_acciones():
    assert set(comandos_app.CONFIRMAR) == {"arm", "disarm", "status", "list_devices"}


def test_lo_que_no_entra_avisa_y_dice_donde_se_hace():
    assert "Horarios" in _decidir("schedule")["texto"]
    assert "Horarios" in _decidir("query_schedule")["texto"]
    assert "Telegram" in _decidir("stop_alarm")["texto"]
    assert "Telegram" in _decidir("last_event")["texto"]
    # La bengala no se toca desde el chat: sus dos rutas se llaman parecido y
    # una acaba en sirena sonando.
    assert _decidir("trigger_bengala")["tipo"] == "aviso"


def test_un_intent_nuevo_no_se_cuela_como_accion():
    r = _decidir("autodestruccion")
    assert r["tipo"] == "aviso"
    assert r["motivo"] == "no_soportado:autodestruccion"


def test_sin_intent_va_al_rag():
    assert comandos_app.decidir(None, EQUIPOS) is None
    assert comandos_app.decidir({}, EQUIPOS) is None


# --------------------------------------------------------------------------
# Confirmación
# --------------------------------------------------------------------------

def test_solo_desarmar_pide_confirmacion():
    """Armar de mas es un susto; desarmar de mas es un fallo de seguridad."""
    assert _decidir("disarm")["confirmar"] is True
    assert "Confirmas" in _decidir("disarm")["texto"]
    assert _decidir("arm")["confirmar"] is False
    assert _decidir("status")["confirmar"] is False
    assert _decidir("list_devices")["confirmar"] is False


def test_list_devices_no_necesita_resolver_ningun_equipo():
    r = _decidir("list_devices", device="garage")
    assert r["tipo"] == "accion" and r["dispositivo"] == "all"


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
