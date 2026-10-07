#!/usr/bin/env python3
"""
Horarios desde Telegram: llegan a la central aunque este offline, y Firebase
no los deshace.

Los fallos que vigila:
  - /horarios off (y el horario por lenguaje natural) se mandaba sin encolar.
    La central usa sesion MQTT limpia: el broker lo tiraba, la central seguia
    armandose con su horario viejo y el bot contestaba "✅ deshabilitado".
  - El horario completo por lenguaje natural no llegaba a Firebase ni
    respondia; y un payload raro del LLM (enabled null, dias con nombre)
    acababa en Firebase o reventaba sin respuesta.
  - Una entrada vieja habilitada bajo el Telegram_ID del dueno ganaba
    ("habilitado gana") a la nueva deshabilitada: el listener deshacia el off.
  - Con varias centrales se escribia una a una y el listener devolvia las
    aun no escritas a su horario viejo.

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
from test_retro_banco import _fm

A = "6C_C8_40_4F_C7"
B = "C8_2E_18_25_CA"
CHAT = "111"


def _arbol():
    nodo = {"ownerUid": "jose", "Telegram_ID": CHAT, "Nombre": "casa"}
    return {
        "ESP32": {A: dict(nodo), B: dict(nodo, Nombre="taller")},
        "Usuarios": {"jose": {"Dispositivos": [A, B]}},
        "Horarios": {},
    }


def _bot(online=False, datos=None):
    fm = _fm(datos or _arbol())
    fm.get_device_location = lambda d: fm.db.datos["ESP32"].get(d, {}).get("Nombre")
    fm.get_authorized_devices = lambda chat: [A, B]
    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager = fm
    bot.mqtt_handler = MagicMock()
    bot.mqtt_handler.resolve_full_device_id = lambda d: d + "_B2"
    bot.mqtt_handler.is_device_online = lambda d: online and d.endswith("_B2")
    bot.device_manager = MagicMock()
    bot.device_manager.get_device_info.return_value = {}
    bot.send_message = AsyncMock()
    bot.interaction_logger = MagicMock()
    bot._get_keyboard = MagicMock(return_value=None)
    return bot


def _aislado(fn):
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


def _horarios(bot):
    return bot.firebase_manager.db.datos["Horarios"]


@_aislado
def test_offline_se_encola_y_se_avisa():
    bot = _bot(online=False)
    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A]))
    kw = bot.mqtt_handler.send_set_schedule.call_args.kwargs
    assert kw["queue_if_offline"] is True, kw
    avisos = [c.args[1] for c in bot.send_message.call_args_list]
    assert any("se aplicará cuando la central se conecte" in a for a in avisos), avisos


@_aislado
def test_online_con_la_mac_larga_no_avisa_en_falso():
    """La telemetria llega con la MAC de 17; la clave es la de 14."""
    bot = _bot(online=True)
    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A]))
    bot.send_message.assert_not_called()


@_aislado
def test_off_borra_la_entrada_vieja_habilitada_del_mismo_dueno():
    datos = _arbol()
    datos["Horarios"] = {CHAT: {"devices": {A: {
        "activationTime": "22:00", "deactivationTime": "06:00", "enabled": True,
        "days": ["Lunes"], "lastUpdated": 1}}}}
    bot = _bot(datos=datos)
    sch.scheduler.set_enabled(A, False)

    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A]))

    h = _horarios(bot)
    assert h["jose"]["devices"][A]["enabled"] is False
    assert A not in h.get(CHAT, {}).get("devices", {}), "la vieja habilitada seguia ahi"
    elegidos = sch.elegir_por_dispositivo(
        bot.firebase_manager._filtrar_horarios(h), bot.firebase_manager._devices_for_schedule_key)
    assert elegidos[A]["enabled"] is False, "el listener volveria a habilitarla"


@_aislado
def test_varias_centrales_se_escriben_de_una_vez():
    bot = _bot()
    escrituras = []
    ref = bot.firebase_manager.db.reference

    def espia(ruta):
        r = ref(ruta)
        if ruta == "Horarios":
            original = r.update
            r.update = lambda cambios: (escrituras.append(sorted(cambios)), original(cambios))
        return r

    bot.firebase_manager.db.reference = espia
    asyncio.run(bot._sync_schedule_to_devices(CHAT, [A, B]))
    assert escrituras == [[f"jose/devices/{A}", f"jose/devices/{B}"]], escrituras


def _nl(bot, params):
    bot.ai_handler = MagicMock()
    bot.ai_handler._backend = "groq"
    bot.ai_handler.parse_intent = AsyncMock(return_value={
        "intent": "schedule", "device": "casa", "confidence": 0.95, "reply": "",
        "params": params})
    update = _make_mock_update(CHAT, "arma la casa de lunes a viernes de 10pm a 6am")
    asyncio.run(bot._handle_ai_message(update, CHAT, update.message.text, [A, B]))
    return " ".join(str(c.args[0]) for c in update.message.reply_text.call_args_list)


@_aislado
def test_horario_completo_por_lenguaje_natural_llega_a_firebase_y_responde():
    bot = _bot(online=False)
    respuesta = _nl(bot, {"enabled": True, "on_hour": 22, "on_minute": 0,
                          "off_hour": 6, "off_minute": 0, "days": [1, 2, 3, 4, 5]})
    assert _horarios(bot)["jose"]["devices"][A]["activationTime"] == "22:00"
    kw = bot.mqtt_handler.send_set_schedule.call_args.kwargs
    assert kw["queue_if_offline"] is True and kw["device_id"] == A, kw
    assert "Horario configurado" in respuesta, respuesta


@_aislado
def test_payload_raro_del_llm_no_toca_nada():
    for params in (
        {"enabled": None, "on_hour": 22, "on_minute": 0, "off_hour": 6, "off_minute": 0},
        {"enabled": True, "on_hour": 22, "on_minute": 0, "off_hour": 6, "off_minute": 0, "days": ["Lunes"]},
        {"enabled": True, "on_hour": 25, "on_minute": 0, "off_hour": 6, "off_minute": 0},
    ):
        bot = _bot()
        respuesta = _nl(bot, params)
        assert _horarios(bot) == {}, (params, _horarios(bot))
        bot.mqtt_handler.send_set_schedule.assert_not_called()
        assert "No pude interpretar" in respuesta, (params, respuesta)
        assert A not in sch.scheduler.configs, params


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:  # no solo AssertionError: un error no corta la suite
            fallos += 1
            print(f"FALLO  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
