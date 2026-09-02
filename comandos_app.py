"""
De una intencion ya clasificada a lo que el endpoint le contesta a la app.

Vive aparte de `api_server.py` y sin `aiohttp` ni Telegram delante, por el mismo
motivo por el que existe `knowledge_qa.py`: aqui esta la decision -que accion
sale, sobre que equipo y si hay que confirmar- y asi se puede probar entera sin
levantar nada.

Quien ejecuta es la app, con la sesion del usuario y por el mismo camino que ya
usa el toggle de la pantalla de equipos. Este modulo no escribe en RTDB ni
publica MQTT: solo decide.

Los dispositivos llegan tal cual los manda la app (`id`, `nombre`, `armado`,
`en_linea`). La traduccion al ingles que espera `parse_intent` se hace en el
endpoint y solo para el LLM.
"""
from typing import Any, Dict, List, Optional

#: No son ordenes: siguen al RAG exactamente como hasta ahora.
AL_RAG = ("question", "complaint", "unknown")

#: Lo que la app sabe hacer hoy, y si hay que preguntar antes de hacerlo.
#: `disarm` es el unico que si: equivocarse armando es un susto, pero desarmar
#: una casa por un error de clasificacion es un fallo de seguridad, y ademas es
#: silencioso. La regla vive aqui y no en el cliente para que no se olvide en el
#: siguiente que se conecte.
CONFIRMAR = {
    "arm": False,
    "disarm": True,
    "status": False,
    "list_devices": False,
}

#: Lo que todavia no se puede, y a donde mandar a quien lo pide. Un "no puedo"
#: explicito ya es mejor respuesta que un parrafo de documentacion que no hizo
#: nada.
AVISOS = {
    # La bengala tiene dos rutas con nombres parecidos y una de ellas acaba en
    # sirena sonando. Hasta aclarar cual toca, desde el chat no se toca.
    "trigger_bengala": (
        "La bengala todavia no se maneja desde el chat. Puedes habilitarla en "
        "la ficha del equipo o desde el bot de Telegram."
    ),
    "stop_alarm": (
        "Para silenciar una sirena que esta sonando, usa el bot de Telegram: "
        "desde la app todavia no se puede."
    ),
    "last_event": (
        "El historial de eventos todavia no esta en la app. El bot de Telegram "
        "si te lo puede decir."
    ),
    "schedule": "Los horarios se configuran desde la pantalla de Horarios.",
    "query_schedule": "Puedes ver los horarios en la pantalla de Horarios.",
}

_NO_SOPORTADO = "Eso todavia no lo puedo hacer desde el chat."


def _equipos(dispositivos: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """Lo que mando la app, quedandose solo con lo que tiene forma de equipo."""
    return [
        d for d in (dispositivos or [])
        if isinstance(d, dict) and d.get("id")
    ]


def _aviso(texto: str, motivo: str) -> Dict[str, Any]:
    #: `motivo` no es para la app: es el codigo de error del registro, y el
    #: endpoint lo saca antes de serializar.
    return {"tipo": "aviso", "texto": texto, "motivo": motivo}


def resolver(nombre: Optional[str], dispositivos: Optional[List[Any]]) -> Optional[str]:
    """
    El nombre que dijo el LLM -> el `id` que mando la app, `"all"`, o `None`.

    Nunca cae a "todos los equipos" cuando el nombre no coincide con ninguno.
    Ese es el fallback de `_resolve_device_ids_by_name` en el bot, y con el
    «apaga la alarma del garage», sin ningun equipo llamado garage, desarma la
    casa entera.

    Con varios candidatos tampoco elige: dos equipos que empiezan igual no son
    una coincidencia, son una pregunta sin responder.
    """
    equipos = _equipos(dispositivos)
    if not equipos:
        return None
    if not nombre or nombre == "all":
        return "all"

    buscado = str(nombre).strip().lower()
    if not buscado:
        return "all"

    exactos = [
        d for d in equipos
        if buscado in (str(d.get("nombre") or "").lower(), str(d.get("id")).lower())
    ]
    # El parcial solo se mira si no hubo exacto: "Casa" no puede quedar en
    # empate con "Casa de campo" teniendo un equipo que se llama Casa.
    candidatos = exactos or [
        d for d in equipos
        if buscado in str(d.get("nombre") or "").lower()
        or buscado in str(d.get("id")).lower()
    ]
    return str(candidatos[0]["id"]) if len(candidatos) == 1 else None


def _nombre_de(objetivo: str, dispositivos: Optional[List[Any]]) -> str:
    if objetivo == "all":
        return "todos los equipos"
    for d in _equipos(dispositivos):
        if str(d["id"]) == objetivo:
            return str(d.get("nombre") or objetivo)
    return objetivo


def _texto(intent: str, objetivo: str, dispositivos: Optional[List[Any]]) -> str:
    """
    El texto se arma aqui y no se coge el `reply` del LLM: ese ya da la orden
    por hecha ("Alarma activada") cuando todavia no se ha ejecutado nada -lo
    hace la app, y con `disarm` solo si el usuario confirma-.
    """
    nombre = _nombre_de(objetivo, dispositivos)
    return {
        "arm": f"Armo {nombre}.",
        "disarm": f"Desarmo {nombre}. ¿Confirmas?",
        "status": f"Miro como esta {nombre}.",
        "list_devices": "Estos son tus equipos.",
    }[intent]


def decidir(
    intento: Optional[Dict[str, Any]],
    dispositivos: Optional[List[Any]],
) -> Optional[Dict[str, Any]]:
    """
    Que contestar a lo que devolvio `parse_intent`.

    `None` significa "esto no era una orden": el endpoint sigue al RAG como
    siempre. Cualquier intent que no este en la tabla acaba en aviso, para que
    uno nuevo en `ai_handler` no se cuele sin que nadie decida que hace la app.
    """
    intent = (intento or {}).get("intent")
    if not intent or intent in AL_RAG:
        return None

    if intent not in CONFIRMAR:
        return _aviso(AVISOS.get(intent, _NO_SOPORTADO), f"no_soportado:{intent}")

    # `list_devices` no habla de ningun equipo en concreto.
    objetivo = (
        "all" if intent == "list_devices"
        else resolver(intento.get("device"), dispositivos)
    )
    if objetivo is None:
        nombres = [str(d.get("nombre") or d["id"]) for d in _equipos(dispositivos)]
        texto = (
            f"No encontre ningun equipo que se llame «{intento.get('device')}». "
            f"Tienes: {', '.join(nombres)}."
            if nombres else "No veo ningun equipo vinculado en esta sesion."
        )
        return _aviso(texto, "device_not_found")

    return {
        "tipo": "accion",
        "accion": intent,
        # Siempre el `id` que mando la app, o "all". Nunca un nombre: el
        # emparejamiento difuso lo hace el VPS y solo una vez.
        "dispositivo": objetivo,
        "confirmar": CONFIRMAR[intent],
        "texto": _texto(intent, objetivo, dispositivos),
    }
