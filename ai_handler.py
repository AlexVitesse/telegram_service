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
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger(__name__)

#: Cuantos segundos decirle a quien rebota que espere. Un numero suelto y no
#: configuracion: es una sugerencia para el usuario, no un parametro a ajustar.
ESPERA_SUGERIDA_SEG = 5

#: Lo que se le dice a quien rebota. Vive aqui y no en cada llamador para que
#: los dos canales -bot y endpoint- digan lo mismo.
TEXTO_OCUPADO = (
    "Estoy atendiendo otras consultas en este momento. "
    "Vuelve a preguntarme en unos segundos."
)


class LlmOcupado(RuntimeError):
    """
    La pila esta llena: hay tantas llamadas esperando turno que encolar una mas
    solo serviria para que expirase haciendo cola.

    Es distinto de un timeout y de un backend caido: aqui el servicio funciona,
    solo que ahora mismo no da abasto, y reintentar en unos segundos si tiene
    sentido. Quien la reciba deberia decirlo asi.
    """


def _no_merece_reserva(e: BaseException) -> bool:
    """
    ¿Es un fallo que hace inutil probar el otro backend?

    Un 503 o una conexion rehusada son instantaneos y al otro backend le queda
    todo el tiempo por delante: ahi la reserva vale. Un **timeout** no: ya te
    gastaste el presupuesto esperando, y repetirlo entero es cobrarselo dos
    veces al mismo usuario. Con la pila delante es ademas quitarle el sitio a
    otro que si podia llegar.

    `LlmOcupado` tampoco: la pila la comparten los dos backends, asi que si esta
    llena para uno lo esta para el otro.
    """
    return isinstance(
        e, (LlmOcupado, asyncio.TimeoutError, httpx.TimeoutException)
    )


def _looks_like_ollama_model(name: str) -> bool:
    return ":" in name


def _looks_like_groq_model(name: str) -> bool:
    n = name.lower()
    return "instant" in n or n.startswith("groq/") or n.startswith("openai/")

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
- "complaint"      → el usuario tiene una queja, reclamo, expresa frustracion, o pide explicitamente hablar con una persona / agente humano / soporte humano
- "unknown"        → el mensaje no tiene relación con el sistema de alarma

Para "device":
- Usa el nombre exacto del dispositivo si se menciona específicamente.
- Usa "all" si el usuario dice "todo", "todas", "el sistema" o no especifica.
- Usa null si el intent es "unknown", "question" o "complaint".

Para intent "schedule" hay TRES variantes segun lo que pida el usuario:

A) CONFIGURAR un horario nuevo (el usuario da horas concretas):
   "params": {
     "enabled": true,
     "on_hour": <hora armado 0-23>,
     "on_minute": <minuto armado 0-59>,
     "off_hour": <hora desarmado 0-23>,
     "off_minute": <minuto desarmado 0-59>,
     "days": [<índices>]
   }

B) DESACTIVAR el horario automatico existente (sin cambiar horas):
   "params": { "enabled": false }
   Ejemplos: "desactiva horarios", "apaga el horario automatico", "quita la programacion", "deshabilita el horario".

