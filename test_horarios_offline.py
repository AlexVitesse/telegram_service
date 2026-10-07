#!/usr/bin/env python3
"""
Horarios desde Telegram con la central sin conexion.

El fallo que vigila: /horarios off (y el horario por lenguaje natural) se
mandaba a la central sin encolar. La central usa sesion MQTT limpia, asi que
el broker lo tiraba; la central seguia armandose con su horario viejo y el bot
contestaba "✅ deshabilitado". Ademas, el horario completo por lenguaje
natural no se escribia en Firebase y no respondia nada.

    python test_horarios_offline.py
"""
import asyncio
import logging
import sys
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.CRITICAL)

import scheduler as sch
from telegram_bot import TelegramBot
from test_lead_capture import _make_mock_update

A = "6C_C8_40_4F_C7"
CHAT = "111"


def _bot(online=False):
    bot = TelegramBot.__new__(TelegramBot)
    fm = MagicMock()
    fm.is_available.return_value = True
    fm._nodo.return_value = {"ownerUid": "jose"}
    fm.get_device_location.return_value = "casa"
    fm.get_authorized_devices.return_value = [A]
    bot.firebase_manager = fm
    bot.mqtt_handler = MagicMock()
    bot.mqtt_handler.is_device_online.return_value = online
    bot.device_manager = MagicMock()
    bot.device_manager.get_device_info.return_value = {}
    bot.send_message = AsyncMock()
    bot.interaction_logger = MagicMock()
    bot._get_keyboard = MagicMock(return_value=None)
    return bot


def _sin_disco(fn):
    """El scheduler es global y guarda en schedule_config.json: aqui no."""
    def envuelta():
        guardadas, guardar = sch.scheduler.configs, sch.scheduler._save_configs
        sch.scheduler.configs, sch.scheduler._save_configs = {}, lambda: None
        try:
            fn()
        finally:
            sch.scheduler.configs, sch.scheduler._save_configs = guardadas, guardar
    envuelta.__name__ = fn.__name__
    return envuelta


@_sin_disco
def test_offline_se_encola_y_se_avisa():
    bot = _bot(online=False)
    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A]))

    kw = bot.mqtt_handler.send_set_schedule.call_args.kwargs
    assert kw["queue_if_offline"] is True, kw
    avisos = [c.args[1] for c in bot.send_message.call_args_list]
    assert any("se aplicará cuando la central se conecte" in a for a in avisos), avisos


@_sin_disco
def test_online_no_avisa_de_nada():
    bot = _bot(online=True)
    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A]))
    assert bot.mqtt_handler.send_set_schedule.call_args.kwargs["queue_if_offline"] is True
    bot.send_message.assert_not_called()


@_sin_disco
def test_horario_completo_por_lenguaje_natural_llega_a_firebase_y_responde():
    bot = _bot(online=False)
    bot.ai_handler = MagicMock()
    bot.ai_handler._backend = "groq"
    bot.ai_handler.parse_intent = AsyncMock(return_value={
        "intent": "schedule", "device": "casa", "confidence": 0.95, "reply": "",
        "params": {"enabled": True, "on_hour": 22, "on_minute": 0,
                   "off_hour": 6, "off_minute": 0, "days": [1, 2, 3, 4, 5]},
    })
    update = _make_mock_update(CHAT, "arma la casa de lunes a viernes de 10pm a 6am")

    asyncio.run(bot._handle_ai_message(update, CHAT, update.message.text, [A]))

    rutas = [c.args[0] for c in bot.firebase_manager.db.reference.call_args_list]
    assert f"Horarios/jose/devices/{A}" in rutas, rutas
    kw = bot.mqtt_handler.send_set_schedule.call_args.kwargs
    assert kw["queue_if_offline"] is True and kw["device_id"] == A, kw
    respuestas = " ".join(str(c.args[0]) for c in update.message.reply_text.call_args_list)
    assert "Horario configurado" in respuestas, respuestas


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
