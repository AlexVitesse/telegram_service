#!/usr/bin/env python3
"""
Lo que vio la linea base de 24 h del modo local (docs/LINEA_BASE_MODO_LOCAL_2026-10-13.md).

  - El firmware manda system_boot en cada reconexion MQTT (L3): no puede
    contar como "la central esta en la mano" ni avisar de un reinicio.
  - Con QoS 1 el mismo evento puede llegar dos veces: un aviso por id.
  - Un evento atrasado (paso sin internet) no cambia el estado y dice su hora.
  - Sin broker el VPS no oye a nadie: no declara a todas "sin conexion".

    python test_eventos_certificados.py
"""
import json
import sys
import time
from unittest.mock import MagicMock

from mqtt_protocol import MqttEvent, TelegramFormatter
from test_cola_pendientes import MAC, _archivo, _handler


def _h():
    h = _handler(_archivo())
    h._on_event_callback = MagicMock()
    return h


def _evento(h, tipo, data=None, **extra):
    h._handle_event(json.dumps({"deviceId": MAC, "eventType": tipo, "data": data or {}, **extra}))


def _telemetria(h, uptime):
    h._handle_telemetry(json.dumps({"deviceId": MAC, "armed": False, "uptime_sec": uptime}))


def test_reconexion_de_firmware_viejo_no_es_arranque():
    h = _h()
    _evento(h, "system_boot")
    assert not h.prueba_fisica and not h._on_event_callback.called, "se decidio antes de la telemetria"
    _telemetria(h, 5561)
    assert not h.prueba_fisica, "una reconexion abrio la ventana para reclamar"
    assert not h._on_event_callback.called, "el admin leeria 'Sistema reiniciado'"


def test_arranque_real_de_firmware_viejo_se_confirma_con_la_telemetria():
    h = _h()
    _evento(h, "system_boot")
    _telemetria(h, 41)
    assert h.prueba_fisica, "el alta por BLE no podria reclamar la central"
    assert h._on_event_callback.call_args.args[0].event_type == "system_boot"


def test_firmware_nuevo_dice_su_uptime_en_el_system_boot():
    h = _h()
    _evento(h, "system_boot", {"uptime_sec": 12})
    assert h.prueba_fisica and h._on_event_callback.called
    h = _h()
    _evento(h, "system_boot", {"uptime_sec": 44259})
    assert not h.prueba_fisica and not h._on_event_callback.called


def test_el_mismo_id_solo_avisa_una_vez():
    h = _h()
    for _ in range(2):
        _evento(h, "alarm_triggered", {"sensorName": "Sala"}, id="a1b2-7")
    assert h._on_event_callback.call_count == 1, h._on_event_callback.call_count
    _evento(h, "alarm_triggered", {"sensorName": "Sala"}, id="a1b2-8")
    assert h._on_event_callback.call_count == 2


def test_firmware_viejo_sin_id_no_se_deduplica():
    h = _h()
    for _ in range(2):
        _evento(h, "system_armed", {"source": "remote"})
    assert h._on_event_callback.call_count == 2


def test_atrasado_no_cambia_el_estado_y_dice_la_hora():
    h = _h()
    ts = int(time.mktime((2026, 10, 14, 4, 47, 0, 0, 0, -1)))
    _evento(h, "alarm_triggered", {"sensorName": "Sala"}, id="x-1", atrasado=True, timestamp=ts)
    assert not h.device_manager.devices_state.get(MAC, {}).get("is_alarming"), "una alarma vieja dejo la central alarmando"
    texto = TelegramFormatter.format_event(h._on_event_callback.call_args.args[0], "Casa")
    assert "04:47" in texto and "sin internet" in texto, texto


def test_atrasado_sin_hora_no_inventa_una():
    ev = MqttEvent(MAC, "alarm_triggered", {}, timestamp=0, atrasado=True)
    assert ev.nota_atrasado() == "Ocurrió mientras la central estaba sin internet."
    assert MqttEvent(MAC, "alarm_triggered", {}).nota_atrasado() == ""


def test_al_volver_el_broker_no_se_declara_a_todas_sin_conexion():
    h = _h()
    _telemetria(h, 100)
    h.device_manager.devices_state[MAC]["last_telemetry_time"] -= 600  # 10 min sin broker
    h.device_manager.dar_gracia_offline()
    assert h.device_manager.check_offline_devices(timeout_seconds=90) == []


def test_al_reconectar_se_sabe_desde_cuando_estaba_fuera():
    h = _h()
    _telemetria(h, 100)
    dm = h.device_manager
    dm.devices_state[MAC]["last_telemetry_time"] -= 1080
    antes = dm.devices_state[MAC]["last_telemetry_time"]
    assert dm.check_offline_devices(timeout_seconds=90)
    assert dm.update_telemetry_time(MAC) is True
    assert dm.devices_state[MAC]["offline_desde"] == antes


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
