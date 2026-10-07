#!/usr/bin/env python3
"""
Botones de los avisos de alarma: cada uno actua sobre SU central.

El fallo que vigila: "Disparar bengala" / "Dejar armado" llevaban un
callback_data sin central ("bengala_confirm") y el handler actuaba sobre
TODAS las centrales del usuario que estuviesen sonando. Con dos alarmas a la
vez, el boton de un aviso disparaba la bengala de las dos.

    python test_botones_alarma.py
"""
import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.CRITICAL)

from device_manager import DeviceManager
from firebase_manager import FirebaseManager
from telegram_bot import BengalaConfirmation, TelegramBot, teclado_alarma
from test_lead_capture import _make_mock_query

A = "6C_C8_40_4F_C7"
B = "C8_2E_18_25_CA"
CHAT = "111"


def _bot(sonando=(), devices=(A, B)):
    fm = MagicMock()
    fm.get_authorized_devices = MagicMock(return_value=list(devices))
    fm.get_authorized_chats = MagicMock(return_value=[CHAT])
    fm.get_device_location = MagicMock(side_effect=lambda d: f"casa-{d[:2]}")
    real = FirebaseManager.__new__(FirebaseManager)
    real._get_all_devices = lambda: {d: {} for d in devices}
    fm.resolver_equipo = real.resolver_equipo

    dm = DeviceManager(None)
    for d in sonando:
        dm.devices_state[d + "_B2"] = {"is_alarming": True}  # MQTT guarda el id largo

    mqtt = MagicMock()
    mqtt.resolve_full_device_id = lambda d: next(
        (k for k in dm.devices_state if k.startswith(d)), d)

    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager = fm
    bot.device_manager = dm
    bot.mqtt_handler = mqtt
    bot.send_message = AsyncMock()
    bot._bengala_confirmations = {}
    bot._alarm_notifications = {}
    bot._disarm_devices = AsyncMock()
    return bot


def _pulsar(bot, data):
    q = _make_mock_query(CHAT)
    q.data = data
    asyncio.run(bot._handle_callback(SimpleNamespace(callback_query=q), None))
    return q


def _disparadas(bot):
    return [c.kwargs["device_id"] for c in bot.mqtt_handler.send_trigger_bengala.call_args_list]


def test_disparar_bengala_solo_en_la_central_del_aviso():
    bot = _bot(sonando=(A, B))
    _pulsar(bot, f"bengala_confirm_{B}")
    assert _disparadas(bot) == [B], _disparadas(bot)


def test_dejar_armado_solo_para_esa_central_y_sin_entradas_fantasma():
    bot = _bot(sonando=(A, B))
    bot._bengala_confirmations[A + "_B2"] = BengalaConfirmation(A + "_B2", [CHAT], "s", "l", 0)
    antes = set(bot.device_manager.devices_state)

    _pulsar(bot, f"bengala_cancel_{A}")

    parados = [c.kwargs["device_id"] for c in bot.mqtt_handler.send_stop_alarm.call_args_list]
    assert parados == [A], parados
    assert set(bot.device_manager.devices_state) == antes, "se creo una entrada fantasma"
    assert not bot.device_manager.is_alarming(A)
    assert bot.device_manager.is_alarming(B), "la otra central tenia que seguir sonando"
    assert not bot._bengala_confirmations, "la confirmacion (guardada con el id largo) seguia viva"


def test_central_que_ya_no_suena_no_dispara():
    bot = _bot(sonando=(A,))
    q = _pulsar(bot, f"bengala_confirm_{B}")
    assert _disparadas(bot) == []
    assert "ya no está activa" in q.edit_message_text.call_args.args[0]


def test_central_ajena_no_dispara():
    bot = _bot(sonando=(A,), devices=(A,))
    q = _pulsar(bot, f"bengala_confirm_{B}")
    assert _disparadas(bot) == []
    assert "No tienes acceso" in q.edit_message_text.call_args.args[0]


def test_boton_antiguo_con_una_alarma_actua_sobre_ella():
    bot = _bot(sonando=(A,))
    _pulsar(bot, "bengala_confirm")
    assert _disparadas(bot) == [A]


def test_boton_antiguo_con_dos_alarmas_pregunta_y_no_dispara():
    bot = _bot(sonando=(A, B))
    q = _pulsar(bot, "bengala_confirm")
    assert _disparadas(bot) == []
    teclado = q.edit_message_text.call_args.kwargs["reply_markup"]
    datos = {b.callback_data for fila in teclado.inline_keyboard for b in fila}
    assert datos == {f"bengala_confirm_{A}", f"bengala_confirm_{B}"}, datos


def test_desarmar_acepta_la_mac_larga_y_rechaza_la_ajena():
    bot = _bot()
    _pulsar(bot, f"disarm_{A}_B2")
    assert bot._disarm_devices.call_args.args[1] == [A]

    bot = _bot(devices=(A,))
    q = _pulsar(bot, f"disarm_{B}")
    bot._disarm_devices.assert_not_called()
    assert "No tienes acceso" in q.edit_message_text.call_args.args[0]


def test_desarmar_todos_sigue_desarmando_todas():
    """Lo usa "Desarmar TODOS" de /off."""
    bot = _bot()
    _pulsar(bot, "disarm_all")
    assert bot._disarm_devices.call_args.args[1] == [A, B]


def test_teclado_atado_a_la_central_y_dentro_del_limite():
    for con_bengala, con_dejar in ((True, True), (False, True), (False, False)):
        t = teclado_alarma(A + "_B2", con_bengala, con_dejar)
        datos = [b.callback_data for fila in t.inline_keyboard for b in fila]
        assert all(d.endswith(A) for d in datos), datos
        assert all(len(d.encode()) <= 64 for d in datos)
        assert ("bengala_confirm_" + A in datos) == con_bengala
        assert ("bengala_cancel_" + A in datos) == con_dejar
        assert "disarm_all" not in datos



def test_dos_centrales_que_casan_con_la_misma_mac_no_se_elige_ninguna():
    """Si la MAC del boton encaja con dos centrales, no se dispara en ninguna."""
    bot = _bot(sonando=(A,), devices=(A, A + "_7"))
    q = _pulsar(bot, f"bengala_confirm_{A}_B2")
    assert _disparadas(bot) == []
    assert "No tienes acceso" in q.edit_message_text.call_args.args[0]


def test_clave_legacy_de_16_resuelve_desde_la_mac_completa():
    legacy = "AC_15_18_D4_47_4"
    bot = _bot(devices=(legacy,))
    _pulsar(bot, "disarm_AC_15_18_D4_47_4F")
    assert bot._disarm_devices.call_args.args[1] == [legacy]


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
