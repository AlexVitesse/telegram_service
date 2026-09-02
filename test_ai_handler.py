"""
Los defaults del handler, sin red y sin levantar nada.

El fallo que vigila: el nombre del modelo de Ollama esta escrito DOS veces
-`config.AIConfig.ollama_model` y el parametro de `AIHandler.__init__`- y hasta
2026-09 las dos decian "gtp-oss:20b", con la p y la t cambiadas de sitio. En un
VPS que no declare INTENT_MODEL, CHAT_MODEL ni OLLAMA_MODEL, el handler acaba
pidiendole a Ollama ese nombre y Ollama responde "model not found": ni
clasificador ni RAG, y el .env no lo delata porque ahi no pone nada.

    python test_ai_handler.py
"""
import inspect
import sys

import ai_handler
from config import AIConfig


def test_el_modelo_de_ollama_se_llama_igual_en_los_dos_sitios():
    """Dos copias del mismo nombre: lo unico que las mantiene juntas es esto."""
    del_constructor = inspect.signature(
        ai_handler.AIHandler.__init__
    ).parameters["ollama_model"].default
    assert del_constructor == AIConfig().ollama_model, (
        f"el default del constructor ({del_constructor!r}) no es el de config "
        f"({AIConfig().ollama_model!r})"
    )


def test_el_default_de_ollama_no_es_un_nombre_inventado():
    """
    No se comprueba contra una lista de modelos -eso caduca-, sino contra la
    forma: `familia:tamano`, y que la familia no sea el typo conocido.
    """
    nombre = AIConfig().ollama_model
    assert ":" in nombre, f"{nombre!r} no tiene la forma modelo:tag de Ollama"
    assert "gtp" not in nombre, f"{nombre!r}: 'gtp' es el typo de 'gpt'"


def test_con_backend_ollama_ningun_modelo_acaba_siendo_de_groq():
    """
    Los defaults de intent/chat SON modelos de Groq mientras el backend por
    defecto es ollama. `__init__` lo detecta y los sustituye; esta prueba
    comprueba que la sustitucion sigue ocurriendo, porque sin ella el handler
    le pide a Ollama un modelo que solo existe en Groq.
    """
    h = ai_handler.AIHandler(
        llm_backend="ollama",
        intent_model=AIConfig().intent_model,
        chat_model=AIConfig().chat_model,
        groq_api_key="",
    )
    for etiqueta, modelo in (("intent", h._intent_model), ("chat", h._chat_model)):
        assert not ai_handler._looks_like_groq_model(modelo) or \
            ai_handler._looks_like_ollama_model(modelo), \
            f"{etiqueta}_model={modelo!r} es de Groq con backend=ollama"


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
