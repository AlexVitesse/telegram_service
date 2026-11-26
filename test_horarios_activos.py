#!/usr/bin/env python3
"""
#309: /status decia "Horario: Desactivado" con el primer horario de la lista
apagado y otro encendido: auto_schedule_enabled solo mira horarios[0]. El
firmware nuevo manda horarios_activos (toda la lista); el viejo no.

    python test_horarios_activos.py
"""
import json
import sys

from mqtt_protocol import MqttTelemetry

BASE = {"deviceId": "AA", "armed": False, "auto_schedule_enabled": False}


def test_firmware_nuevo_trae_horarios_activos():
    t = MqttTelemetry.from_json(json.dumps({**BASE, "horarios_activos": 2}))
    assert t.horarios_activos == 2 and t.auto_schedule_enabled is False


def test_firmware_viejo_no_lo_trae():
    assert MqttTelemetry.from_json(json.dumps(BASE)).horarios_activos is None


def test_el_status_usa_horarios_activos_si_viene():
    # La misma condicion que _cmd_status/_get_device_status (telegram_bot.py).
    def activo(t):
        n = getattr(t, "horarios_activos", None)
        return n > 0 if n is not None else t.auto_schedule_enabled
    assert activo(MqttTelemetry.from_json(json.dumps({**BASE, "horarios_activos": 1})))
    assert not activo(MqttTelemetry.from_json(json.dumps({**BASE, "horarios_activos": 0})))
    assert not activo(MqttTelemetry.from_json(json.dumps(BASE)))
    assert activo(MqttTelemetry.from_json(json.dumps({**BASE, "auto_schedule_enabled": True})))


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
