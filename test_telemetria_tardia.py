#!/usr/bin/env python3
"""
#309: una telemetria hecha DURANTE la cuenta de salida (armed=false a
proposito) que llega tarde no puede desarmar a ojos del VPS.

25-nov, LORA Test: armado 16:30:09, fin de la cuenta 16:31:12, y a las 16:32:21
Telemetry.armed=false. El 26-nov se midio en el banco: la central publico a
las 16:08:41 y el VPS lo escribio a las 16:09:18 (37 s tarde). Pasado el margen
(tiempo de salida + 5 s, medido con la hora del VPS) esa telemetria vieja
llamaba a set_armed_state(False), que escribe Estado.

    python test_telemetria_tardia.py
"""
import json
import sys
import time
from collections import OrderedDict
from unittest.mock import MagicMock

from mqtt_handler import MqttHandler

MAC = "AC_15_18_D5_2D"


def _handler():
    h = MqttHandler.__new__(MqttHandler)
    h.device_id = MAC
    h.device_location = ""
    h.firebase_manager = MagicMock()
    h.firebase_manager._get_all_devices.return_value = {MAC: {}}
    h.device_manager = MagicMock()
    h.device_manager.update_telemetry_time.return_value = False
    h.device_manager.devices_state = {}
    h.last_arm_event_time, h.last_arm_event_ts = {}, {}
    h.last_telemetry, h.last_telemetry_time = {}, {}
    h.device_exit_time = {}
    h.prueba_fisica = {}
    h._ids_vistos, h._arranques_por_confirmar = OrderedDict(), {}
    h._on_event_callback = h._on_telemetry_callback = None
    h.process_pending_commands = MagicMock()
    h._confirmar_arranque = MagicMock()
    h.LORA_EDAD_SOSPECHOSA = 10**9
    return h


def _telemetria(h, ts, armed):
    h._handle_telemetry(json.dumps({"deviceId": MAC, "timestamp": ts, "armed": armed, "tiempo_bomba": 60}))


def _escrito(h):
    return h.firebase_manager.update_data.call_args.args[1]


def test_la_de_la_cuenta_de_salida_que_llega_tarde_no_desarma():
    h = _handler()
    fin_cuenta = int(time.time()) - 120          # system_armed del fin de la cuenta
    h.last_arm_event_ts[MAC] = fin_cuenta
    h.last_arm_event_time[MAC] = time.time() - 120   # ya pasado el margen por hora del VPS
    _telemetria(h, fin_cuenta - 30, False)       # hecha en la cuenta, llega ahora
    h.device_manager.set_armed_state.assert_not_called()
    assert "armed" not in _escrito(h), _escrito(h)


def test_la_de_despues_si_cuenta():
    h = _handler()
    fin_cuenta = int(time.time()) - 120
    h.last_arm_event_ts[MAC] = fin_cuenta
    h.last_arm_event_time[MAC] = time.time() - 120
    _telemetria(h, fin_cuenta + 90, True)
    h.device_manager.set_armed_state.assert_called_once_with(MAC, True)
    assert _escrito(h)["armed"] is True


def test_sin_hora_en_la_central_se_queda_como_antes():
    h = _handler()
    h.last_arm_event_ts[MAC] = time.time()
    h.last_arm_event_time[MAC] = time.time() - 120
    _telemetria(h, 0, False)                     # sin NTP: solo manda el margen del VPS
    h.device_manager.set_armed_state.assert_called_once_with(MAC, False)


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
