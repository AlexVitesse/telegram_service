"""
Comprueba las cuatro salidas de knowledge_qa.responder() sin red ni LLM.

Los cuatro caminos importan porque cada uno le dice algo distinto al usuario y
se registra distinto: si el de escalado se cuela por el de exito, alguien se
queda esperando una respuesta de soporte que nadie va a mandar.

    python test_knowledge_qa.py
"""
import asyncio
import sys

import httpx

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
    def __init__(self, respuesta, tarda=0.0):
        self._respuesta = respuesta
        self._tarda = tarda

    async def chat_with_context(self, mensaje, chunks):
        if self._tarda:
            await asyncio.sleep(self._tarda)
        if isinstance(self._respuesta, Exception):
            raise self._respuesta
        return self._respuesta


class ErrorHTTP(Exception):
    """Imita un error del SDK de Groq, que lleva el codigo encima."""

    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


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
    assert r.texto == "Se configura desde la ficha del equipo."
    # La fuente ya no va dentro del texto: viaja aparte y la pone quien envia.
    assert knowledge_qa.pista_de_fuentes(r.fuentes) == "bengala config | primeros pasos"
    assert r.scores == [0.6, 0.4]


def test_las_fuentes_no_se_repiten_y_mantienen_el_orden():
    kb = KBFalsa([
        ResultadoFalso("03_bengala.md", 0.9),
        ResultadoFalso("01_alta.md", 0.5),
        ResultadoFalso("03_bengala.md", 0.3),  # mismo archivo, otro fragmento
    ])
    r = correr(kb, IAFalsa("respuesta"))
    assert knowledge_qa.pista_de_fuentes(r.fuentes) == "bengala | alta"


def test_un_fallo_definitivo_manda_a_soporte():
    kb = KBFalsa([ResultadoFalso("03_bengala.md")])
    r = correr(kb, IAFalsa(TypeError("bug mio")))
    assert r.tipo == "error" and not r.ok
    assert r.error.startswith("definitivo: TypeError")
    # Un TypeError no se arregla reintentando: no se le invita a repetir.
    assert "ntenta de nuevo" not in r.texto
    assert r.texto


def test_un_timeout_si_invita_a_reintentar():
    kb = KBFalsa([ResultadoFalso("03_bengala.md")])
    r = correr(kb, IAFalsa(httpx.ReadTimeout("se colgo")))
    assert r.tipo == "error" and not r.ok
    assert r.error.startswith("transitorio: ReadTimeout")
    assert "ntentarlo" in r.texto


def test_un_429_cuenta_como_transitorio():
    kb = KBFalsa([ResultadoFalso("03_bengala.md")])
    r = correr(kb, IAFalsa(ErrorHTTP(429)))
    assert r.error.startswith("transitorio: ErrorHTTP")


def test_un_400_no_es_transitorio():
    kb = KBFalsa([ResultadoFalso("03_bengala.md")])
    r = correr(kb, IAFalsa(ErrorHTTP(400)))
    assert r.error.startswith("definitivo: ErrorHTTP")


def test_un_llm_colgado_se_corta_solo():
    """El techo total: sin el, la peticion no volveria nunca."""
    import knowledge_qa as kq
    from config import config

    original = config.ai.llm_timeout_sec
    config.ai.llm_timeout_sec = 0.05  # 0.05*2 + margen... bajamos el margen
    kq._MARGEN_CADENA = 0.05
    try:
        kb = KBFalsa([ResultadoFalso("03_bengala.md")])
        r = correr(kb, IAFalsa("nunca llega", tarda=5))
        assert r.tipo == "error" and not r.ok
        assert r.error.startswith("transitorio: TimeoutError")
    finally:
        config.ai.llm_timeout_sec = original
        kq._MARGEN_CADENA = 5.0


def test_el_markdown_no_llega_al_usuario():
    """
    Ninguno de los dos canales lo renderiza -el bot manda esta respuesta sin
    parse_mode-, asi que "**/bengala**" se veia con los asteriscos en los dos.
    """
    kb = KBFalsa([ResultadoFalso("08_bengala.md")])
    r = correr(kb, IAFalsa("En Telegram escribe **/bengala**.\n\n## Modos"))

    assert "**" not in r.texto and "#" not in r.texto
    assert "escribe /bengala." in r.texto
    assert "Modos" in r.texto


def test_los_nombres_con_guion_bajo_no_se_parten():
    """
    Media base habla de Tiempo_Bomba y 08_bengala.md. Tratar el guion bajo como
    cursiva se los comeria, y son justo los datos que el usuario tiene que
    copiar tal cual.
    """
    kb = KBFalsa([ResultadoFalso("08_bengala.md")])
    r = correr(kb, IAFalsa("Ajusta Tiempo_Bomba y mira 08_bengala.md o Group_ID."))

    assert "Tiempo_Bomba" in r.texto
    assert "08_bengala.md" in r.texto
    assert "Group_ID" in r.texto


def test_la_fuente_no_viene_dentro_del_texto():
    """
    Viaja en `fuentes`, y ponerla tambien en el parrafo hacia que la app la
    pintase dos veces: una en el texto y otra en su chip.
    """
    kb = KBFalsa([ResultadoFalso("08_bengala.md")])
    r = correr(kb, IAFalsa("Pulsa el boton 3 s."))

    assert "(Fuente:" not in r.texto
    assert r.texto == "Pulsa el boton 3 s."
    assert r.fuentes == ["08_bengala.md"]
    assert knowledge_qa.pista_de_fuentes(r.fuentes) == "bengala"


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
