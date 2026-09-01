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
import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional

from config import config
from escalation_handler import NO_INFO_SENTINEL, build_escalation_message

logger = logging.getLogger(__name__)


@dataclass
class RespuestaConocimiento:
    """Lo que hay que decirle al usuario, mas lo que hay que registrar."""

    texto: str
    #: "rag" contesto la documentacion · "escalation" toca soporte ·
    #: "fallback" el servicio no estaba · "error" estaba y reventó.
    tipo: str
    ok: bool
    error: Optional[str] = None
    fuentes: List[str] = field(default_factory=list)
    scores: List[float] = field(default_factory=list)


def _pista_de_fuentes(archivos: List[str]) -> str:
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
) -> RespuestaConocimiento:
    """
    Busca en la documentacion y contesta. No lanza: los fallos vuelven como una
    RespuestaConocimiento con `ok=False`, porque quien llama siempre tiene que
    tener algo que decirle al usuario.
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

        respuesta = await ai_handler.chat_with_context(
            pregunta, [r.chunk.text for r in resultados]
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

        pista = _pista_de_fuentes(fuentes)
        logger.info("📚 RAG respuesta para '%s' (fuentes: %s)", pregunta[:40], pista)

        return RespuestaConocimiento(
            texto=f"{respuesta}\n\n(Fuente: {pista})",
            tipo="rag",
            ok=True,
            fuentes=fuentes,
            scores=scores,
        )

    except Exception as e:
        logger.error("📚 Error en RAG chat: %s", e)
        return RespuestaConocimiento(
            texto="Hubo un error procesando tu pregunta. Intenta de nuevo.",
            # "error" y no "fallback": son cosas distintas en el registro de
            # interacciones. "fallback" es que el servicio no estaba; "error" es
            # que estaba y reventó. Mezclarlos ensucia el analisis.
            tipo="error",
            ok=False,
            error=f"{type(e).__name__}: {e}",
        )
