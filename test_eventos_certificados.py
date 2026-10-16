#!/usr/bin/env python3
"""
Lo que vio la linea base de 24 h del modo local (docs/LINEA_BASE_MODO_LOCAL_2026-10-13.md).

  - El firmware manda system_boot en cada reconexion MQTT (L3): no puede
    contar como "la central esta en la mano" ni avisar de un reinicio.
  - Con QoS 1 el mismo evento puede llegar dos veces: un aviso por id.
  - Un evento atrasado (paso sin internet) no cambia el estado y dice su hora.
  - Sin broker el VPS no oye a nadie: no declara a todas "sin conexion".
  - Varias centrales calladas a la vez = el broker va mal: no se culpa al
    internet de cada casa (caida del 14-oct, docs/PLAN_EVENTOS_CERTIFICADOS §10.5).

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


def _central_callada(dm, mac, hace_seg):
    """Una central que mando su ultima telemetria hace `hace_seg` segundos."""
    dm.devices_state[mac] = {"id": mac, "is_online": True, "offline_notified": False,
                             "last_telemetry_time": time.time() - hace_seg}


def test_una_central_callada_no_es_caida_masiva():
    dm = _h().device_manager
    dm.devices_state.clear()
    _central_callada(dm, "08_D1_F9_29_E4", 100)
    _central_callada(dm, "C8_2E_18_26_60", 10)   # esta sigue hablando
    dm.check_offline_devices(timeout_seconds=90)
    assert dm.calladas_a_la_vez() == ["08_D1_F9_29_E4"]


def test_dos_calladas_en_la_ventana_son_caida_masiva():
    # 14-oct: 08_D1 a las 04:44 y C8_2E_18_26_60 a las 04:46.
    dm = _h().device_manager
    dm.devices_state.clear()
    _central_callada(dm, "08_D1_F9_29_E4", 250)
    _central_callada(dm, "C8_2E_18_26_60", 100)
    dm.check_offline_devices(timeout_seconds=90)
    assert len(dm.calladas_a_la_vez()) == 2


def test_una_central_muerta_hace_horas_no_cuenta():
    # Si no, una central desenchufada una semana haria "masiva" a cualquier otra.
    dm = _h().device_manager
    dm.devices_state.clear()
    _central_callada(dm, "C8_2E_18_25_CA", 86400)
    _central_callada(dm, "A0_A3_B3_2F_A2", 100)
    dm.check_offline_devices(timeout_seconds=90)
    assert dm.calladas_a_la_vez() == ["A0_A3_B3_2F_A2"]


def test_la_retenida_sigue_contando_si_la_caida_dura_mas_que_la_ventana():
    # La del 14-oct duro 18 min, mas que la ventana de 10.
    dm = _h().device_manager
    dm.devices_state.clear()
    _central_callada(dm, "08_D1_F9_29_E4", 1100)
    _central_callada(dm, "A0_A3_B3_2F_A2", 100)
    dm.check_offline_devices(timeout_seconds=90)
    assert dm.calladas_a_la_vez() == ["A0_A3_B3_2F_A2"]
    dm.devices_state["08_D1_F9_29_E4"]["aviso_retenido"] = True
    assert len(dm.calladas_a_la_vez()) == 2


def test_central_sin_hora_manda_la_edad_y_el_vps_la_calcula():
    """Reiniciada sin internet y aun sin NTP: timestamp 0 + edad_s (15-oct)."""
    e = MqttEvent.from_json(json.dumps({
        "deviceId": "D1", "eventType": "system_armed", "timestamp": 0,
        "edad_s": 600, "atrasado": True, "data": {}}))
    assert abs(e.timestamp - (int(time.time()) - 600)) <= 2, e.timestamp
    assert "Ocurrió a las" in e.nota_atrasado()
    # Firmware viejo: ni edad_s ni hora; no se inventa una.
    viejo = MqttEvent.from_json(json.dumps({
        "deviceId": "D1", "eventType": "system_armed", "timestamp": 35,
        "atrasado": True, "data": {}}))
    assert viejo.timestamp == 35
    assert viejo.nota_atrasado() == "Ocurrió mientras la central estaba sin internet."


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
