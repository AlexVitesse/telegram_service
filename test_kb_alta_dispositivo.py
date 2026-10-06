"""
Senti encuentra como dar de alta un equipo aunque el usuario no diga "vincular".

El fallo que vigila: "Como doy de alta un dispositivo?" traia de la KB "Como
desvinculo un dispositivo" y el LLM acababa explicando /adduser (invitar
USUARIOS). Ningun texto de la KB usaba las palabras del usuario: alta,
agregar, emparejar. Visto en produccion el 2026-10-06, con TF-IDF.

Sin red: solo TF-IDF, como corre hoy en produccion.

    python test_kb_alta_dispositivo.py
"""
import os
import sys

from config import AIConfig
from rag_handler import KnowledgeBase

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")
TOP_K = AIConfig().rag_max_chunks
MIN_SCORE = max(AIConfig().rag_min_score, 0.15)  # produccion corre con ~0.15

_kb = None


def _buscar(pregunta):
    global _kb
    if _kb is None:
        _kb = KnowledgeBase(KB_DIR, use_embeddings=False)
        assert _kb.load() > 0, "la KB no cargo ningun chunk"
    return _kb.search(pregunta, top_k=TOP_K, min_score=MIN_SCORE)


def _top_es_emparejar(pregunta):
    resultados = _buscar(pregunta)
    assert resultados, f"{pregunta!r}: sin resultados"
    top = resultados[0].chunk
    donde = f"{pregunta!r} -> {top.source_file} / {top.heading}"
    texto = (top.heading + " " + top.text).lower()
    assert "desvincul" not in top.heading.lower(), donde
    assert "emparejamiento" in texto or "bluetooth" in texto, donde


def test_dar_de_alta():
    _top_es_emparejar("Como doy de alta un dispositivo?")


def test_agregar():
    _top_es_emparejar("como agrego un dispositivo nuevo")


def test_emparejar():
    _top_es_emparejar("como emparejo mi equipo")


def test_vincular():
    # "vinculo" es una palabra distinta de "desvinculo" para TF-IDF: antes
    # ganaba la FAQ de desvincular y la lista de ejemplos de 06.
    _top_es_emparejar("como vinculo un dispositivo")


def test_registrar():
    _top_es_emparejar("como registro un dispositivo")


def _top_es_borrar(pregunta):
    resultados = _buscar(pregunta)
    assert resultados, f"{pregunta!r}: sin resultados"
    top = resultados[0].chunk
    donde = f"{pregunta!r} -> {top.source_file} / {top.heading}"
    assert "desvincul" in top.heading.lower(), donde
    assert "Borrar dispositivo" in top.text, donde


def test_desvincular():
    _top_es_borrar("como desvinculo un dispositivo")


def test_borrar_o_quitar():
    _top_es_borrar("como borro un dispositivo")
    _top_es_borrar("como quito un equipo")


def test_para_que_sirve_la_app():
    assert _buscar("para que sirve esta app"), "sin resultados"


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
