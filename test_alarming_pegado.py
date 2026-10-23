#!/usr/bin/env python3
"""
`Alarming` pegado en true (22-oct 17:12, 08_D1_F9_29_E4): el reinicio por
offline tocaba solo la memoria y despues nadie escribia false, porque solo se
escribia si cambiaba la memoria. La app mostraba "Alerta en curso" al abrirse.

    python test_alarming_pegado.py
"""
import json
import logging
from unittest.mock import MagicMock

logging.basicConfig(handlers=[logging.NullHandler()])

from device_manager import DeviceManager
from mqtt_protocol import MqttTelemetry


def _dm():
    fm = MagicMock()
    fm.get_bengala_mode_from_firebase.return_value = None
    return DeviceManager(fm), fm


def test_false_con_la_memoria_ya_en_false_igual_se_sincroniza():
    dm, fm = _dm()
    dm.set_alarming_state("08_D1", False)  # memoria ya false, base quiza true
    fm.update_device_state_in_firebase.assert_called_with("08_D1", {"is_alarming": False})


def test_reinicio_offline_y_luego_desarme_limpia_la_base():
    dm, fm = _dm()
    dm.set_alarming_state("08_D1", True)
    dm.devices_state["08_D1"]["is_online"] = False
    dm.get_alarming_devices()  # el reinicio por offline: solo memoria
    fm.reset_mock()
    dm.set_alarming_state("08_D1", False)  # desarme o telemetria con sirena apagada
    fm.update_device_state_in_firebase.assert_called_once_with("08_D1", {"is_alarming": False})


def test_sirena_solo_del_firmware_que_la_manda():
    viejo = MqttTelemetry.from_json(json.dumps({"deviceId": "A", "alarm_active": False}))
    nuevo = MqttTelemetry.from_json(json.dumps({"deviceId": "A", "alarm_active": True, "sirena": True}))
    assert viejo.sirena is None   # alarm_active iba fijo en false: no se usa
    assert nuevo.sirena is True


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
