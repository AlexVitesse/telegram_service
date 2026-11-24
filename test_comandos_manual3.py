"""
Los comandos que el Manual 3.0 le ensena al cliente existen en el bot.

El manual impreso dice "/modo auto", "/modo pregunta" y "/sensores"; el bot
solo tenia /auto, /preguntar y /sensors. Se anaden sin quitar los de antes, y
/modo no duplica logica: delega en /auto y /preguntar.

    python test_comandos_manual3.py
"""
import asyncio
import sys
import types


def _bot():
    from telegram_bot import TelegramBot
    return object.__new__(TelegramBot)  # sin __init__: ni red ni Firebase


def _comandos():
    from telegram.ext import CommandHandler
    b = _bot()
    handlers = []
    b.application = types.SimpleNamespace(add_handler=handlers.append)
    b._register_handlers()
    return {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}


def test_existen_los_del_manual_y_los_de_antes():
    cmds = _comandos()
    for c in ("modo", "sensores", "sensors", "auto", "preguntar", "deshabilitar"):
        assert c in cmds, f"falta /{c}"


class _Msg:
    def __init__(self):
        self.respuestas = []

    async def reply_text(self, texto, **k):
        self.respuestas.append(texto)


def _modo(args):
    b = _bot()
    llamado = []

    async def auto(update, context):
        llamado.append("auto")

    async def preguntar(update, context):
        llamado.append("preguntar")

    b._cmd_auto, b._cmd_preguntar = auto, preguntar
    update = types.SimpleNamespace(message=_Msg())
    asyncio.run(b._cmd_modo(update, types.SimpleNamespace(args=args)))
    return llamado, update.message.respuestas


def test_modo_delega_en_auto_y_preguntar():
    assert _modo(["auto"])[0] == ["auto"]
    assert _modo(["Pregunta"])[0] == ["preguntar"]


def test_modo_sin_argumento_o_raro_explica_el_uso():
    for args in ([], ["xyz"]):
        llamado, resp = _modo(args)
        assert not llamado
        assert resp and "/modo auto" in resp[0] and "/modo pregunta" in resp[0]


def test_la_kb_los_documenta_como_el_manual():
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "knowledge_base", "05_comandos_telegram.md")
    doc = open(ruta, encoding="utf-8").read()
    for c in ("/modo auto", "/modo pregunta", "/sensores"):
        assert c in doc, f"la KB no documenta {c}"
    assert "no existe" not in doc.replace("No existe un comando dedicado tipo /stop", "")


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
