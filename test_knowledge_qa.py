"""
Comprueba las cuatro salidas de knowledge_qa.responder() sin red ni LLM.

Los cuatro caminos importan porque cada uno le dice algo distinto al usuario y
se registra distinto: si el de escalado se cuela por el de exito, alguien se
queda esperando una respuesta de soporte que nadie va a mandar.

    python test_knowledge_qa.py
"""
import asyncio
import sys
import types

from escalation_handler import NO_INFO_SENTINEL
import knowledge_qa


class ChunkFalso:
    def __init__(self, archivo, texto="contenido"):
        self.source_file = archivo
        self.heading = "un encabezado"
        self.text = texto


class ResultadoFalso:
    def __init__(self, archivo, score=0.5):
        self.chunk = ChunkFalso(archivo)
        self.score = score


class KBFalsa:
    def __init__(self, resultados):
        self._resultados = resultados

    def search(self, query, top_k=4, min_score=0.08):
        return self._resultados


class IAFalsa:
    def __init__(self, respuesta):
        self._respuesta = respuesta

    async def chat_with_context(self, mensaje, chunks):
        if isinstance(self._respuesta, Exception):
            raise self._respuesta
        return self._respuesta


def correr(kb, ia, pregunta="como configuro la bengala"):
    return asyncio.run(knowledge_qa.responder(pregunta, kb, ia))


def test_sin_base_de_conocimiento():
    r = correr(None, IAFalsa("da igual"))
    assert r.tipo == "fallback" and not r.ok
    assert r.error == "kb_unavailable"


def test_sin_resultados_escala():
    r = correr(KBFalsa([]), IAFalsa("da igual"))
    assert r.tipo == "escalation" and not r.ok
    assert r.error == "rag_no_results"
    assert r.fuentes == [] and r.scores == []


def test_el_llm_dice_que_no_sabe_escala():
    kb = KBFalsa([ResultadoFalso("03_bengala.md", 0.42)])
    r = correr(kb, IAFalsa(f"algo {NO_INFO_SENTINEL} algo"))
    assert r.tipo == "escalation" and not r.ok
    assert r.error == "llm_no_info"
    # Las fuentes se conservan aunque se escale: hacen falta para el registro.
    assert r.fuentes == ["03_bengala.md"]
    assert r.scores == [0.42]


def test_respuesta_buena_lleva_la_fuente():
    kb = KBFalsa([
        ResultadoFalso("03_bengala_config.md", 0.6),
        ResultadoFalso("01_primeros_pasos.md", 0.4),
    ])
    r = correr(kb, IAFalsa("Se configura desde la ficha del equipo."))
    assert r.tipo == "rag" and r.ok and r.error is None
    assert r.texto.startswith("Se configura desde la ficha del equipo.")
    assert "(Fuente: bengala config | primeros pasos)" in r.texto
    assert r.scores == [0.6, 0.4]


def test_las_fuentes_no_se_repiten_y_mantienen_el_orden():
    kb = KBFalsa([
        ResultadoFalso("03_bengala.md", 0.9),
        ResultadoFalso("01_alta.md", 0.5),
        ResultadoFalso("03_bengala.md", 0.3),  # mismo archivo, otro fragmento
    ])
    r = correr(kb, IAFalsa("respuesta"))
    assert "(Fuente: bengala | alta)" in r.texto


def test_un_fallo_del_llm_no_revienta():
    kb = KBFalsa([ResultadoFalso("03_bengala.md")])
    r = correr(kb, IAFalsa(RuntimeError("groq caido")))
    # "error", no "fallback": el registro los distingue y el analisis depende
    # de esa diferencia.
    assert r.tipo == "error" and not r.ok
    assert r.error == "RuntimeError: groq caido"
    # Lo importante: quien llama siempre tiene algo que decirle al usuario.
    assert r.texto


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
