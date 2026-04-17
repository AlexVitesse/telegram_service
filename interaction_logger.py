"""
Interaction Logger - Log estructurado de preguntas y respuestas del bot AI.

Escribe en formato JSON Lines (.jsonl) para poder analizar posteriormente
con herramientas como jq, pandas o scripts simples.

Cada linea es un JSON autonomo con:
    timestamp       ISO-8601 con timezone local
    user_id         Telegram user id (chat_id)
    user_name       Nombre del usuario (para legibilidad)
    query           Texto enviado por el usuario
    intent          Intent detectado (arm, disarm, question, unknown, etc.)
    confidence      Confianza del LLM en el intent (0.0-1.0)
    backend         Backend usado (ollama / groq)
    response_type   "action" | "rag" | "fallback" | "error"
    response        Texto enviado al usuario (truncado a 2000 chars)
    rag_sources     Lista de fuentes usadas (para intents question)
    rag_scores      Scores de relevancia de los chunks RAG
    elapsed_ms      Tiempo total de procesamiento en milisegundos
    ok              True si la respuesta se considero util
    error           Mensaje de error si ok=False
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    timestamp: str
    user_id: str
    user_name: str
    query: str
    intent: Optional[str] = None
    confidence: Optional[float] = None
    backend: Optional[str] = None
    response_type: str = "action"  # action | rag | fallback | error
    response: str = ""
    rag_sources: List[str] = field(default_factory=list)
    rag_scores: List[float] = field(default_factory=list)
    elapsed_ms: Optional[int] = None
    ok: bool = True
    error: Optional[str] = None


class InteractionLogger:
    """Escribe interacciones AI en un archivo JSONL thread-safe."""

    def __init__(self, log_path: str):
        self.log_path = log_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
        logger.info("📝 Interaction logger activo: %s", self.log_path)

    def log(self, interaction: Interaction) -> None:
        """Escribe una interaccion en el archivo. Nunca levanta excepcion."""
        try:
            line = json.dumps(asdict(interaction), ensure_ascii=False)
            with self._lock, open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            # Nunca romper el bot por fallar el logging
            logger.warning("📝 InteractionLogger falló: %s", e)

    def record(
        self,
        user_id: str,
        user_name: str,
        query: str,
        *,
        intent: Optional[str] = None,
        confidence: Optional[float] = None,
        backend: Optional[str] = None,
        response_type: str = "action",
        response: str = "",
        rag_sources: Optional[List[str]] = None,
        rag_scores: Optional[List[float]] = None,
        elapsed_ms: Optional[int] = None,
        ok: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Atajo para construir y escribir una Interaction en una sola llamada."""
        truncated = response if len(response) <= 2000 else response[:1997] + "..."
        entry = Interaction(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            user_id=str(user_id),
            user_name=user_name or "",
            query=query,
            intent=intent,
            confidence=confidence,
            backend=backend,
            response_type=response_type,
            response=truncated,
            rag_sources=rag_sources or [],
            rag_scores=rag_scores or [],
            elapsed_ms=elapsed_ms,
            ok=ok,
            error=error,
        )
        self.log(entry)
