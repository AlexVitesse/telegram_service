"""
AI Handler - Dual Backend (Ollama / Groq)
==========================================
Interpreta mensajes en lenguaje natural y genera respuestas
conversacionales usando RAG. Soporta Ollama (local) como backend
principal y Groq como fallback opcional.
"""
import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt para intent parsing
# ---------------------------------------------------------------------------
INTENT_SYSTEM_PROMPT = """Eres el asistente de un sistema de alarma de seguridad llamado SentinelGuard.
Tu función es interpretar mensajes en español y convertirlos en intenciones estructuradas.

Responde SOLO con JSON válido, sin texto adicional, con este formato exacto:
{
  "intent": "<accion>",
  "device": "<nombre o 'all' o null>",
  "confidence": <0.0 a 1.0>,
  "reply": "<mensaje amigable al usuario en español>",
  "params": {}
}

Valores válidos para "intent":
- "arm"          → activar / armar / encender alarma
- "disarm"       → desactivar / desarmar / apagar alarma
- "status"       → consultar estado actual de un dispositivo
- "stop_alarm"   → detener / silenciar sirena / alarma sonando
- "list_devices" → preguntar cuántos dispositivos hay, listarlos, cuáles tengo
- "last_event"   → preguntar cuándo fue la última alarma / evento reciente
- "trigger_bengala" → activar bengala / señal / disparo / flare
- "schedule"       → configurar horario automático de armado/desarmado
- "query_schedule" → consultar / ver qué horarios están configurados actualmente
- "question"       → el usuario quiere información, ayuda, explicación, pregunta algo sobre el sistema (NO es un comando)
- "unknown"        → el mensaje no tiene relación con el sistema de alarma

Para "device":
- Usa el nombre exacto del dispositivo si se menciona específicamente.
- Usa "all" si el usuario dice "todo", "todas", "el sistema" o no especifica.
- Usa null si el intent es "unknown" o "question".

Para intent "schedule", agrega en "params":
{
  "enabled": true,
  "on_hour": <hora armado 0-23>,
  "on_minute": <minuto armado 0-59>,
  "off_hour": <hora desarmado 0-23>,
  "off_minute": <minuto desarmado 0-59>,
  "days": [<índices>]
}
Días: 0=Domingo, 1=Lunes, 2=Martes, 3=Miércoles, 4=Jueves, 5=Viernes, 6=Sábado
Ejemplo: "lunes a viernes" → [1,2,3,4,5] | "todos los días" → [0,1,2,3,4,5,6]
Horarios en formato 24h. "10pm" → on_hour=22, on_minute=0.

Reglas de confianza:
- Mayor a 0.85 si el intent es muy claro.
- Entre 0.6 y 0.85 si hay ambigüedad.
- Menor a 0.6 si no estás seguro — en ese caso usa intent "unknown".

IMPORTANTE:
- Si el usuario PREGUNTA cómo hacer algo, pide explicación o ayuda → intent "question".
- Si el usuario ORDENA hacer algo (activar, desactivar, etc.) → intent correspondiente.
- Ejemplos de "question": "cómo configuro la bengala?", "qué es el modo pregunta?", "cómo agrego un usuario?"
- Ejemplos de comando: "activa la alarma", "apaga el sistema", "arma todo"
- Si el mensaje es un saludo sin relación con alarmas → intent "unknown".
- El campo "reply" debe ser una respuesta corta y amigable en español.
- Siempre incluye "params": {} aunque esté vacío.
"""

# ---------------------------------------------------------------------------
# Prompt para RAG chat
# ---------------------------------------------------------------------------
RAG_CHAT_PROMPT = """Eres el asistente del sistema de alarma SentinelGuard.
Respondes preguntas de los usuarios usando SOLO la documentación proporcionada.

Reglas:
- Responde en español, de forma clara y concisa.
- Si la documentación no contiene la respuesta, di que no tienes esa información y sugiere usar /help o contactar al administrador.
- No inventes información que no esté en la documentación.
- Usa formato simple (sin markdown complejo, ya que es para Telegram).
- Sé amigable y útil.
- Respuestas cortas: máximo 3-4 oraciones a menos que el usuario pida más detalle.
"""


