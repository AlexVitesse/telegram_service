"""
La busqueda de la KB sobrevive a que Ollama se caiga despues de arrancar.

El fallo que vigila: con embeddings, cada consulta pide el vector de la
pregunta a Ollama. Si Ollama muere a media vida del proceso, esa llamada
lanzaba ConnectError, `knowledge_qa` lo tomaba por transitorio y el usuario
leia "El asistente tardó demasiado en responder" en TODAS las preguntas, aunque
el LLM de chat estuviese sano. Visto en produccion en 2026-10.

Sin red: los embeddings se fingen.

    python test_rag_sin_ollama.py
"""
import os
import sys

import httpx
import numpy as np

import rag_handler
from rag_handler import KnowledgeBase

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")


def _kb_con_embeddings_falsos():
    """Carga la KB real con Ollama 'vivo' (vectores falsos) y la devuelve."""
    kb = KnowledgeBase(KB_DIR, use_embeddings=True)
    kb._get_embedding = lambda text, timeout=30.0: np.ones(8, dtype=np.float32)
    assert kb.load() > 0, "la KB no cargo ningun chunk"
    assert kb._embeddings is not None, "tenia que cargar con embeddings"
    return kb


def _ollama_caido(text, timeout=30.0):
    raise httpx.ConnectError("Connection refused")


def test_si_ollama_cae_la_busqueda_sigue_con_tfidf():
    kb = _kb_con_embeddings_falsos()
    kb._get_embedding = _ollama_caido

    resultados = kb.search("como configuro los horarios", top_k=3, min_score=0.05)

    assert resultados, "sin Ollama tenia que contestar TF-IDF, no quedarse vacio"


def test_no_apaga_los_embeddings_para_siempre():
    """Cuando Ollama vuelva, la siguiente consulta tiene que volver a usarlos."""
    kb = _kb_con_embeddings_falsos()
    kb._get_embedding = _ollama_caido
    kb.search("horarios")

    assert kb._use_embeddings, "un fallo puntual no debe apagar los embeddings"


def test_la_consulta_usa_el_techo_corto():
    kb = _kb_con_embeddings_falsos()
    techos = []

    def espia(text, timeout=30.0):
        techos.append(timeout)
        return np.ones(8, dtype=np.float32)

    kb._get_embedding = espia
    kb.search("horarios")

    assert techos == [rag_handler.QUERY_EMBED_TIMEOUT_SEC], techos


def test_recargar_espera_a_la_busqueda_en_curso():
    """
    `search` corre en un hilo y `/reload_kb` vacia `chunks`. Sin lock, la
    recarga se colaba a mitad de busqueda y esta reventaba con IndexError.
    """
    import threading
    import time

    kb = KnowledgeBase(KB_DIR, use_embeddings=False)
    kb.load()
    dentro = threading.Event()
    orden = []
    boosts = kb._apply_boosts

    def boosts_lentos(query, scores):
        dentro.set()
        time.sleep(0.2)  # ventana en la que la recarga se colaba
        boosts(query, scores)

    kb._apply_boosts = boosts_lentos

    def buscar():
        kb.search("horarios")
        orden.append("busqueda")

    hilo = threading.Thread(target=buscar)
    hilo.start()
    dentro.wait(5)
    kb.load()
    orden.append("recarga")
    hilo.join(5)

    assert orden == ["busqueda", "recarga"], orden


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
