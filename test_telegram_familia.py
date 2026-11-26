#!/usr/bin/env python3
"""
#308: un familiar de la app usa el bot con su Telegram vinculado.

Solo arma, desarma, pide pánico y ve el estado; la orden sigue el mismo camino
que la `Orden` de la app (aviso al dueño con su nombre). Quitarlo de
`miembros` le corta Telegram al momento.

    python test_telegram_familia.py
"""
import sys
import time
from unittest.mock import MagicMock

from mqtt_protocol import Command
from test_retro_banco import MAC, _fm


def _arbol():
    """Central de Jose (Telegram 7001112222); Ana es familiar con Telegram 7003334444; Pedro (7004445555) no pinta nada."""
    return {
        "ESP32": {MAC: {"ownerUid": "jose", "Nombre": "Casa", "Telegram_ID": "7001112222",
                        "Answer": False, "miembros": {"ana": {"rol": "familia"}}}},
        "Miembros": {MAC: {"ana": {"nombre": "Ana"}}},
        "Usuarios": {"jose": {"telegram_id": "7001112222"}, "ana": {"telegram_id": "7003334444"},
                     "pedro": {"telegram_id": "7004445555"}},
    }


def _fm_familia():
    fm = _fm(_arbol())
    cuentas = {"7001112222": ["jose"], "7003334444": ["ana"], "7004445555": ["pedro"]}
    fm._uids_por_chat_id = lambda chat: cuentas.get(str(chat), [])
    fm._ultima_orden, fm.on_sos, fm.on_orden_miembro = {}, MagicMock(), MagicMock()
    return fm


def test_el_familiar_ve_su_central_y_los_demas_no():
    fm = _fm_familia()
    assert fm.centrales_familia("7003334444") == [MAC]
    assert fm.centrales_familia("7001112222") == []      # el dueño ya la tiene por Telegram_ID
    assert fm.centrales_familia("7004445555") == []      # no es miembro
    assert fm.centrales_familia("-100") == []     # un grupo nunca
    # Si ademas es Usuario 2 de Telegram, va por el camino de siempre (sin duplicar).
    fm.db.datos["ESP32"][MAC]["Telegram_ID_2"] = "7003334444"
    assert fm.centrales_familia("7003334444") == []


def test_la_orden_por_telegram_va_como_la_de_la_app_y_avisa_al_dueno():
    fm = _fm_familia()
    assert fm.orden_familia(MAC, "7003334444", "arm") is True
    fm.mqtt_handler.send_command.assert_called_once_with(cmd=Command.ARM.value, device_id=MAC)
    assert fm.db.datos["ESP32"][MAC]["Answer"] is True
    args = fm.on_orden_miembro.call_args.args
    assert args[:4] == (MAC, "jose", "Ana", "arm"), args
    assert fm.orden_familia(MAC, "7004445555", "disarm") is False        # Pedro no
    assert fm.mqtt_handler.send_command.call_count == 1


def test_quitarlo_le_corta_telegram_al_momento():
    fm = _fm_familia()
    del fm.db.datos["ESP32"][MAC]["miembros"]["ana"]
    assert fm.centrales_familia("7003334444") == []
    assert fm.orden_familia(MAC, "7003334444", "arm") is False
    fm.mqtt_handler.send_command.assert_not_called()


def test_el_bot_manda_lo_del_familiar_por_orden_y_lo_del_dueno_directo():
    from telegram_bot import TelegramBot
    fm = _fm_familia()
    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager, bot.mqtt_handler = fm, MagicMock()

    assert bot._centrales_control("7003334444") == [MAC]
    bot._mandar("7003334444", MAC, "disarm")
    fm.mqtt_handler.send_command.assert_called_once_with(cmd=Command.DISARM.value, device_id=MAC)
    bot.mqtt_handler.send_disarm.assert_not_called()
    assert fm.on_orden_miembro.call_args.args[2] == "Ana"

    time.sleep(0.002)   # la dedup es por (uid, ts en ms)
    bot._mandar("7003334444", MAC, "panic")
    fm.mqtt_handler.send_command.assert_called_with(cmd=Command.TRIGGER_ALARM.value, device_id=MAC)
    fm.on_sos.assert_called_once_with(MAC)

    bot._mandar("7001112222", MAC, "arm")                   # el dueño, como siempre
    bot.mqtt_handler.send_arm.assert_called_once_with(device_id=MAC)


def test_vincularse_borra_el_sin_cuenta_cacheado():
    from firebase_manager import FirebaseManager
    fm = _fm(_arbol())
    fm.db.datos["Usuarios"]["ana"].pop("telegram_id")
    fm._cache_uid = {"7003334444": ([], time.time())}   # escribio al bot antes de vincularse
    fm._propagar_chat_id = lambda *a: None
    fm.update_data = lambda ruta, datos: fm.db.datos["Usuarios"]["ana"].update(datos) or True
    assert FirebaseManager.vincular_chat_id(fm, "ana", "7003334444") == "vinculado"
    assert "7003334444" not in fm._cache_uid


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
