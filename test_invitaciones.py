#!/usr/bin/env python3
"""
Invitaciones por Telegram: /adduser, /join_ y /approve_ solo con el dueno.

Los fallos que vigila:
  - /adduser armaba el codigo con mqtt_handler.device_id: la PRIMERA central
    que reporto desde el arranque, de cualquier cliente. La invitacion podia
    ser a la central de otra persona.
  - /join_ casaba por prefijo: "/join_6" encajaba con media flota y la
    solicitud le llegaba a un dueno cualquiera.
  - /approve_ no miraba de quien era la central: cualquiera con una central
    aprobaba a cualquiera en la central de otro.

    python test_invitaciones.py
"""
import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

logging.basicConfig(level=logging.CRITICAL)

from telegram_bot import TelegramBot
from test_lead_capture import _make_mock_query, _make_mock_update
from test_retro_banco import _fm

A = "6C_C8_40_4F_C7"
B = "C8_2E_18_25_CA"
C = "AA_BB_CC_DD_EE"  # de otro cliente
JOSE, PEDRO, EXTRANO = "111", "222", "999"


def _bot(autorizadas):
    fm = _fm({
        "ESP32": {
            A: {"Telegram_ID": JOSE, "Telegram_ID_2": PEDRO, "Nombre": "casa"},
            B: {"Telegram_ID": JOSE, "Nombre": "taller"},
            C: {"Telegram_ID": "555", "Nombre": "ajena"},
        },
        "Usuarios": {}, "Horarios": {},
    })
    fm.get_authorized_devices = lambda chat: list(autorizadas.get(chat, []))
    fm.get_device_location = lambda d: fm.db.datos["ESP32"].get(d, {}).get("Nombre")
    fm.is_group_chat = lambda chat: False
    fm.is_user_admin = lambda chat: bool(autorizadas.get(chat))
    fm.add_pending_request = MagicMock()
    fm.get_device_owner = lambda d: fm.db.datos["ESP32"][d]["Telegram_ID"]
    fm.get_pending_request = MagicMock()
    fm.remove_pending_request = MagicMock()
    fm.add_authorized_chat = MagicMock(return_value=True)
    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager = fm
    bot.mqtt_handler = MagicMock()
    bot.mqtt_handler.device_id = C  # lo que antes acababa en la invitacion
    bot.send_message = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
    return bot


def _comando(bot, metodo, chat, texto):
    update = _make_mock_update(chat, texto)
    asyncio.run(getattr(bot, metodo)(update, None))
    return " ".join(str(c.args[0]) for c in update.message.reply_text.call_args_list), update


def test_adduser_con_una_central_propia_da_su_codigo_y_no_el_de_otro():
    bot = _bot({PEDRO: [A]})  # Pedro es "Usuario 2" de A: no es dueno
    texto, _ = _comando(bot, "_cmd_adduser", PEDRO, "/adduser")
    assert "Solo el dueño" in texto, texto

    bot = _bot({JOSE: [A]})
    texto, _ = _comando(bot, "_cmd_adduser", JOSE, "/adduser")
    assert f"/join_{A}" in texto and C not in texto, texto


def test_adduser_con_varias_centrales_pregunta_cual():
    bot = _bot({JOSE: [A, B]})
    _, update = _comando(bot, "_cmd_adduser", JOSE, "/adduser")
    teclado = update.message.reply_text.call_args.kwargs["reply_markup"]
    datos = {b.callback_data for fila in teclado.inline_keyboard for b in fila}
    assert datos == {f"adduser_{A}", f"adduser_{B}"}, datos


def test_boton_adduser_de_central_ajena_no_da_codigo():
    bot = _bot({JOSE: [A, B], PEDRO: [A]})
    q = _make_mock_query(PEDRO)
    q.data = f"adduser_{A}"
    asyncio.run(bot._handle_callback(SimpleNamespace(callback_query=q), None))
    assert "/join_" not in q.edit_message_text.call_args.args[0]


def test_join_con_prefijo_corto_no_crea_solicitud():
    bot = _bot({})
    texto, _ = _comando(bot, "_cmd_join", EXTRANO, "/join_6")
    assert "Código no válido" in texto, texto
    bot.firebase_manager.add_pending_request.assert_not_called()


def test_join_con_mac_en_otro_formato_resuelve_la_central():
    bot = _bot({})
    _comando(bot, "_cmd_join", EXTRANO, "/join_6c:c8:40:4f:c7:b2")
    args = bot.firebase_manager.add_pending_request.call_args.args
    assert args[2] == A, args
    assert bot.send_message.call_args.args[0] == JOSE, "la solicitud tenia que ir al dueno"


def test_approve_de_quien_no_es_dueno_no_aprueba_ni_borra():
    bot = _bot({PEDRO: [A]})
    bot.firebase_manager.get_pending_request.return_value = {"name": "x", "device_id": A}
    texto, _ = _comando(bot, "_cmd_approve", PEDRO, f"/approve_{EXTRANO}")
    assert "no es tuya" in texto, texto
    bot.firebase_manager.add_authorized_chat.assert_not_called()
    bot.firebase_manager.remove_pending_request.assert_not_called()


def test_approve_del_dueno_aprueba():
    bot = _bot({JOSE: [A]})
    bot.firebase_manager.get_pending_request.return_value = {"name": "x", "device_id": A}
    _comando(bot, "_cmd_approve", JOSE, f"/approve_{EXTRANO}")
    bot.firebase_manager.add_authorized_chat.assert_called_once_with(A, EXTRANO)
    bot.firebase_manager.remove_pending_request.assert_called_once()


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
