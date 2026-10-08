#!/usr/bin/env python3
"""
Fase 3 (servidor): lo que necesita el firmware nuevo de la central.

  - "Disparar bengala" va marcado como respuesta (el SOS ya no la dispara en
    modo pregunta).
  - cmd_ack solo al log.
  - Central borrada: "olvidar" solo si esta conectada, nunca encolado.
  - El horario de la telemetria se compara con el de la nube y se reenvia.

    python test_fase3.py
"""
import sys
import time
from unittest.mock import MagicMock

from mqtt_handler import MqttHandler
from mqtt_protocol import Command, MqttEvent, MqttTelemetry
from test_retro_banco import MAC, _arbol_jose, _fm, _horarios_aislados


def _telem(**kw):
    base = dict(device_id=MAC + "_B2", timestamp=0, armed=False, alarm_active=False,
                bengala_enabled=False, bengala_mode=1, wifi_rssi=0, heap_free=0,
                uptime_sec=0, lora_sensors_active=0, auto_schedule_enabled=True)
    base.update(kw)
    return MqttTelemetry(**base)


def _con_horario(fn):
    def caso(sch):
        sch.scheduler.configs[MAC] = sch.ScheduleConfig(
            enabled=True, on_hour=22, on_minute=0, off_hour=7, off_minute=0)
        fm = _fm(_arbol_jose())
        fn(fm)
    _horarios_aislados(caso)


def test_bengala_confirmada_va_marcada():
    h = MqttHandler.__new__(MqttHandler)
    h.send_command = MagicMock(return_value=True)
    h.send_trigger_bengala(device_id=MAC)
    ultimo = h.send_command.call_args_list[-1]
    assert ultimo.args[:2] == (Command.TRIGGER_ALARM.value, {"confirm": True}), ultimo


def test_cmd_ack_no_llega_a_nadie():
    h = MqttHandler.__new__(MqttHandler)
    h.device_id = MAC
    h.device_location = ""
    h.firebase_manager = MagicMock()
    h.firebase_manager.get_device_location.return_value = ""
    h.device_manager = MagicMock()
    h.last_arm_event_time = {}
    h.prueba_fisica = {}
    h._on_event_callback = MagicMock()
    ev = '{"deviceId": "%s", "eventType": "cmd_ack", "data": {"cmd": "set_schedule", "ok": false}}' % MAC
    h._handle_event(ev)
    h._on_event_callback.assert_not_called()


def test_horario_igual_no_se_reenvia():
    def f(fm):
        fm.revisar_horario(_telem(sched_on=22 * 60, sched_off=7 * 60, sched_days=0x7F))
        fm.mqtt_handler.send_set_schedule.assert_not_called()
    _con_horario(f)


def test_horario_distinto_se_reenvia_una_vez_cada_10_min():
    def f(fm):
        t = _telem(sched_on=20 * 60, sched_off=7 * 60, sched_days=0x7F)
        fm.revisar_horario(t)
        fm.revisar_horario(t)
        assert fm.mqtt_handler.send_set_schedule.call_count == 1
        kw = fm.mqtt_handler.send_set_schedule.call_args.kwargs
        assert kw["on_hour"] == 22 and kw["enabled"] is True, kw
    _con_horario(f)


def test_dias_distintos_se_reenvia():
    def f(fm):
        fm.revisar_horario(_telem(sched_on=22 * 60, sched_off=7 * 60, sched_days=0x3E))
        assert fm.mqtt_handler.send_set_schedule.call_count == 1
    _con_horario(f)


def test_firmware_viejo_sin_horario_en_telemetria_no_se_toca():
    def f(fm):
        fm.revisar_horario(_telem(auto_schedule_enabled=False))
        fm.mqtt_handler.send_set_schedule.assert_not_called()
    _con_horario(f)


def test_horario_apagado_en_la_nube_y_activo_en_la_central():
    def caso(sch):
        sch.scheduler.configs[MAC] = sch.ScheduleConfig(enabled=False)
        fm = _fm(_arbol_jose())
        fm.revisar_horario(_telem(sched_on=0, sched_off=0, sched_days=0x7F))
        kw = fm.mqtt_handler.send_set_schedule.call_args.kwargs
        assert kw["enabled"] is False, kw
    _horarios_aislados(caso)


def test_borrar_conectada_la_manda_olvidar():
    fm = _fm(_arbol_jose())
    fm.mqtt_handler.is_device_online.return_value = True
    assert fm.borrar_equipo("jose", MAC) == "ok"
    fm.mqtt_handler.send_command.assert_called_once_with(Command.FORGET.value, device_id=MAC)


def test_borrar_offline_no_encola_olvidar():
    """Si se encolara, le llegaria despues de volver a darla de alta."""
    fm = _fm(_arbol_jose())
    fm.mqtt_handler.is_device_online.return_value = False
    assert fm.borrar_equipo("jose", MAC) == "ok"
    fm.mqtt_handler.send_command.assert_not_called()


def test_central_borrada_que_arranca_olvida():
    def caso(sch):
        fm = _fm(_arbol_jose())
        fm.mqtt_handler.is_device_online.return_value = True
        fm.enviar_horario("AB_CD_EF_01_23_45")
        fm.mqtt_handler.send_command.assert_called_once_with(
            Command.FORGET.value, device_id="AB_CD_EF_01_23_45")
    _horarios_aislados(caso)


def test_central_borrada_olvida_al_arrancar_sin_telemetria_previa():
    """El system_boot llega antes que la primera telemetria: offline segun el handler."""
    def caso(sch):
        fm = _fm(_arbol_jose())
        fm.mqtt_handler.is_device_online.return_value = False
        fm.enviar_horario("AB_CD_EF_01_23_45", arrancando=True)
        fm.mqtt_handler.send_command.assert_called_once_with(
            Command.FORGET.value, device_id="AB_CD_EF_01_23_45")
    _horarios_aislados(caso)


def test_system_boot_pide_el_horario_como_arranque():
    h = MqttHandler.__new__(MqttHandler)
    h.device_id = MAC
    h.device_location = ""
    h.firebase_manager = MagicMock()
    h.firebase_manager.get_device_location.return_value = ""
    h.device_manager = MagicMock()
    h.last_arm_event_time = {}
    h.prueba_fisica = {}
    h._on_event_callback = None
    h.process_pending_commands = MagicMock()
    h._handle_event('{"deviceId": "%s", "eventType": "system_boot", "data": {}}' % MAC)
    h.firebase_manager.enviar_horario.assert_called_once_with(MAC, arrancando=True)


def test_central_con_nodo_no_olvida():
    def f(fm):
        fm.mqtt_handler.is_device_online.return_value = True
        fm.enviar_horario(MAC + "_B2")
        fm.mqtt_handler.send_command.assert_not_called()
    _con_horario(f)


def test_telemetria_lee_el_horario():
    t = MqttTelemetry.from_json('{"deviceId": "X", "sched_on": 1200, "sched_off": 420, "sched_days": 127}')
    assert (t.sched_on, t.sched_off, t.sched_days) == (1200, 420, 127)
    assert MqttTelemetry.from_json('{"deviceId": "X"}').sched_on is None


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
