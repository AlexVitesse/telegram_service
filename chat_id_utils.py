"""
chat_id_utils — Validacion y normalizacion de chat IDs de Telegram.

Resuelve un bug recurrente: la app Ionic a veces guarda IDs de supergrupo
sin el '-' inicial, lo que rompe las notificaciones (Telegram rechaza el
chat_id positivo con "Chat not found" y el bot lo loguea solo a nivel
warning, asi que el problema pasa silencioso).

Patron de supergrupo de Telegram: -100xxxxxxxxxx (13 digitos despues del -).
Si llega 100xxxxxxxxxx (positivo, exactamente 13 digitos arrancando con 100)
es practicamente seguro que es un supergrupo malformado:

- Hoy los user IDs de Telegram tienen ~10 digitos (max ~9.000 millones).
- Para colisionar con el patron 100xxxxxxxxxx (>= 1 billon) Telegram
  tendria que asignar dos ordenes de magnitud mas IDs de los actuales.
- El patron es estrictamente: positivo, 13 digitos exactos, prefijo "100".
  Cualquier desviacion (12 digitos, prefijo distinto, ya tiene "-") no se toca.

NO cubrimos grupos basicos legacy (IDs negativos cortos como -1234567890).
Esos, si pierden el '-', son indistinguibles de un user ID y no hay
heuristica segura. Telegram viene migrando todos a supergrupos hace anos.
"""
from __future__ import annotations

import logging
import re
from typing import Union

logger = logging.getLogger(__name__)

# Positivo, exactamente 13 digitos, empieza con "100".
# Coincide con el rango de IDs de supergrupo cuando se les saca el "-".
_STRIPPED_SUPERGROUP_RE = re.compile(r"^100\d{10}$")

ChatIdLike = Union[str, int, None]


def looks_like_stripped_supergroup(chat_id: ChatIdLike) -> bool:
    """True si el chat_id parece un supergrupo al que le sacaron el '-'.

    Heuristica estricta: debe ser un string/int de exactamente 13 digitos,
    positivo, arrancando con "100". Devuelve False para cualquier otro
    input (vacio, None, ya tiene "-", longitud distinta, prefijo distinto).
    """
    if chat_id is None:
        return False
    s = str(chat_id).strip()
    if not s:
        return False
    return bool(_STRIPPED_SUPERGROUP_RE.match(s))


def normalize_chat_id(chat_id: ChatIdLike, *, auto_fix: bool = True) -> str:
    """Normaliza un chat_id de Telegram aplicando el fix defensivo si corresponde.

    Args:
        chat_id: el chat_id (str, int, o None).
        auto_fix: True (default) habilita la auto-correccion del patron
                  100xxxxxxxxxx -> -100xxxxxxxxxx. Si False, solo loguea
                  un error y devuelve el valor sin tocar (caller decide).

    Returns:
        Chat_id normalizado como string. Si el input es None o vacio,
        devuelve string vacio.
    """
    if chat_id is None:
        return ""
    s = str(chat_id).strip()
    if not s:
        return ""

    if looks_like_stripped_supergroup(s):
        if auto_fix:
            corrected = "-" + s
            logger.warning(
                "🔧 Chat ID parece supergrupo sin '-': %s -> %s. "
                "Probable bug en la app Ionic al registrar el grupo. "
                "Auto-corregido. Para desactivar: TELEGRAM_AUTO_FIX_GROUP_ID=false",
                s, corrected,
            )
            return corrected
        else:
            logger.error(
                "❌ Chat ID parece supergrupo sin '-': %s. "
                "auto_fix=False, no se corrige. Las notificaciones a este chat fallaran.",
                s,
            )
            return s

    return s
