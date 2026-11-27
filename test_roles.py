#!/usr/bin/env python3
"""
#314: dos roles por persona, que elige el dueño.

  - Familia y Usuario 2 de Telegram: armar, desarmar, pánico y estado.
  - Administrador: además horarios, bengala, modo y sensores.
  - Invitar, quitar, traspasar y aprobar: solo el dueño.

    python test_roles.py
"""
import asyncio
import sys

from test_retro_banco import MAC
from test_telegram_familia import _fm_familia

DUENO, ANA, USUARIO2 = "7001112222", "7003334444", "7006667777"


def _fm():
    fm = _fm_familia()
    fm.db.datos["ESP32"][MAC]["Telegram_ID_2"] = USUARIO2
    return fm


def test_ajustes_solo_dueno_y_administrador():
    fm = _fm()
    assert fm.centrales_ajustes(DUENO) == [MAC]
    assert fm.centrales_ajustes(ANA) == []              # familia
    assert fm.centrales_ajustes(USUARIO2) == []         # Usuario 2 ya no cambia ajustes
    assert MAC in fm.get_authorized_devices(USUARIO2)   # pero sigue armando y recibiendo avisos
    fm.db.datos["ESP32"][MAC]["miembros"]["ana"]["rol"] = "admin"
    assert fm.centrales_ajustes(ANA) == [MAC]
    assert fm.puede_ajustar(MAC, ANA) and not fm.puede_ajustar(MAC, USUARIO2)
    assert not fm.es_dueno(MAC, ANA)                    # invitar y aprobar siguen siendo del dueño


def test_solo_el_dueno_cambia_el_rol():
    fm = _fm()
    assert fm.cambiar_rol("ana", MAC, "ana", "admin") == "no_es_dueno"
    assert fm.cambiar_rol("jose", MAC, "ana", "dueno") == "rol_malo"
    assert fm.cambiar_rol("jose", MAC, "pedro", "admin") == "no_es_miembro"
    assert fm.db.datos["ESP32"][MAC]["miembros"]["ana"] == {"rol": "familia"}
    assert fm.cambiar_rol("jose", MAC, "ana", "admin") == {"nombre": "Casa"}
    assert fm.db.datos["ESP32"][MAC]["miembros"]["ana"] == {"rol": "admin"}


def test_api_cambia_el_rol():
    from test_api_server import con_api, pedir
    fm, out = _fm(), []

    async def p(url, api):
        out.append(await pedir(url, token="bueno", cuerpo={"mac": MAC, "uid": "ana", "rol": "admin"},
                               ruta="/equipos/miembros/rol"))
    asyncio.run(con_api(fm, "jose", p))
    assert out[0] == (200, {"ok": True, "rol": "admin"}), out
    assert fm.db.datos["ESP32"][MAC]["miembros"]["ana"]["rol"] == "admin"

    out.clear()
    asyncio.run(con_api(fm, "ana", p))
    assert out[0][0] == 403, out


def test_el_bot_no_deja_horarios_al_usuario2():
    from unittest.mock import AsyncMock, MagicMock
    from telegram_bot import TelegramBot
    fm = _fm()
    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager, bot.mqtt_handler = fm, MagicMock()
    bot._get_keyboard = lambda: None
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    assert asyncio.run(bot._ajustes(update, USUARIO2)) == []
    assert "administrador" in update.message.reply_text.call_args.args[0]
    assert asyncio.run(bot._ajustes(update, DUENO)) == [MAC]


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
