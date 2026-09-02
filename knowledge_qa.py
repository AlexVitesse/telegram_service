"""
Responder una pregunta con la base de conocimiento. Sin Telegram de por medio.

Este flujo -buscar en el RAG, preguntarle al LLM con esos fragmentos, decidir si
hay que escalar a soporte- vivia dentro de un handler de `telegram_bot.py`,
enredado con `reply_text`, teclados y el registro de interacciones. Sacarlo aqui
permite que lo llame algo que no sea el bot (un endpoint HTTP para la app) y
**responda exactamente igual**, que es el punto: dos respuestas distintas a la
misma pregunta segun el canal serian un bug dificil de ver.

Quien llama decide que hacer con el resultado: el bot lo manda por Telegram, el
endpoint lo serializa a JSON. Los dos registran la interaccion con los mismos
campos, que es para lo que estan `tipo`, `ok`, `error`, `fuentes` y `scores`.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

import httpx

from ai_handler import TEXTO_OCUPADO, LlmOcupado
from config import config
from escalation_handler import NO_INFO_SENTINEL, build_escalation_message

logger = logging.getLogger(__name__)

#: Techo para TODA la respuesta, incluida la cadena de reserva.
#: `_call_llm` intenta un backend y, si falla, el otro: dos timeouts en serie.
#: Sin este techo, el peor caso son 40 s largos antes de decir nada.
_MARGEN_CADENA = 5.0


def _es_transitorio(e: BaseException) -> bool:
    """
    ¿Tiene sentido que el usuario reintente?

    Un timeout o un 503 se arreglan solos; un TypeError no se va a arreglar
    nunca por mucho que insista. Decirle "intenta de nuevo" a alguien cuyo
    reintento no puede funcionar es mandarlo a dar vueltas.
    """
    if isinstance(e, (asyncio.TimeoutError, httpx.TimeoutException,
                      httpx.ConnectError, httpx.ReadError)):
        return True

    # El SDK de Groq no se importa aqui -es opcional-, asi que se mira por pato:
    # sus errores llevan el codigo HTTP encima.
    codigo = getattr(e, "status_code", None) or getattr(e, "status", None)
    if isinstance(codigo, int):
        return codigo == 429 or 500 <= codigo <= 599

    return False


@dataclass
class RespuestaConocimiento:
    """Lo que hay que decirle al usuario, mas lo que hay que registrar."""

    texto: str
    #: "rag" contesto la documentacion · "escalation" toca soporte ·
    #: "fallback" el servicio no estaba · "error" estaba y reventó ·
    #: "ocupado" estaba y no daba abasto (reintentar SI sirve).
    tipo: str
    ok: bool
    error: Optional[str] = None
    fuentes: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)


#: Enfasis con asterisco, codigo en linea, titulos y enlaces. Los guiones bajos
#: NO se tocan a proposito: la base de conocimiento habla de `Tiempo_Bomba`,
#: `BengalaHab` o `08_bengala.md`, y tratarlos como cursiva parte los nombres.
_MARKDOWN = (
    (re.compile(r"```[a-zA-Z]*\n?(.*?)```", re.S), r"\1"),   # bloque de codigo
    (re.compile(r"`([^`\n]+)`"), r"\1"),                     # codigo en linea
    (re.compile(r"\*\*([^\n]+?)\*\*"), r"\1"),               # negrita
    (re.compile(r"(?<![\w*])\*(?!\s)([^\n*]+?)(?<!\s)\*(?![\w*])"), r"\1"),  # cursiva
    (re.compile(r"^\s{0,3}#{1,6}\s+", re.M), ""),            # titulo
    (re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)"), r"\1 (\2)"),  # enlace
)


def sin_markdown(texto: str) -> str:
    """
    Quita el marcado que no pinta nadie.

    El LLM contesta en markdown, pero ninguno de los dos canales lo renderiza:
    la app pinta texto plano, y el bot manda ESTA respuesta con `reply_text`
    sin `parse_mode`, a diferencia del resto de sus mensajes. Asi que
    "**/bengala**" llegaba con los asteriscos a los dos sitios.

    Se limpia aqui y no en cada cliente por el mismo motivo por el que existe
    este modulo: que los dos canales contesten exactamente lo mismo.
    """
    for patron, reemplazo in _MARKDOWN:
        texto = patron.sub(reemplazo, texto)
    return texto.strip()


def pista_de_fuentes(archivos: List[str]) -> str:
    """
    "03_bengala_config.md" -> "bengala config"

    Se quitan duplicados conservando el orden de relevancia. Antes se usaba un
    `set`, asi que la misma pregunta podia listar las fuentes en distinto orden
    en cada llamada; es cosmetico, pero desconcierta al comparar respuestas.
    """
    limpios = [
        a.replace(".md", "").lstrip("0123456789_").replace("_", " ")
        for a in archivos
    ]
    return " | ".join(dict.fromkeys(limpios))


async def responder(
    pregunta: str,
    knowledge_base: Any,
    ai_handler: Any,
    timeout: Optional[float] = None,
) -> RespuestaConocimiento:
    """
    Busca en la documentacion y contesta. No lanza: los fallos vuelven como una
    RespuestaConocimiento con `ok=False`, porque quien llama siempre tiene que
    tener algo que decirle al usuario.

    `timeout` es el techo para la llamada al LLM. Sin el se usa el de siempre,
    que es lo que quiere el bot de Telegram: alli no hay un cliente cortando por
    su cuenta. El endpoint HTTP si lo pasa, porque reparte un presupuesto entre
    el clasificador y esta llamada.
    """
    if not knowledge_base or not ai_handler:
        return RespuestaConocimiento(
            texto=(
                "ℹ️ La base de conocimiento no está disponible.\n"
                "Usa /help para ver los comandos."
            ),
            tipo="fallback",
            ok=False,
            error="kb_unavailable",
        )

    try:
        resultados = knowledge_base.search(
            pregunta,
            top_k=config.ai.rag_max_chunks,
            min_score=config.ai.rag_min_score,
        )

        for r in resultados:
            logger.debug(
                "📚 RAG match: score=%.3f | %s > %s",
                r.score, r.chunk.source_file, r.chunk.heading[:50],
            )

        if not resultados:
            return RespuestaConocimiento(
                texto=build_escalation_message("no_results", config.support),
                tipo="escalation",
                ok=False,
                error="rag_no_results",
            )

        fuentes = [r.chunk.source_file for r in resultados]
        scores = [round(r.score, 3) for r in resultados]

        respuesta = await asyncio.wait_for(
            ai_handler.chat_with_context(pregunta, [r.chunk.text for r in resultados]),
            timeout=timeout or config.ai.llm_timeout_sec * 2 + _MARGEN_CADENA,
        )

        # El LLM avisa con este centinela de que los fragmentos no contestaban
        # la pregunta. Inventar es peor que mandar a soporte.
        if NO_INFO_SENTINEL in respuesta:
            return RespuestaConocimiento(
                texto=build_escalation_message("no_results", config.support),
                tipo="escalation",
                ok=False,
                error="llm_no_info",
                fuentes=fuentes,
                scores=scores,
            )

        pista = pista_de_fuentes(fuentes)
        logger.info("📚 RAG respuesta para '%s' (fuentes: %s)", pregunta[:40], pista)

        return RespuestaConocimiento(
            # La fuente NO se mete en el texto: ya viaja en `fuentes`, y ponerla
            # en los dos sitios hacia que la app la pintase dos veces -dentro
            # del parrafo y en su chip-. Quien envie decide como mostrarla.
            texto=sin_markdown(respuesta),
            tipo="rag",
            ok=True,
            fuentes=fuentes,
            scores=scores,
        )

    except LlmOcupado as e:
        # No es un fallo: es que ahora mismo no da abasto. Se separa del resto
        # porque la respuesta es distinta -reintentar en unos segundos SI sirve-
        # y porque el endpoint la convierte en un 503 con `reintentar_en`, que
        # es lo que le permite a la app distinguir "ocupado" de "caido".
        logger.warning("📚 RAG rebotado por la pila: %s", e)
        return RespuestaConocimiento(
            texto=TEXTO_OCUPADO,
            tipo="ocupado",
            ok=False,
            error="llm_ocupado",
        )

    except Exception as e:
        transitorio = _es_transitorio(e)
        logger.error(
            "📚 Error en RAG chat (%s): %s",
            "transitorio" if transitorio else "definitivo", e,
        )

        if transitorio:
            texto = (
                "El asistente tardó demasiado en responder. "
                "Vuelve a intentarlo en un momento."
            )
        else:
            # Reintentar no va a servir: se le da un camino que si lleva a algun
            # sitio en vez de invitarle a repetir lo que acaba de fallar.
            texto = build_escalation_message("llm_error", config.support)

        return RespuestaConocimiento(
            texto=texto,
            # "error" y no "fallback": son cosas distintas en el registro de
            # interacciones. "fallback" es que el servicio no estaba; "error" es
            # que estaba y reventó. Mezclarlos ensucia el analisis.
            tipo="error",
            ok=False,
            error=f"{'transitorio' if transitorio else 'definitivo'}: {type(e).__name__}: {e}",
        )