C) ACTIVAR el horario automatico existente (sin cambiar horas):
   "params": { "enabled": true }
   Ejemplos: "activa horarios", "enciende el horario automatico", "rehabilita la programacion".

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
- Ejemplos de "complaint": "tengo una queja", "esto no me sirve", "quiero hablar con una persona", "necesito un humano", "esto es pesimo".
- Ejemplos de comando: "activa la alarma", "apaga el sistema", "arma todo"
- Si la pregunta es sobre HORARIOS y es de CONSULTA (verbos: "ver", "muestra", "cual es", "que horario", "como esta", "consulta"), usa "query_schedule". Ejemplos: "Horarios?", "que horario tiene Estudio?", "muestrame los horarios", "como esta el horario".
- Si la pregunta es sobre HORARIOS y es para DESACTIVAR / APAGAR / DESHABILITAR / QUITAR, usa "schedule" con params {"enabled": false}. Ejemplos: "desactiva horarios", "apaga el horario automatico", "quita la programacion".
- Si la pregunta es sobre HORARIOS y es para ACTIVAR / ENCENDER / HABILITAR el horario existente SIN dar nuevas horas, usa "schedule" con params {"enabled": true}. Ejemplos: "activa horarios", "enciende el horario automatico".
- Si la pregunta es sobre HORARIOS y da HORAS concretas para configurarlos, usa "schedule" con todos los params (variante A).
- Si la pregunta es sobre ESTADO de armado (contiene "esta armada", "esta activa", "cual es el estado", "como esta"), usa intent "status". Ejemplos: "como esta la alarma?", "esta armada la casa?", "que alarma esta activada?".
- Si el mensaje es un saludo sin relación con alarmas → intent "unknown".
- El campo "reply" debe ser una respuesta corta y amigable en español.
- Siempre incluye "params": {} aunque esté vacío.
"""

# ---------------------------------------------------------------------------
# Prompt para RAG chat
# ---------------------------------------------------------------------------
RAG_CHAT_PROMPT = """Eres el asistente del sistema de alarma SentinelGuard.
Responde preguntas usando EXCLUSIVAMENTE la documentación que aparece abajo.

REGLAS ESTRICTAS:
- SOLO usa información que aparece en la documentación proporcionada abajo.
- NUNCA inventes comandos, funciones, pasos o características que no estén en la documentación.
- Si algo no está en la documentación, responde EXACTAMENTE con el texto: NO_INFO_AVAILABLE (sin nada mas, sin explicaciones).
- Responde en español, claro y conciso.
- Formato de texto plano. Sin asteriscos, sin guiones bajos, sin markdown.
- Da respuestas COMPLETAS. No cortes la respuesta a la mitad.

PRECISION OBLIGATORIA:
- Cuando la documentación mencione numeros especificos (distancias, angulos, tiempos, codigos, contrasenas), SIEMPRE incluyelos textualmente. Ejemplo: "110 grados", "7 metros", "1234", "3 intentos".
- Cuando la documentación liste pasos o procedimientos, reproducilos fielmente en el mismo orden. No parafrasees ni resumas los pasos.
- Incluye comandos exactos tal como aparecen: /bengala, /adduser, /horarios, etc.
- Incluye valores por defecto y codigos especificos: contrasena default 1234, tecla #, etc.
- Cita las especificaciones tecnicas tal cual: angulo de deteccion, rango, altura de montaje, etc.
- NO parafrasees la documentación. Usa las mismas palabras y valores que aparecen en ella.
"""

# ---------------------------------------------------------------------------
# Prompt para modo vendedor (usuarios NO registrados)
# ---------------------------------------------------------------------------
SALES_CHAT_PROMPT = """Sos un asesor comercial del sistema de alarma SentinelGuard.
Hablas con alguien que aun NO tiene el sistema. Tu objetivo es:
1. Explicar como funciona y por que es util (con datos reales de la documentacion).
2. Despejar dudas tecnicas o practicas.
3. Invitar a comprar / pedir mas info al final de cada respuesta.

REGLAS ESTRICTAS:
- SOLO usa informacion que aparece en la documentacion proporcionada abajo.
- NUNCA inventes caracteristicas que no esten en la documentacion.
- Tono cordial, cercano, en espanol rioplatense (vos, podes). No uses jerga tecnica innecesaria.
- Formato de texto plano, SIN markdown (sin asteriscos, sin guiones bajos).
- Respuestas concisas: 3-6 lineas idealmente. Esto es un chat, no un brochure.

PROHIBICIONES:
- NUNCA des precios, costos ni planes — todavia no estan publicados.
  Si preguntan precio, costo, valor, cuanto sale: redirigi al email/landing.
- NUNCA menciones comandos del bot (/on, /off, /status, /bengala, etc).
  Esos son para usuarios ya registrados con el sistema instalado.
- NUNCA menciones detalles tecnicos internos: Firebase, MQTT, broker, VPS,
  arquitectura del backend. Hablale de la experiencia del usuario.
- Si la pregunta NO se relaciona con SentinelGuard (saludos vacios, off-topic),
  responde brevemente quien sos y volve al tema. No mantengas conversacion off-topic.

