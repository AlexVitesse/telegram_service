#!/usr/bin/env python3
"""
G7 (29-oct): desde el chat de la APP, Senti explica la ruta en pantalla y no
da comandos de Telegram. Desde Telegram, todo igual.

    python test_senti_app.py
"""
import asyncio
import sys

import ai_handler
import knowledge_qa


def _ia_que_anota():
    ia = ai_handler.AIHandler.__new__(ai_handler.AIHandler)
    ia._chat_model = ""
    ia._backend = "prueba"
    visto = {}

    async def _call_llm(system_prompt, user_prompt, **k):
        visto["prompt"] = system_prompt
        return "ok"

    ia._call_llm = _call_llm
    return ia, visto


def test_telegram_sigue_con_comandos():
    ia, visto = _ia_que_anota()
    asyncio.run(ia.chat_with_context("como activo los horarios", ["doc"]))
    assert visto["prompt"] == ai_handler.RAG_CHAT_PROMPT
    assert "/bengala, /adduser, /horarios" in visto["prompt"]


def test_app_da_la_ruta_y_no_comandos():
    ia, visto = _ia_que_anota()
    asyncio.run(ia.chat_with_context("como activo los horarios", ["doc"], canal="app"))
    p = visto["prompt"]
    assert p == ai_handler.RAG_CHAT_PROMPT_APP
    assert "Incluye comandos exactos" not in p
    assert "NUNCA escribas comandos de Telegram" in p
    # Los textos reales de la app para lo que la KB explica con comandos.
    for boton in ("Horarios", "Guardar horario", "Ver detalles y ajustes",
                  "Bengala", "Pregunta", "Autorizar", "Sensores LoRa",
                  "Proteger ahora", "Desarmar", "Borrar dispositivo",
                  "Tiempo de salida", "Solicitar ayuda inmediata"):
        assert boton in p, f"falta {boton!r} en el mapa de la app"


class _KB:
    def search(self, *a, **k):
        class T:
            text, source_file, heading = "doc", "09_horarios.md", "h"

        class R:
            score, chunk = 0.9, T()
        return [R()]


class _IA:
    async def chat_with_context(self, mensaje, chunks, canal="telegram"):
        return f"canal={canal}"


def test_responder_pasa_el_canal():
    r = asyncio.run(knowledge_qa.responder("horarios", _KB(), _IA()))
    assert r.texto == "canal=telegram", r.texto
    r = asyncio.run(knowledge_qa.responder("horarios", _KB(), _IA(), canal="app"))
    assert r.texto == "canal=app", r.texto


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
