#!/usr/bin/env python3
"""
Testamento (LWT) y telemetria cada 2 min (firmware desde el 23-oct).

La caida la avisa el broker en ~30 s; la falta de telemetria queda de respaldo
(2 x tele_s + 30). El firmware anterior (sin tele_s) sigue con los 90 s.

    python test_testamento.py
"""
import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

logging.basicConfig(handlers=[logging.NullHandler()])

import main as main_mod
from device_manager import DeviceManager


def _dm(tele_s, hace):
    dm = DeviceManager()
    dm.update_telemetry_time("A1", tele_s)
    dm.devices_state["A1"]["last_telemetry_time"] = time.time() - hace
    return dm


def test_firmware_viejo_sigue_con_90_s():
    assert _dm(None, 91).check_offline_devices(90)
    assert not _dm(None, 60).check_offline_devices(90)


def test_telemetria_cada_2_min_no_la_da_por_caida():
    assert not _dm(120, 200).check_offline_devices(90)   # entre dos telemetrias
    assert _dm(120, 271).check_offline_devices(90)       # respaldo sin testamento


def test_testamento_la_da_por_caida_tras_la_gracia():
    dm = _dm(120, 5)
    dm.marcar_desconectada("A1")
    assert not dm.check_offline_devices(90)
    dm.devices_state["A1"]["desconectada"] -= dm.GRACIA_TESTAMENTO_S
    assert dm.check_offline_devices(90)
    assert not dm.vivas_con_testamento()


def test_telemetria_despues_del_testamento_la_reconecta():
    dm = _dm(120, 5)
    dm.marcar_desconectada("A1")
    dm.devices_state["A1"]["desconectada"] -= dm.GRACIA_TESTAMENTO_S
    dm.check_offline_devices(90)
    assert dm.update_telemetry_time("A1", 120) is True
    assert dm.vivas_con_testamento() == ["A1"]


def test_testamento_de_desconocida_no_crea_fantasma():
    dm = DeviceManager()
    dm.marcar_desconectada("ZZ")
    assert "ZZ" not in dm.devices_state


def test_refresco_solo_de_equipos_que_existen():
    s = main_mod.AlarmBridgeService.__new__(main_mod.AlarmBridgeService)
    s.device_manager = _dm(120, 5)
    s.device_manager.update_telemetry_time("B2", 120)
    s.device_manager.update_telemetry_time("VIEJA", None)   # sin testamento: no se toca
    main_mod.firebase_manager._get_all_devices = lambda: {"A1": {}, "VIEJA": {}}
    main_mod.firebase_manager.update_data = MagicMock()
    s._refrescar_en_linea()
    rutas = [c.args[0] for c in main_mod.firebase_manager.update_data.call_args_list]
    assert rutas == ["ESP32/A1/Telemetry"], rutas



def test_testamento_junto_con_la_reconexion_no_avisa():
    dm = _dm(120, 5)
    dm.marcar_desconectada("A1")
    dm.update_telemetry_time("A1", 120)
    dm.devices_state["A1"]["last_telemetry_time"] = time.time()
    assert not dm.check_offline_devices(90)
    assert dm.vivas_con_testamento() == ["A1"]


def test_testamento_despierta_al_monitor():
    from mqtt_handler import MqttHandler
    h = MqttHandler.__new__(MqttHandler)
    h.device_manager = _dm(120, 5)
    h.on_desconexion = MagicMock()
    h._on_message(None, None, SimpleNamespace(
        topic="dispositivos/desconexion", payload=b'{"deviceId": "A1"}'))
    assert h.device_manager.devices_state["A1"]["desconectada"]
    h.on_desconexion.assert_called_once()


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
            print("ok", nombre)
