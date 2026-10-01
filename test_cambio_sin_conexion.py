#!/usr/bin/env python3
"""
Aviso cuando la central vuelve con otro estado del que tenia al perder la red.

El 30-sep C8_2E_18_26_60 se armo a las 07:00 por su horario sin internet; el
aviso del firmware se perdio y nadie se entero hasta que empezo a pitar.

    python test_cambio_sin_conexion.py
"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import fcm_handler as fcm_mod
import main as main_mod
from scheduler import ScheduleConfig


def _servicio(antes, armado_ahora, horario=None):
    s = main_mod.AlarmBridgeService.__new__(main_mod.AlarmBridgeService)
    s.device_manager = SimpleNamespace(devices_state={"C8": {"is_armed": antes}} if antes is not None else {})
    s.mqtt = SimpleNamespace(last_telemetry={"C8": SimpleNamespace(armed=armado_ahora)})
    s.fcm = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    s.fcm.is_available = lambda: True
    s.fcm.send_to_device_users = MagicMock()
    s._schedule_telegram_broadcast_for_device = MagicMock()
    main_mod.scheduler.configs.pop("C8", None)
    if horario:
        main_mod.scheduler.configs["C8"] = horario
    return s


def test_se_armo_por_horario_sin_red():
    s = _servicio(False, True, ScheduleConfig(enabled=True, on_hour=7, on_minute=0))
    s._avisar_cambio_sin_conexion("C8", "cuarto")
    aviso = s.fcm.send_to_device_users.call_args.args[1]
    assert "se armó mientras estaba sin internet" in aviso.body, aviso.body
    assert "07:00" in aviso.body, aviso.body
    texto = s._schedule_telegram_broadcast_for_device.call_args.args[1]
    assert "cuarto" in texto and "\n\n" in texto, texto


def test_sin_horario_no_inventa_el_motivo():
    s = _servicio(False, True)
    s._avisar_cambio_sin_conexion("C8", "cuarto")
    assert "horario" not in s.fcm.send_to_device_users.call_args.args[1].body


def test_se_desarmo_sin_red():
    s = _servicio(True, False)
    s._avisar_cambio_sin_conexion("C8", "cuarto")
    aviso = s.fcm.send_to_device_users.call_args.args[1]
    assert "desarmó" in aviso.body, aviso.body
    assert aviso.notification_type is fcm_mod.NotificationType.SYSTEM_DISARMED


def test_mismo_estado_no_avisa():
    s = _servicio(True, True)
    s._avisar_cambio_sin_conexion("C8", "cuarto")
    s.fcm.send_to_device_users.assert_not_called()
    s._schedule_telegram_broadcast_for_device.assert_not_called()


def test_estado_previo_desconocido_no_avisa():
    s = _servicio(None, True)
    s._avisar_cambio_sin_conexion("C8", "cuarto")
    s.fcm.send_to_device_users.assert_not_called()


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if nombre.startswith("test_"):
            try:
                fn()
                print(f"  ok  {nombre}")
            except AssertionError as e:
                print(f"  FALLO  {nombre}: {e}")
                fallos += 1
    sys.exit(1 if fallos else 0)
