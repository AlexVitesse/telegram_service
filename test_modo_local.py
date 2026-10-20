#!/usr/bin/env python3
"""
Modo local (Fase 3): el servidor guarda lo que la app necesita para hablar con
la central sin internet.

  - local_creds va a ESP32/<id>/Local, sin avisar a nadie ni loguear secretos.
  - Incompletas o de una central sin alta: se ignoran.
  - La IP de la telemetria llega a la app.
  - Traspaso: la central cambia su llave (local_rotate).

    python test_modo_local.py
"""
import json
import logging
import sys
from collections import OrderedDict
from unittest.mock import MagicMock

from mqtt_handler import MqttHandler
from mqtt_protocol import MqttTelemetry

MAC = "08_D1_F9_29_E4"
LLAVE = "ab" * 32


def _handler(dispositivos=(MAC,)):
    h = MqttHandler.__new__(MqttHandler)
    h.device_id = MAC
    h.device_location = ""
    h.firebase_manager = MagicMock()
    h.firebase_manager._get_all_devices.return_value = {d: {} for d in dispositivos}
    h.firebase_manager.get_device_location.return_value = ""
    h.device_manager = MagicMock()
    h.last_arm_event_time = {}
    h.prueba_fisica = {}
    h._ids_vistos, h._arranques_por_confirmar = OrderedDict(), {}
    h._on_event_callback = MagicMock()
    return h


def _creds(**data):
    base = {"ssid": "Sentinel-29E4", "pass": "abcdefgh2345", "key": LLAVE, "port": 8080}
    base.update(data)
    return json.dumps({"deviceId": MAC, "eventType": "local_creds", "id": "1-1", "data": base})


class _Captura(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.textos = []

    def emit(self, r):
        self.textos.append(r.getMessage())


def test_creds_se_guardan_sin_avisar_ni_loguear():
    h = _handler()
    cap = _Captura()
    raiz = logging.getLogger()
    nivel = raiz.level
    raiz.addHandler(cap)
    raiz.setLevel(logging.DEBUG)
    try:
        h._handle_event(_creds())
    finally:
        raiz.removeHandler(cap)
        raiz.setLevel(nivel)
    h.firebase_manager.update_data.assert_called_once()
    ruta, datos = h.firebase_manager.update_data.call_args.args
    assert ruta == f"ESP32/{MAC}/Local", ruta
    assert datos["key"] == LLAVE and datos["pass"] == "abcdefgh2345" and datos["port"] == 8080, datos
    h._on_event_callback.assert_not_called()
    filtrado = [t for t in cap.textos if LLAVE in t or "abcdefgh2345" in t]
    assert not filtrado, filtrado


def test_creds_incompletas_se_ignoran():
    h = _handler()
    h._handle_event(_creds(key="corta"))
    h._handle_event(_creds(**{"pass": ""}))
    h.firebase_manager.update_data.assert_not_called()
    h._on_event_callback.assert_not_called()


def test_creds_de_central_sin_alta_no_crean_el_nodo():
    h = _handler(dispositivos=())
    h._handle_event(_creds())
    h.firebase_manager.update_data.assert_not_called()


def test_ip_de_la_telemetria_llega_a_la_app():
    h = _handler()
    t = MqttTelemetry.from_json(json.dumps({"deviceId": MAC, "ip": "192.168.1.50", "fw": "2026.10.20"}))
    assert t.ip == "192.168.1.50"
    h._save_telemetry_to_firebase(t)
    ruta, datos = h.firebase_manager.update_data.call_args.args
    assert ruta == f"ESP32/{MAC}/Telemetry" and datos["ip"] == "192.168.1.50", (ruta, datos)


def test_telemetria_sin_ip_no_la_borra():
    h = _handler()
    h._save_telemetry_to_firebase(MqttTelemetry.from_json(json.dumps({"deviceId": MAC})))
    _, datos = h.firebase_manager.update_data.call_args.args
    assert "ip" not in datos, datos


def test_traspaso_pide_llave_nueva():
    import asyncio, time
    from types import SimpleNamespace
    from test_api_server import con_api, pedir
    from test_retro_banco import MAC as MAC_BANCO, _arbol_jose, _fm
    from mqtt_protocol import Command
    fm = _fm(_arbol_jose())
    enviados = []
    mqtt = SimpleNamespace(prueba_fisica={MAC_BANCO: time.time()},
                           send_command=lambda *a, **kw: enviados.append((a, kw)) or True)

    async def p(url, api):
        api._bot.mqtt_handler = mqtt
        r = await pedir(url, token="bueno", cuerpo={"mac": MAC_BANCO, "nombre": "casa"}, ruta="/equipos/reclamar")
        assert r[0] == 200 and r[1]["traspaso"] is True, r
    asyncio.run(con_api(fm, "pedro", p))
    assert enviados == [((Command.LOCAL_ROTATE.value,), {"device_id": MAC_BANCO, "queue_if_offline": True})], enviados


def _correr():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            print(f"  FALLO  {fn.__name__}: {e}")
            fallos += 1
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if _correr() else 0)