CIERRE OBLIGATORIO:
Toda respuesta termina con un CTA breve al final, separado por una linea en blanco.
Los datos de contacto te los paso en la documentacion abajo bajo el bloque [CONTACTO].
Usalos textuales (email, link App Store, landing si esta disponible).
Variantes aceptables del CTA:
- "Para empezar, descargá la app o escribinos a {email}."
- "Si te interesa adquirir el equipo, escribinos a {email}."
- "Mas info y contacto: {email}."
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
        ollama_model: str = "gpt-oss:20b",
        groq_api_key: str = "",
        groq_model: str = "llama-3.1-8b-instant",
        intent_model: str = "",
        chat_model: str = "",
        timeout_sec: float = 20.0,
        max_concurrent: int = 2,
        max_cola: int = 8,
    ):
        self._backend = llm_backend
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_model = ollama_model
        self._groq_api_key = groq_api_key
        self._groq_model = groq_model
        # Modelos específicos por tarea (si no se especifican, usan el default del backend)
        default_task_model = ollama_model if llm_backend == "ollama" else groq_model
        self._intent_model = intent_model or default_task_model
        self._chat_model = chat_model or default_task_model
        self._groq_client = None
        self._http_client: Optional[httpx.AsyncClient] = None
        self._timeout_sec = timeout_sec

        # La pila. Sin esto no habia NADA que limitase cuantas llamadas al LLM
        # hay en vuelo: con Ollama, que las serializa en su propia cola, diez a
        # la vez significa que las diez expiran juntas mientras la maquina sigue
        # generando texto que ya nadie va a leer.
        self._pila = asyncio.Semaphore(max_concurrent)
        self._max_cola = max_cola
        self._en_cola = 0

        # Detectar configuración incompatible: backend=ollama con modelos de Groq
        if llm_backend == "ollama":
            for label, model in (("intent", self._intent_model), ("chat", self._chat_model)):
                if _looks_like_groq_model(model) and not _looks_like_ollama_model(model):
                    logger.warning(
                        "🤖 %s_model='%s' parece ser un modelo de Groq pero backend=ollama. "
                        "Usando ollama_model='%s' como fallback automatico.",
                        label, model, ollama_model,
                    )
                    if label == "intent":
                        self._intent_model = ollama_model
                    else:
                        self._chat_model = ollama_model

        # Inicializar Groq si hay API key (para fallback)
        if groq_api_key:
            try:
                from groq import Groq
                # El timeout aqui NO es opcional: _call_groq corre dentro de un
                # asyncio.to_thread, y un to_thread no se puede cancelar. Sin
                # techo en el SDK, una llamada colgada deja el hilo colgado y la
                # peticion no vuelve nunca.
                self._groq_client = Groq(api_key=groq_api_key, timeout=timeout_sec)
            except ImportError:
                logger.warning("🤖 Paquete 'groq' no instalado, fallback Groq deshabilitado")

        logger.info(
            "🤖 AI Handler — backend: %s | intent: %s | chat: %s%s",
            self._backend,
            self._intent_model,
            self._chat_model,
            " (fallback Groq)" if self._groq_client else "",
        )

    async def _ensure_http_client(self):
        """Crea el cliente HTTP async si no existe."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout_sec)

    @asynccontextmanager
    async def _turno(self):
        """
        Espera sitio en la pila, o rebota si la cola ya es demasiado larga.

        Envuelve las llamadas REALES -`_call_ollama` y `_call_groq`- y no
        `_call_llm`, para que ninguna via se escape: ni la cadena de reserva de
        `_call_llm`, ni el reintento contra Groq que `parse_intent` hace por su
        cuenta cuando el JSON viene invalido.

        El limite de cola no es un adorno. Un semaforo sin el solo mueve el
        atasco: la peticion espera turno, se le acaba el techo mientras espera,
        y el usuario recibe un timeout DESPUES de haber ocupado sitio. Rebotar
        en 0 ms con un "estoy ocupado" es mas honesto y ademas mas barato.

        Se espera dentro del `wait_for` que ya tiene puesto cada llamador, asi
        que el techo sigue cubriendo la espera y no hace falta uno nuevo.
        """
        if self._en_cola >= self._max_cola:
            logger.warning(
                "🤖 Pila llena (%d esperando): rebotando la consulta",
                self._en_cola,
            )
            raise LlmOcupado("hay demasiadas consultas en cola")

        self._en_cola += 1
        try:
            async with self._pila:
                yield
        finally:
            self._en_cola -= 1

    # ------------------------------------------------------------------
    # LLM calls
    # ------------------------------------------------------------------

    async def _call_ollama(self, system_prompt: str, user_prompt: str, model: str = "", temperature: float = 0.1, max_tokens: int = 512) -> str:
        """Llama a Ollama REST API."""
        await self._ensure_http_client()
        effective_model = model or self._ollama_model
        async with self._turno():
            response = await self._http_client.post(
                f"{self._ollama_base_url}/api/chat",
                json={
                    "model": effective_model,
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
        body = response.json()
        if "error" in body:
            logger.error("🤖 Ollama error (model=%s): %s", effective_model, body["error"])
            raise RuntimeError(f"Ollama error: {body['error']}")
        content = body.get("message", {}).get("content", "").strip()
        if not content:
            logger.error(
                "🤖 Ollama respondió vacío (model=%s). Body: %s",
                effective_model,
                json.dumps(body, ensure_ascii=False)[:1000],
            )
            raise RuntimeError(f"Ollama empty response (model={effective_model})")
        return content

    async def _call_groq(self, system_prompt: str, user_prompt: str, model: str = "", temperature: float = 0.1, max_tokens: int = 512) -> str:
        """Llama a Groq API (bloqueante, envuelta en thread)."""
        if not self._groq_client:
            raise RuntimeError("Groq client no disponible")

        use_model = model or self._groq_model

        def _blocking_call():
            resp = self._groq_client.chat.completions.create(
                model=use_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            contenido = (resp.choices[0].message.content or "").strip()
            if not contenido:
                # Mismo guard que `_call_ollama`. Sin el, una respuesta vacia
                # sube como respuesta valida y el usuario recibe un mensaje que
                # solo dice "(Fuente: ...)": vacio con pinta de haber
                # funcionado. Visto en produccion.
                raise RuntimeError(f"Groq empty response (model={use_model})")
            return contenido

        async with self._turno():
            return await asyncio.to_thread(_blocking_call)

    async def _call_llm(self, system_prompt: str, user_prompt: str, model: str = "", temperature: float = 0.1, max_tokens: int = 512) -> str:
        """
        Llama al LLM configurado. Si falla el principal, intenta el fallback.
        El model se pasa al backend principal. El fallback usa su modelo default.
        """
        if self._backend == "ollama":
            try:
                return await self._call_ollama(system_prompt, user_prompt, model, temperature, max_tokens)
            except Exception as e:
                if _no_merece_reserva(e):
                    raise
                logger.warning("🤖 Ollama falló (%s), intentando fallback Groq...", e)
                if self._groq_client:
                    # Fallback: usar modelo default de Groq, no el de Ollama
                    return await self._call_groq(system_prompt, user_prompt, "", temperature, max_tokens)
                raise
        else:
            # Backend groq
            try:
                return await self._call_groq(system_prompt, user_prompt, model, temperature, max_tokens)
            except Exception as e:
                if _no_merece_reserva(e):
                    raise
                logger.warning("🤖 Groq falló (%s), intentando fallback Ollama...", e)
                # Fallback: usar modelo default de Ollama, no el de Groq
                return await self._call_ollama(system_prompt, user_prompt, "", temperature, max_tokens)

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

        raw = ""
        try:
            raw = await self._call_llm(
                system_prompt=INTENT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                model=self._intent_model,
                temperature=0.1,
                max_tokens=256,
            )
            logger.debug("🤖 Respuesta LLM (intent) model=%s: %s", self._intent_model, raw)

            result = self._parse_intent_json(raw)
            if result is None:
                # Fallback a Groq si es posible y aún no hemos fallado a Groq
                if self._backend == "ollama" and self._groq_client:
                    logger.warning(
                        "🤖 Intent JSON invalido de Ollama (raw=%r). Reintentando con Groq...",
                        raw[:500],
                    )
                    raw = await self._call_groq(
                        system_prompt=INTENT_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        model="",
                        temperature=0.1,
                        max_tokens=256,
                    )
                    logger.debug("🤖 Respuesta LLM (intent/groq-fallback): %s", raw)
                    result = self._parse_intent_json(raw)

            if result is None:
                logger.warning("🤖 Respuesta LLM no es JSON valido: %r", raw[:500])
                return None

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

        except LlmOcupado:
            # NO se convierte en None. Un None aqui significa "no era una
            # orden", y el llamador sigue al RAG: bajo carga, "arma la alarma"
            # volveria como un parrafo de documentacion en vez de como orden,
            # que es exactamente el fallo que este endpoint vino a arreglar.
            # Que suba y que lo conteste quien sepa decir "estoy ocupado".
            raise
        except Exception as e:
            logger.error("🤖 Error en LLM (parse_intent): %s | raw=%r", e, raw[:500])
            return None

    @staticmethod
    def _parse_intent_json(raw: str) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            return None
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
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
                model=self._chat_model,
                temperature=0.3,
                max_tokens=1024,
            )
            logger.info("🤖 RAG chat respondido (%d chars) | backend: %s", len(answer), self._backend)
            return answer
        except Exception as e:
            logger.error("🤖 Error en LLM (chat_with_context): %s", e)
            return "Lo siento, hubo un error procesando tu pregunta. Intenta de nuevo o usa /help."

    # ------------------------------------------------------------------
    # Modo vendedor (usuarios NO registrados)
    # ------------------------------------------------------------------

    async def chat_sales(
        self,
        user_message: str,
        context_chunks: List[str],
        *,
        support_email: str = "",
        app_store_url: str = "",
        landing_url: str = "",
    ) -> str:
        """
        Genera una respuesta en modo vendedor para alguien que aun no
        tiene el sistema. Reutiliza la KB existente pero con SALES_CHAT_PROMPT
        que enfoca la respuesta hacia el cierre comercial.

        Args:
            user_message: pregunta del prospecto.
            context_chunks: fragmentos relevantes de la knowledge base.
            support_email: email de soporte (se inyecta en el bloque [CONTACTO]).
            app_store_url: link a la app en App Store.
            landing_url: link al landing (opcional).

        Returns:
            Respuesta generada por el LLM con CTA de cierre.
        """
        context_text = "\n\n---\n\n".join(context_chunks) if context_chunks else "(Sin documentacion relevante encontrada — respondé desde principios generales del producto sin inventar caracteristicas.)"

        contact_lines = []
        if support_email:
            contact_lines.append(f"Email: {support_email}")
        if app_store_url:
            contact_lines.append(f"App Store: {app_store_url}")
        if landing_url:
            contact_lines.append(f"Landing: {landing_url}")
        contact_block = "\n".join(contact_lines) if contact_lines else "(Sin canales de contacto configurados.)"

        user_prompt = (
            f"Documentacion del producto:\n{context_text}\n\n"
            f"[CONTACTO — usar textualmente al cerrar la respuesta]\n{contact_block}\n\n"
            f"Pregunta del prospecto: {user_message}"
        )

        try:
            answer = await self._call_llm(
                system_prompt=SALES_CHAT_PROMPT,
                user_prompt=user_prompt,
                model=self._chat_model,
                temperature=0.5,  # mas creativo que el RAG estricto, pero no inventa
                max_tokens=600,
            )
            logger.info("🛒 Sales chat respondido (%d chars) | backend: %s", len(answer), self._backend)
            return answer
        except Exception as e:
            logger.error("🛒 Error en LLM (chat_sales): %s", e)
            # Fallback minimo con el contacto en duro
            fallback = (
                "Disculpá, no pude procesar tu consulta en este momento. "
                "Si querés mas info sobre SentinelGuard:"
            )
            if support_email:
                fallback += f"\nEscribinos a {support_email}"
            if app_store_url:
                fallback += f"\nDescargá la app: {app_store_url}"
            return fallback

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        """Cierra el cliente HTTP."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            logger.info("🤖 AI Handler HTTP client cerrado")
