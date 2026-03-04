"""
AI Handler - Integración con Groq
==================================
Interpreta mensajes en lenguaje natural del usuario y los convierte
en intenciones estructuradas para ejecutar comandos del sistema de alarma.
"""
import json
import logging
from typing import Optional, Dict, Any, List

from groq import Groq

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt del sistema
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """Eres el asistente de un sistema de alarma de seguridad llamado SentinelGuard.
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
- "unknown"        → el mensaje no tiene relación con el sistema de alarma

Para "device":
- Usa el nombre exacto del dispositivo si se menciona específicamente.
- Usa "all" si el usuario dice "todo", "todas", "el sistema" o no especifica.
- Usa null solo si el intent es "unknown".

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
- Si el mensaje es un saludo, pregunta general o no relacionado con alarmas → intent "unknown".
- El campo "reply" debe ser una respuesta corta y amigable en español confirmando lo que vas a hacer.
- Siempre incluye "params": {} aunque esté vacío.
"""


class AIHandler:
    """
    Procesa mensajes de texto libre via Groq y retorna intenciones estructuradas.
    """

    def __init__(self, api_key: str):
        self.client = Groq(api_key=api_key)
        self.model = "llama-3.1-8b-instant"
        logger.info("🤖 AI Handler inicializado con Groq (modelo: %s)", self.model)

    def parse_intent(
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
            Dict con keys: intent, device, confidence, reply.
            None si hay error o confidence < 0.6.
        """
        # Construir lista de dispositivos para el contexto
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=256,
            )

            raw = response.choices[0].message.content.strip()
            logger.debug("🤖 Respuesta Groq: %s", raw)

            result = json.loads(raw)

            # Validar estructura mínima
            required_keys = {"intent", "device", "confidence", "reply"}
            if not required_keys.issubset(result.keys()):
                logger.warning("🤖 Respuesta Groq incompleta: %s", result)
                return None

            # Descartar respuestas de baja confianza
            if result["confidence"] < 0.6:
                logger.info(
                    "🤖 Confianza baja (%.2f) para intent '%s' — ignorado",
                    result["confidence"],
                    result["intent"],
                )
                return None

            logger.info(
                "🤖 Intent detectado: '%s' | device: '%s' | confianza: %.2f",
                result["intent"],
                result["device"],
                result["confidence"],
            )
            return result

        except json.JSONDecodeError:
            logger.warning("🤖 Respuesta Groq no es JSON válido: %s", raw)
            return None
        except Exception as e:
            logger.error("🤖 Error en Groq API: %s", e)
            return None
