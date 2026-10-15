#!/usr/bin/env python3
"""
El SOS de la app (15-oct): llega a la central y avisa al grupo de Telegram.

La app escribe `DisparoApp = {"<fecha>": true}` con set(); el VPS solo
aceptaba `true` a secas y el SOS no llegaba nunca a la central.

    python test_sos_app.py
"""
import logging
import sys
from unittest.mock import MagicMock

logging.basicConfig(handlers=[logging.NullHandler()])

from firebase_manager import es_disparo_app
from test_estado_y_armado import _Evento, _fm


def test_el_objeto_de_la_app_dispara():
    assert es_disparo_app({"2026_10_15_21_30_00_000": True})
    assert es_disparo_app(True)


def test_desactivar_no_dispara():
    assert not es_disparo_app({"2026_10_15_21_31_00_000": False})
    assert not es_disparo_app(False)
    assert not es_disparo_app(None)


def test_el_sos_llega_a_la_central_y_avisa():
    fm = _fm({"C8": {"Nombre": "Casa"}})
    avisos = []
    fm.on_sos = avisos.append
    fm._app_command_listener(_Evento("/C8/DisparoApp", {"2026_10_15_21_30_00_000": True}))
    fm.mqtt_handler.send_command.assert_called_once_with(cmd="trigger_alarm", device_id="C8")
    assert avisos == ["C8"]


def test_un_fallo_del_aviso_no_rompe_el_disparo():
    fm = _fm({"C8": {}})
    fm.on_sos = MagicMock(side_effect=RuntimeError("bot caido"))
    fm._app_command_listener(_Evento("/C8/DisparoApp", {"x": True}))
    fm.mqtt_handler.send_command.assert_called_once()


def _main(grupo, en_linea):
    import main as m
    app = m.AlarmBridgeService.__new__(m.AlarmBridgeService)
    app.mqtt = MagicMock()
    app.mqtt.is_device_online.return_value = en_linea
    app.telegram = MagicMock()
    app.telegram.is_running.return_value = True
    app._loop = MagicMock()
    enviados = []
    m.asyncio.run_coroutine_threadsafe = lambda coro, loop: enviados.append(coro)
    app.telegram.send_message = lambda chat, msg, **kw: (chat, msg)
    m.firebase_manager._get_all_devices = lambda: {"C8": {"Nombre": "Casa", "Group_ID": grupo}}
    app._avisar_sos("C8")
    return enviados


def test_con_grupo_avisa_y_dice_si_la_sirena_no_suena():
    (chat, msg), = _main("-1001234567890", en_linea=False)
    assert chat == "-1001234567890"
    assert "Casa" in msg and "NO va a sonar" in msg and "911" in msg


def test_sin_grupo_no_avisa_a_nadie():
    assert _main("", en_linea=True) == []


if __name__ == "__main__":
    fallos = 0
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            try:
                f()
                print(f"OK   {nombre}")
            except Exception as e:
                fallos += 1
                print(f"FALLA {nombre}: {e!r}")
    sys.exit(1 if fallos else 0)
