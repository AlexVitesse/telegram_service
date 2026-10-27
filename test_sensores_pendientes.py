#!/usr/bin/env python3
"""
Sensores en cuarentena (firmware de Pedro, 27-oct): pending_authorization se
apunta en Pendientes, avisa al dueño una vez (push + Telegram con botones) y
se autoriza desde la app o desde Telegram.

    python test_sensores_pendientes.py
"""
import logging
import sys
from collections import OrderedDict
from unittest.mock import MagicMock

logging.basicConfig(handlers=[logging.NullHandler()])

import main as m
from mqtt_handler import MqttHandler
from mqtt_protocol import Command, EventType, MqttEvent
from telegram_bot import teclado_autorizar
from test_estado_y_armado import _Evento, _fm

MAC = "08_D1_F9_29_E4"


def _app(nuevo=True):
    app = m.AlarmBridgeService.__new__(m.AlarmBridgeService)
    app.mqtt = MagicMock()
    app.fcm = MagicMock()
    app.telegram = MagicMock()
    app.telegram.is_running.return_value = True
    app._loop = MagicMock()
    enviados = []
    m.asyncio.run_coroutine_threadsafe = lambda coro, loop: enviados.append(coro)
    app.telegram.send_message = lambda chat, msg, *a, **kw: (chat, msg, kw.get("reply_markup"))
    fm = m.firebase_manager
    fm.anotar_pendiente = MagicMock(return_value=nuevo)
    fm.quitar_pendiente = MagicMock()
    fm.get_device_location = lambda d: "Casa"
    fm.get_authorized_chats = lambda d: ["111", "222", "-999"]
    fm.es_dueno = lambda d, c: c == "111"
    return app, enviados


def _pendiente(sensor="MOV-NUEVO1"):
    return MqttEvent(device_id=MAC, event_type="pending_authorization",
                     data={"sensorId": sensor, "sensorType": "MOV"})


def test_sensor_nuevo_avisa_solo_al_dueno_con_botones():
    app, enviados = _app()
    app._handle_event(_pendiente())
    m.firebase_manager.anotar_pendiente.assert_called_once_with(MAC, "MOV-NUEVO1", "MOV")
    assert [e[0] for e in enviados] == ["111"]           # ni el 2.º usuario ni el grupo
    teclado = enviados[0][2]
    datos = [b.callback_data for b in teclado.inline_keyboard[0]]
    assert datos == [f"auth_{MAC}_MOV-NUEVO1", f"authno_{MAC}_MOV-NUEVO1"]
    app.fcm.send_to_device_users.assert_called_once()
    app.telegram.handle_mqtt_event.assert_not_called()   # no va al admin como «técnico»


def test_el_mismo_sensor_no_se_avisa_dos_veces():
    app, enviados = _app(nuevo=False)
    app._handle_event(_pendiente())
    assert enviados == []
    app.fcm.send_to_device_users.assert_not_called()


def test_la_app_pide_autorizar():
    fm = _fm({MAC: {}})
    pedidos = []
    fm.on_autorizar = lambda d, s: pedidos.append((d, s))
    fm._app_command_listener(_Evento(f"/{MAC}/Pendientes/MOV-NUEVO1/autorizar", True))
    fm._app_command_listener(_Evento(f"/{MAC}/Pendientes/MOV-NUEVO2", {"autorizar": True}))
    # Las escrituras del propio VPS (alta y borrado) no piden nada.
    fm._app_command_listener(_Evento(f"/{MAC}/Pendientes/MOV-NUEVO3", {"tipo": "MOV", "desde": 1}))
    fm._app_command_listener(_Evento(f"/{MAC}/Pendientes/MOV-NUEVO3", None))
    assert pedidos == [(MAC, "MOV-NUEVO1"), (MAC, "MOV-NUEVO2")]


def test_pedir_autorizacion_manda_la_orden_aunque_este_caida():
    app, _ = _app()
    app._pedir_autorizacion(MAC, "MOV-NUEVO1")
    app.mqtt.send_command.assert_called_once_with(
        Command.AUTHORIZE_DEVICE.value, {"sensorId": "MOV-NUEVO1"}, device_id=MAC, queue_if_offline=True)


def _handler():
    h = MqttHandler.__new__(MqttHandler)
    h.device_id, h.device_location = MAC, ""
    h.firebase_manager = MagicMock()
    h.firebase_manager.get_device_location.return_value = ""
    h.device_manager = MagicMock()
    h.last_arm_event_time, h.prueba_fisica = {}, {}
    h._ids_vistos, h._arranques_por_confirmar = OrderedDict(), {}
    h._on_event_callback = None
    h._modo_bengala_pedido, h._autorizacion_pedida = {}, {}
    h.on_autorizacion = MagicMock()
    return h


def test_el_ack_dice_que_sensor_era():
    h = _handler()
    h._autorizacion_pedida[MAC] = "MOV-NUEVO1"       # lo apunta send_command
    h._handle_event('{"deviceId": "%s", "eventType": "cmd_ack", "data": {"cmd": "set_schedule", "ok": true}}' % MAC)
    h.on_autorizacion.assert_not_called()             # otro ack no lo consume
    h._handle_event('{"deviceId": "%s", "eventType": "cmd_ack", "data": {"cmd": "authorize_device", "ok": true}}' % MAC)
    h.on_autorizacion.assert_called_once_with(MAC, "MOV-NUEVO1", True)


def test_hecha_quita_el_pendiente_y_avisa():
    app, enviados = _app()
    app._autorizacion_hecha(MAC, "MOV-NUEVO1", True)
    m.firebase_manager.quitar_pendiente.assert_called_once_with(MAC, "MOV-NUEVO1")
    assert enviados[0][0] == "111" and "autorizado" in enviados[0][1]
    app, enviados = _app()
    app._autorizacion_hecha(MAC, "MOV-NUEVO1", False)   # la central lo olvidó
    m.firebase_manager.quitar_pendiente.assert_called_once()
    assert "Apaga y enciende" in enviados[0][1]


def test_callback_cabe_en_telegram():
    for b in teclado_autorizar(MAC, "MOV-ABCDEFGH").inline_keyboard[0]:
        assert len(b.callback_data.encode()) <= 64
        resto = b.callback_data.split("_", 1)[1]
        assert (resto[:14], resto[15:]) == (MAC, "MOV-ABCDEFGH")


if __name__ == "__main__":
    fallos = 0
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            try:
                f(); print(f"  ok  {nombre}")
            except Exception as e:
                fallos += 1; print(f"FALLA {nombre}: {type(e).__name__} {e}")
    print(f"\n{'todas pasan' if not fallos else f'{fallos} fallan'}")
    sys.exit(1 if fallos else 0)
