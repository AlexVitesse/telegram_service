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
import re
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


# --- Hechos: la KB dice lo que hace el codigo (revision Codex del PR #9) ---

def _kb_texto():
    """{archivo: texto en minusculas} de toda la KB."""
    out = {}
    for f in sorted(os.listdir(KB_DIR)):
        if f.endswith(".md"):
            with open(os.path.join(KB_DIR, f), encoding="utf-8") as fh:
                out[f] = fh.read().lower()
    return out


def test_clip_3_segundos():
    # config.h: LONG_PRESS_TIME 3000; alarma_modulos.ino: beep(5) al entrar.
    kb = _kb_texto()
    for f, t in kb.items():
        assert "5 a 8 segundos" not in t, f
    todo = " ".join(kb.values())
    assert "3 segundos" in todo and "cinco pitidos" in todo


def test_tiempo_de_salida_10_a_180():
    # El VPS solo reenvia >= 10 (firebase_manager.py); el firmware acepta 10-300.
    kb = _kb_texto()
    for f, t in kb.items():
        assert not re.search(r"(?<!1)0 (a|y) 180|(?<!1)0[-–]180", t), f
    assert "10 y 180" in kb["14_faq.md"]
    assert "10 a 180" in kb["04_app_sentinel_guard.md"]


def test_borrar_no_limpia_el_master():
    # borrar_equipo borra la nube y apaga el horario. Con el firmware de la fase 3
    # (oct-2026) tambien manda forget; con el anterior la NVS del Master queda.
    kb = _kb_texto()
    for f in ("14_faq.md", "04_app_sentinel_guard.md"):
        assert "reset de fabrica" in kb[f], f
        assert "memoria" in kb[f], f


def test_botones_bengala_solo_en_su_central():
    # Desde el 7-oct (#11) los botones llevan la MAC y actuan solo sobre ella.
    t = _kb_texto()["08_bengala.md"]
    assert "solo sobre la central del aviso" in t
    assert "todas tus centrales que esten sonando" not in t
    assert "desarma todos tus equipos" not in t
    assert "120" not in t and "tiempo agotado" not in t  # timeout del bot: codigo muerto


def test_horarios_offline_se_aplican_al_conectarse():
    # Desde el 7-oct (#12, #13) Telegram tambien encola y la cola no caduca.
    t = _kb_texto()["09_horarios.md"]
    assert "se propaga a todos los componentes" not in t
    assert "se aplicara cuando la central se conecte" in t
    assert "no se guardan para despues" not in t
    assert "24 horas" not in t.split("## sincronizacion de horarios")[1].split("##")[0]


def test_invitaciones_solo_el_dueno():
    kb = _kb_texto()
    assert "solo el dueño de la central" in kb["05_comandos_telegram.md"]
    assert "chat privado" in kb["12_usuarios_permisos.md"]


def test_bengala_sin_datos_inventados():
    for f, t in _kb_texto().items():
        assert "no toxico" not in t and "no tóxico" not in t, f
        assert "20 metros cuadrados" not in t, f


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
