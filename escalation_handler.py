"""
Escalation Handler
==================
Genera el mensaje que el bot envia al usuario cuando no puede resolver
una consulta (RAG vacio, LLM sin info, queja, o pedido explicito de
soporte humano). Toma los datos de contacto desde config.support
(SUPPORT_EMAIL / SUPPORT_PHONE / SUPPORT_HOURS en .env).

El bot NO envia correos ni notifica al admin: solo le da al usuario
los medios para contactar a una persona.
"""
from __future__ import annotations

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import SupportConfig


# Sentinel que el LLM emite cuando no encuentra info en la KB.
# Lo intercepta _handle_rag_chat para reemplazarlo por la escalacion real.
NO_INFO_SENTINEL = "NO_INFO_AVAILABLE"

# Frases que indican queja o pedido explicito de hablar con una persona.
# Se usa como red de seguridad si el LLM no clasifica como intent "complaint".
COMPLAINT_KEYWORDS = (
    "queja", "quejarme", "reclamo", "reclamar",
    "muy mal", "pesimo", "malisimo", "horrible",
    "no me sirve", "no me funciona nada", "esto es un desastre",
    "hablar con una persona", "hablar con un humano", "hablar con alguien",
    "agente humano", "soporte humano", "atencion humana",
    "necesito una persona", "necesito un humano",
    "comunicarme con", "contactar a alguien",
)


# Encabezado por motivo de escalacion. La parte de contacto se anexa abajo.
_REASON_HEADERS = {
    "no_results": (
        "No encontré información sobre eso en mi documentación. "
        "Para una respuesta humana, podés contactarnos:"
    ),
    "llm_error": (
        "No pude procesar tu consulta. Si necesitás ayuda inmediata, "
        "contactá a una persona del equipo:"
    ),
    "complaint": (
        "Lamento la mala experiencia. Para que un humano del equipo "
        "atienda tu caso, escribinos:"
    ),
    "manual": (
        "Para hablar con una persona del equipo de soporte:"
    ),
}


def _normalize(text: str) -> str:
    """Minusculas sin acentos, para matchear keywords sin importar tildes."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def looks_like_complaint(text: str) -> bool:
    """True si el mensaje contiene alguna frase de queja/pedido humano.
    Red de seguridad por si el LLM no clasifica como intent 'complaint'."""
    if not text:
        return False
    norm = _normalize(text)
    return any(kw in norm for kw in COMPLAINT_KEYWORDS)


def has_any_contact(support: "SupportConfig") -> bool:
    """True si hay al menos un canal de contacto configurado."""
    return bool(support.email or support.phone)


def build_escalation_message(reason: str, support: "SupportConfig") -> str:
    """
    Arma el texto que se le envia al usuario.

    Args:
        reason: 'no_results' | 'llm_error' | 'complaint' | 'manual'.
        support: instancia de SupportConfig (config.support).

    Returns:
        Mensaje en espanol con los canales disponibles. Si no hay
        ningun contacto configurado en .env, devuelve un mensaje
        generico para que el usuario al menos sepa que el bot no resuelve.
    """
    header = _REASON_HEADERS.get(reason, _REASON_HEADERS["manual"])

    if not has_any_contact(support):
        return (
            f"{header}\n\n"
            "(El equipo de soporte aún no configuró los datos de contacto. "
            "Pedile al administrador que complete SUPPORT_EMAIL en el .env.)"
        )

    lines = [header, ""]
    if support.email:
        lines.append(f"📧 Email: {support.email}")
    if support.phone:
        lines.append(f"📞 Teléfono: {support.phone}")
    if support.hours:
        lines.append(f"🕐 Horario de atención: {support.hours}")

    return "\n".join(lines)
