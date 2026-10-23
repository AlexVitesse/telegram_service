#!/usr/bin/env python3
"""
Horario sobre una central que ya estaba caida al arrancar el servidor.

23-oct: C8_2E_18_26_60 llevaba 7 dias sin telemetria; tras el reinicio del
20-oct el servidor no la conocia, nunca la dio por caida y el horario le
mandaba arm/disarm (y el recordatorio "se activara") a diario.

    python test_horario_central_caida.py
"""
import asyncio
import logging
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

logging.basicConfig(handlers=[logging.NullHandler()])

import main as main_mod
from device_manager import DeviceManager
from scheduler import ScheduleConfig


def _servicio(telemetria):
    s = main_mod.AlarmBridgeService.__new__(main_mod.AlarmBridgeService)
    s.device_manager = DeviceManager()
    s.mqtt = SimpleNamespace(send_arm=MagicMock(), send_disarm=MagicMock())
    s._pending_scheduled = {}
    s._loop = None
    s.telegram = SimpleNamespace(is_running=lambda: False)
    main_mod.scheduler.configs.clear()
    main_mod.scheduler.configs["C8"] = ScheduleConfig(enabled=True, on_hour=10, on_minute=0)
    main_mod.firebase_manager._get_all_devices = lambda: {"C8": {"Telemetry": telemetria}}
    s._sembrar_centrales_caidas()
    return s


def test_caida_de_dias_no_recibe_comandos():
    hace_7_dias = int(time.time()) - 7 * 86400
    s = _servicio({"timestamp": hace_7_dias, "armed": True})
    d = s.device_manager.devices_state["C8"]
    assert d["offline_notified"] and not d["is_online"] and d["is_armed"], d
    # Ya estaba avisada: el monitor no repite "sin conexion".
    assert s.device_manager.check_offline_devices() == []
    asyncio.run(s._scheduled_arm("C8"))
    asyncio.run(s._scheduled_disarm("C8"))
    s.mqtt.send_arm.assert_not_called()
    s.mqtt.send_disarm.assert_not_called()
    # Al volver avisa la reconexion y el comando vuelve a salir.
    assert s.device_manager.update_telemetry_time("C8") is True
    asyncio.run(s._scheduled_disarm("C8"))
    s.mqtt.send_disarm.assert_called_once_with("C8")


def test_recien_callada_no_se_siembra():
    s = _servicio({"timestamp": int(time.time()) - 30, "armed": False})
    assert "C8" not in s.device_manager.devices_state


def test_callada_un_momento_si_recibe_el_comando():
    # 2 min callada (ya avisada): ante la duda se manda igual.
    s = _servicio({"timestamp": int(time.time()) - 120, "armed": False})
    asyncio.run(s._scheduled_arm("C8"))
    s.mqtt.send_arm.assert_called_once_with("C8")


def test_horario_que_llega_despues_del_arranque_tambien_se_siembra():
    # 23-oct: el horario de 6C_C8_40_4F_C7 llego de Firebase 2 s despues
    # de la siembra del arranque y la central seguia recibiendo comandos.
    s = _servicio({"timestamp": int(time.time()) - 13 * 86400, "armed": False})
    s.device_manager.devices_state.clear()
    asyncio.run(s._scheduled_arm("C8"))
    s.mqtt.send_arm.assert_not_called()
    assert s.device_manager.devices_state["C8"]["offline_notified"]


def test_recordatorio_avisa_caida_una_vez_al_dia():
    s = _servicio({"timestamp": int(time.time()) - 3 * 86400, "armed": False})
    s._loop = object()
    s.telegram = SimpleNamespace(is_running=lambda: True, send_message=MagicMock())
    s._get_authorized_chats = lambda _id: ["111"]
    main_mod.firebase_manager.get_device_location = lambda _id: "Casa"
    main_mod.firebase_manager.quiere_aviso_telegram = lambda chat, familia: familia == "conexion"
    enviados = []
    with patch.object(main_mod.asyncio, "run_coroutine_threadsafe", lambda coro, loop: enviados.append(1)):
        asyncio.run(s._scheduled_reminder("C8", "on", 5))
        asyncio.run(s._scheduled_reminder("C8", "off", 5))
    assert len(enviados) == 1, enviados
    texto = s.telegram.send_message.call_args.args[1]
    assert "SIN CONEXIÓN" in texto and "10:00" in texto, texto


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in list(globals().items()):
        if nombre.startswith("test_"):
            try:
                fn()
                print(f"ok   {nombre}")
            except Exception as e:
                fallos += 1
                print(f"FALLA {nombre}: {e!r}")
    sys.exit(1 if fallos else 0)