class AIHandler:
    """
    Procesa mensajes de texto libre via Ollama (principal) o Groq (fallback).
    Soporta intent parsing y respuestas conversacionales con RAG.
    """

    def __init__(
        self,
        llm_backend: str = "ollama",
        ollama_base_url: str = "http://localhost:11434",
        ollama_model: str = "gtp-oss:20b",
        groq_api_key: str = "",
        groq_model: str = "llama-3.1-8b-instant",
    ):
        self._backend = llm_backend
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_model = ollama_model
        self._groq_api_key = groq_api_key
        self._groq_model = groq_model
        self._groq_client = None
        self._http_client: Optional[httpx.AsyncClient] = None

        # Inicializar Groq si hay API key (para fallback)
        if groq_api_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=groq_api_key)
            except ImportError:
                logger.warning("🤖 Paquete 'groq' no instalado, fallback Groq deshabilitado")

        logger.info(
            "🤖 AI Handler inicializado — backend: %s | modelo: %s%s",
            self._backend,
            self._ollama_model if self._backend == "ollama" else self._groq_model,
            " (fallback Groq disponible)" if self._groq_client else "",
        )

    async def _ensure_http_client(self):
        """Crea el cliente HTTP async si no existe."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    async def _call_ollama(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> str:
        """Llama a Ollama REST API."""
        await self._ensure_http_client()
        response = await self._http_client.post(
            f"{self._ollama_base_url}/api/chat",
            json={
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                },
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"].strip()

    async def _call_groq(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> str:
        """Llama a Groq API (bloqueante, envuelta en thread)."""
        if not self._groq_client:
            raise RuntimeError("Groq client no disponible")

        def _blocking_call():
            resp = self._groq_client.chat.completions.create(
                model=self._groq_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

        return await asyncio.to_thread(_blocking_call)

    async def _call_llm(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 512) -> str:
        """
        Llama al LLM configurado. Si falla el principal, intenta el fallback.
        """
        if self._backend == "ollama":
            try:
                return await self._call_ollama(system_prompt, user_prompt, temperature, max_tokens)
            except Exception as e:
                logger.warning("🤖 Ollama falló (%s), intentando fallback Groq...", e)
                if self._groq_client:
                    return await self._call_groq(system_prompt, user_prompt, temperature, max_tokens)
                raise
        else:
            # Backend groq
            try:
                return await self._call_groq(system_prompt, user_prompt, temperature, max_tokens)
            except Exception as e:
                logger.warning("🤖 Groq falló (%s), intentando fallback Ollama...", e)
                return await self._call_ollama(system_prompt, user_prompt, temperature, max_tokens)

    # ------------------------------------------------------------------
    # Intent parsing
    # ------------------------------------------------------------------

    async def parse_intent(
        self,
        user_message: str,
        devices: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Interpreta el mensaje del usuario y retorna una intención estructurada.

        Args:
            user_message: El texto enviado por el usuario.
            devices: Lista de dispositivos con id, name, is_armed, is_online.

        Returns:
            Dict con keys: intent, device, confidence, reply, params.
            None si hay error o confidence < 0.6.
        """
        if devices:
            device_lines = "\n".join(
                f"- \"{d.get('name') or d.get('id', 'Desconocido')}\" "
                f"({'armado' if d.get('is_armed') else 'desarmado'}, "
                f"{'en línea' if d.get('is_online') else 'offline'})"
                for d in devices
            )
        else:
            device_lines = "- Sin dispositivos registrados"

        user_prompt = (
            f"Dispositivos disponibles:\n{device_lines}\n\n"
            f"Mensaje del usuario: \"{user_message}\""
        )

        try:
            raw = await self._call_llm(
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.1,
                max_tokens=256,
            )
            logger.debug("🤖 Respuesta LLM (intent): %s", raw)

            # Extraer JSON de la respuesta (por si viene con texto extra)
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                raw = json_match.group()

            result = json.loads(raw)

            required_keys = {"intent", "device", "confidence", "reply"}
            if not required_keys.issubset(result.keys()):
                logger.warning("🤖 Respuesta LLM incompleta: %s", result)
                return None

            if result["confidence"] < 0.6:
                logger.info(
                    "🤖 Confianza baja (%.2f) para intent '%s' — ignorado",
                    result["confidence"],
                    result["intent"],
                )
                return None

            logger.info(
                "🤖 Intent: '%s' | device: '%s' | confianza: %.2f | backend: %s",
                result["intent"],
                result["device"],
                result["confidence"],
                self._backend,
            )
            return result

        except json.JSONDecodeError:
            logger.warning("🤖 Respuesta LLM no es JSON válido: %s", raw)
            return None
        except Exception as e:
            logger.error("🤖 Error en LLM (parse_intent): %s", e)
            return None

    # ------------------------------------------------------------------
    # RAG chat
    # ------------------------------------------------------------------

    async def chat_with_context(self, user_message: str, context_chunks: List[str]) -> str:
        """
        Genera una respuesta conversacional usando documentación como contexto.

        Args:
            user_message: La pregunta del usuario.
            context_chunks: Fragmentos de documentación relevantes.

        Returns:
            Respuesta generada por el LLM.
        """
        context_text = "\n\n---\n\n".join(context_chunks)
        user_prompt = (
            f"Documentación relevante:\n{context_text}\n\n"
            f"Pregunta del usuario: {user_message}"
        )

        try:
            answer = await self._call_llm(
                system_prompt=RAG_CHAT_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=512,
            )
            logger.info("🤖 RAG chat respondido (%d chars) | backend: %s", len(answer), self._backend)
            return answer
        except Exception as e:
            logger.error("🤖 Error en LLM (chat_with_context): %s", e)
            return "Lo siento, hubo un error procesando tu pregunta. Intenta de nuevo o usa /help."

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        """Cierra el cliente HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            logger.info("🤖 AI Handler HTTP client cerrado")
