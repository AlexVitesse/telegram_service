#!/usr/bin/env python3
"""
#260: traspaso de una central solo con el codigo que da por BLE.

Antes bastaba conocer la MAC en los 15 min tras un arranque: despues de un
corte de luz cualquiera podia quedarse la central a distancia. Ahora la central
(firmware 2026.11.26) da un codigo de un solo uso por BLE en modo
configuracion y manda su SHA-256 al conectar; /equipos/reclamar lo gasta.

    python test_codigo_alta.py
"""
import asyncio
import copy
import hashlib
import json
import sys
import time
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock

from mqtt_handler import MqttHandler
from test_retro_banco import MAC, _arbol_jose, _fm

CODIGO = "0123456789abcdef0123456789abcdef"


def _mqtt():
    h = MqttHandler.__new__(MqttHandler)
    h.device_id, h.device_location = MAC, ""
    h.firebase_manager, h.device_manager = MagicMock(), MagicMock()
    h.last_arm_event_time, h.last_arm_event_ts = {}, {}
    h.last_telemetry = {}
    h.prueba_fisica, h.codigos_alta, h.con_codigo_alta = {}, {}, set()
    h._ids_vistos, h._arranques_por_confirmar = OrderedDict(), {}
    h._on_event_callback = MagicMock()
    h.send_command = MagicMock()
    return h


def _llega_codigo(h, codigo=CODIGO):
    h._handle_event(json.dumps({"deviceId": MAC, "eventType": "codigo_alta",
                                "data": {"h": hashlib.sha256(codigo.encode()).hexdigest()}}))


def _reclamar(fm, mqtt, cuerpo):
    from test_api_server import con_api, pedir
    out = []

    async def p(url, api):
        api._bot.mqtt_handler = mqtt
        out.append(await pedir(url, token="bueno", cuerpo={"mac": MAC, **cuerpo}, ruta="/equipos/reclamar"))
    asyncio.run(con_api(fm, "pedro", p))
    return out[0]


def test_el_codigo_llega_sin_avisar_a_nadie():
    h = _mqtt()
    _llega_codigo(h)
    assert MAC in h.codigos_alta and h.exige_codigo_alta(MAC)
    h._on_event_callback.assert_not_called()


def test_con_el_codigo_bueno_traspasa_y_se_gasta():
    fm, h = _fm(_arbol_jose()), _mqtt()
    _llega_codigo(h)
    r = _reclamar(fm, h, {"codigo": CODIGO.upper()})
    assert r == (200, {"ok": True, "traspaso": True}), r
    assert fm.db.datos["ESP32"][MAC]["ownerUid"] == "pedro"
    assert h.gastar_codigo_alta(MAC, CODIGO) == "espera"     # de un solo uso


def test_codigo_malo_o_sin_codigo_no_traspasa():
    fm, h = _fm(_arbol_jose()), _mqtt()
    antes = copy.deepcopy(fm.db.datos)
    _llega_codigo(h)
    h.prueba_fisica[MAC] = time.time()             # aunque este "en la mano" (corte de luz)
    assert _reclamar(fm, h, {"codigo": "f" * 32})[0] == 403
    assert _reclamar(fm, h, {})[0] == 403          # firmware con codigo: sin el, nada
    assert fm.db.datos == antes


def test_codigo_que_aun_no_llego_es_409_para_que_la_app_reintente():
    fm, h = _fm(_arbol_jose()), _mqtt()
    assert _reclamar(fm, h, {"codigo": CODIGO})[0] == 409


def test_codigo_caducado():
    h = _mqtt()
    _llega_codigo(h)
    hsh, _ = h.codigos_alta[MAC]
    h.codigos_alta[MAC] = (hsh, time.time() - 16 * 60)
    assert h.gastar_codigo_alta(MAC, CODIGO) == "malo"


def test_firmware_nuevo_por_telemetria_exige_codigo_y_el_viejo_no():
    h = _mqtt()
    h.last_telemetry[MAC] = SimpleNamespace(fw="2026.11.26")
    assert h.exige_codigo_alta(MAC)
    h.last_telemetry[MAC] = SimpleNamespace(fw="2026.11.24")
    assert not h.exige_codigo_alta(MAC)


def test_firmware_viejo_sigue_con_la_ventana():
    fm, h = _fm(_arbol_jose()), _mqtt()
    h.prueba_fisica[MAC] = time.time()
    assert _reclamar(fm, h, {})[0] == 200


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
