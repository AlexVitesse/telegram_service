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

# Numero entero opcionalmente negativo, entre 5 y 14 digitos (sin contar el "-").
# Rango realista de chat IDs de Telegram: user IDs son 7-10 digitos, supergrupos
# son 13 digitos despues del prefijo "-100". Acotamos un poco mas amplio (5-14)
# para tolerar futuras expansiones de Telegram sin tener que tocar el codigo.
# Menores a 5 digitos son placeholders ("1111"), mayores a 14 son ruido.
_PLAUSIBLE_CHAT_ID_RE = re.compile(r"^-?\d{5,14}$")

ChatIdLike = Union[str, int, None]


def is_plausible_telegram_chat_id(chat_id: ChatIdLike) -> bool:
    """True si el valor se parece a un chat ID real de Telegram.

    Filtra basura como placeholders literales ("hola chatid", "hi chatid grupal"),
    numeros muy cortos ("1111", "1212") o vacios. La app Ionic obliga a llenar
    Group_ID y los usuarios meten cualquier cosa para avanzar; este validador
    permite tratar esos valores como "sin grupo configurado".

    Criterio: numero entero (opcional "-" al inicio), entre 5 y 14 digitos.

    Args:
        chat_id: el valor a chequear (str, int, o None).

    Returns:
        True si es plausible, False para basura, vacio, no numerico, o fuera de rango.
    """
    if chat_id is None:
        return False
    s = str(chat_id).strip()
    if not s:
        return False
    return bool(_PLAUSIBLE_CHAT_ID_RE.match(s))


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
    """Normaliza un chat_id de Telegram aplicando defensas en cadena.

    1. Auto-fix del patron supergrupo sin "-" (100xxxxxxxxxx -> -100xxxxxxxxxx).
    2. Si el resultado NO es un chat ID plausible (no numerico, muy corto, etc),
       devuelve "" para que los callers lo traten como "sin chat configurado".

    Esto resuelve el escenario donde la app obliga a llenar Group_ID y los
    usuarios meten basura ("hola chatid", "1111") para avanzar el form.

    Args:
        chat_id: el chat_id (str, int, o None).
        auto_fix: True (default) habilita la auto-correccion del patron
                  100xxxxxxxxxx -> -100xxxxxxxxxx. Si False, solo loguea
                  un error y devuelve el valor sin tocar (caller decide).

    Returns:
        - El chat_id normalizado y plausible como string, OR
        - "" (string vacio) si el input es None, vacio, o no plausible.
    """
    if chat_id is None:
        return ""
    s = str(chat_id).strip()
    if not s:
        return ""

    # Paso 1: auto-fix supergrupo sin "-"
    if looks_like_stripped_supergroup(s):
        if auto_fix:
            corrected = "-" + s
            logger.warning(
                "🔧 Chat ID parece supergrupo sin '-': %s -> %s. "
                "Probable bug en la app Ionic al registrar el grupo. "
                "Auto-corregido. Para desactivar: TELEGRAM_AUTO_FIX_GROUP_ID=false",
                s, corrected,
            )
            s = corrected
        else:
            logger.error(
                "❌ Chat ID parece supergrupo sin '-': %s. "
                "auto_fix=False, no se corrige. El send a Telegram fallara.",
                s,
            )
            # Con auto_fix=False respetamos el valor — la plausibilidad lo dejara
            # pasar porque es numerico y 13 digitos entra en el rango. La idea
            # del flag es preservar el comportamiento viejo cuando se desactiva.

    # Paso 2: validar plausibilidad. Si no parece chat ID real, descartar.
    if not is_plausible_telegram_chat_id(s):
        logger.warning(
            "⚠️ Chat ID invalido o placeholder descartado: %r. "
            "El usuario probablemente metio basura en un campo obligatorio de la app.",
            s,
        )
        return ""

    return s
