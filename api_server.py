"""
Endpoint HTTP para que la app le pregunte a Senti sin pasar por Telegram.

Corre **en el mismo proceso que el bot** y no aparte: `KnowledgeBase` construye
los embeddings y el índice TF-IDF al cargar, así que un segundo proceso pagaría
esa construcción entera en cada arranque y tendría su propia copia en memoria.

Escucha en `127.0.0.1`. Quien lo publica hacia fuera es **ngrok** o un proxy
inverso, nunca este proceso: abrirlo en `0.0.0.0` lo dejaría expuesto a toda la
red del VPS, y las peticiones llevan un ID token de Firebase.

    POST /preguntar   Authorization: Bearer <idToken de Firebase>
                      {"pregunta": "..."}  ->  {"texto": "...", "fuente": "..."}
    GET  /salud       sin auth, para comprobar que está vivo

Quien contesta es `knowledge_qa.responder()`, el mismo que usa el bot, así que
los dos canales dan **la misma respuesta a la misma pregunta**.

Si la petición trae además `dispositivos`, la frase se clasifica antes con
`parse_intent` y una orden vuelve como acción (`comandos_app`) en vez de como
párrafo de documentación. **Ejecutar es cosa de la app**: aquí no se publica
MQTT ni se escribe en RTDB. Sin `dispositivos`, todo sigue igual que antes.
"""
import asyncio
import hmac
import json
import logging
import time
from typing import Any, Optional, Tuple

from aiohttp import web

import ai_handler
import comandos_app
import knowledge_qa
from api_limites import Limitador, normalizar_pregunta
from config import config

logger = logging.getLogger(__name__)

#: Que parte del presupuesto puede gastarse el clasificador. Con los 40 s de hoy
#: son 20 para clasificar y ~18 para contestar.
#:
#: Era 0.25 -"clasificar es la llamada corta"- y la medicion dijo lo contrario:
#: sobre 89 interacciones reales, el RAG tiene p95 de 8.2 s y el camino de
#: accion 9.9 s, con maximo en 10.7. O sea que el clasificador estaba pegado a
#: su techo de 10 s mientras al RAG le sobraban 20. Y pasarse de ese techo no
#: da un error: expira, se trata como "no era una orden" y la frase se va al
#: RAG. Ordenes contestadas con documentacion, otra vez, ahora por reloj.
#:
#: Con 0.5 el clasificador tiene el doble de su p95 y al RAG le quedan 18 s,
#: que siguen siendo 2.2 veces el suyo. Si algun dia se cambia el modelo del
#: clasificador, este numero se vuelve a medir: depende de cual sea.
_PARTE_CLASIFICADOR = 0.5

#: Lo que se reserva para serializar y devolver la respuesta ya calculada. Sin
#: esto, el ultimo segundo se lo lleva el LLM y el cliente corta justo cuando
#: habia respuesta.
_MARGEN_RESPUESTA = 2.0


def _restante(limite: float) -> float:
    """Segundos que quedan del presupuesto. Nunca negativo."""
    return max(0.0, limite - time.monotonic())


def elegir_tunel(datos: dict, puerto: int) -> Optional[str]:
    """
    De lo que responde la API local de ngrok, el tunel que apunta a NUESTRO
    puerto. `None` si no hay ninguno.

    No vale coger el primero: el agente de ngrok puede estar publicando otros
    proyectos a la vez, y entonces se anuncia como endpoint de la app una URL
    que lleva a otro servicio. El fallo no se ve -la URL existe y contesta-,
    solo contesta cualquier otra cosa.

    A donde reenvia cada tunel viene en `config.addr` ("http://localhost:8765").
    Se compara contra ":puerto" para no confundir el 8765 con un 18765.
    """
    marca = f":{puerto}"
    for t in (datos or {}).get("tunnels", []) or []:
        publica = str(t.get("public_url", ""))
        destino = str((t.get("config") or {}).get("addr", ""))
        if publica.startswith("https://") and destino.endswith(marca):
            return publica
    return None


class ApiSenti:
    def __init__(self, bot: Any, firebase: Any):
        # Se toman del bot en cada peticion y no en el constructor: el admin
        # puede recargar la base de conocimiento con /reload_kb, y guardarnos
        # una referencia aqui dejaria al endpoint contestando con la version
        # vieja para siempre.
        self._bot = bot
        self._firebase = firebase
        self._limitador = Limitador(
            config.api.max_por_hora, config.api.espera_min_seg
        )
        self._runner: Optional[web.AppRunner] = None
        # Guardada a proposito: asyncio solo tiene una referencia debil a las
        # tareas, y una que nadie sujeta puede irsele al recolector a medias.
        self._tarea_url: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Autenticación y autorización
    # ------------------------------------------------------------------

    async def _identificar(self, request: web.Request) -> Tuple[Optional[str], Optional[web.Response]]:
        """
        Quién pregunta. Devuelve `(uid, None)` si pasa, o `(None, respuesta)`
        con el error si no.

        El `uid` sirve para dos cosas: el tope de uso y el registro. En los
        modos que no son "firebase" no hay un usuario real, así que se usa un
        identificador de la conexión — peor, pero mejor que no llevar cuenta.
        """
        modo = config.api.auth

        if modo == "abierto":
            return f"ip:{self._ip(request)}", None

        if modo == "clave":
            if not config.api.clave:
                logger.error("API_AUTH=clave pero API_CLAVE esta vacia")
                return None, web.json_response(
                    {"error": "El asistente no está configurado."}, status=503
                )
            enviada = request.headers.get("X-Api-Key", "")
            # compare_digest y no ==: comparar cadenas normalmente tarda mas
            # cuanto mas coincide el principio, y eso deja adivinar la clave
            # caracter a caracter midiendo tiempos.
            if not hmac.compare_digest(enviada, config.api.clave):
                return None, web.json_response({"error": "Clave no válida."}, status=401)
            return f"ip:{self._ip(request)}", None

        # modo firebase
        token = self._token_de(request)
        if not token:
            return None, web.json_response(
                {"error": "Falta la cabecera Authorization: Bearer <token>."},
                status=401,
            )
        uid = await asyncio.to_thread(self._uid_del_token, token)
        if not uid:
            return None, web.json_response(
                {"error": "Sesión no válida. Vuelve a iniciar sesión."}, status=401
            )
        if not await self._esta_habilitado(uid):
            return None, web.json_response(
                {"error": "Tu cuenta todavía no tiene ningún equipo vinculado."},
                status=403,
            )
        return uid, None

    @staticmethod
    def _ip(request: web.Request) -> str:
        """
        Detrás de ngrok la IP real llega en X-Forwarded-For.

        Se toma el **último** de la cadena, no el primero. Cada proxy añade al
        final la IP de quien le habló, así que el primer valor es el que mandó
        el cliente: falsificarlo es escribir una cabecera. Tomándolo, cualquiera
        estrenaba cuota en cada petición y el tope no existía.
        """
        reenviada = request.headers.get("X-Forwarded-For", "")
        if reenviada:
            return reenviada.split(",")[-1].strip()
        return request.remote or "desconocida"

    @staticmethod
    def _token_de(request: web.Request) -> Optional[str]:
        cabecera = request.headers.get("Authorization", "")
        if not cabecera.startswith("Bearer "):
            return None
        token = cabecera[7:].strip()
        return token or None

    def _uid_del_token(self, token: str) -> Optional[str]:
        """
        Verifica el ID token contra Firebase. Es lo que hace de contraseña, así
        que un fallo aquí es un 401 y punto: nunca se deja pasar "por si acaso".
        """
        try:
            from firebase_admin import auth

            return auth.verify_id_token(token).get("uid")
        except Exception as e:
            # A nivel debug: un token caducado es lo mas normal del mundo y no
            # tiene que llenar el log de errores.
            logger.debug("Token rechazado: %s", e)
            return None

    async def _esta_habilitado(self, uid: str) -> bool:
        """
        Solo gente habilitada: que el uid tenga al menos un equipo dado de alta.

        Un cliente real tiene equipos; quien solo se registró, no. Se apoya en
        un dato que ya existe en vez de en una lista aparte que habría que
        mantener a mano y que se desincronizaría el primer día.
        """
        try:
            # to_thread: firebase_admin.db es sincrono y esto corre en el
            # mismo event loop que el bot. Sin esto, cada pregunta de la app
            # congela Telegram y el MQTT lo que tarde Firebase en contestar.
            datos = await asyncio.to_thread(
                self._firebase.db.reference(f"Usuarios/{uid}/Dispositivos").get
            )
        except Exception as e:
            # Si Firebase no contesta NO se deja pasar. Un fallo de lectura no
            # puede convertirse en una puerta abierta.
            logger.error("No se pudo comprobar si %s esta habilitado: %s", uid, e)
            return False

        if isinstance(datos, str):
            return bool(datos.strip())
        return bool(datos)

    # ------------------------------------------------------------------
    # Rutas
    # ------------------------------------------------------------------

    async def salud(self, request: web.Request) -> web.Response:
        kb = getattr(self._bot, "knowledge_base", None)
        return web.json_response(
            {
                "ok": True,
                "kb": bool(kb),
                "ia": bool(getattr(self._bot, "ai_handler", None)),
            }
        )

    async def preguntar(self, request: web.Request) -> web.Response:
        t0 = time.monotonic()

        uid, error = await self._identificar(request)
        if error is not None:
            return error

        permitido, motivo = self._limitador.permitir(uid)
        if not permitido:
            return web.json_response({"error": motivo}, status=429)

        try:
            cuerpo = await request.json()
        except (json.JSONDecodeError, ValueError):
            return web.json_response({"error": "El cuerpo no es JSON."}, status=400)

        pregunta = normalizar_pregunta((cuerpo or {}).get("pregunta"))
        if not pregunta:
            return web.json_response(
                {"error": "Mándame una pregunta."}, status=400
            )

        # Todo lo que queda -clasificar y contestar- sale de este presupuesto,
        # en vez de que cada tramo pida el suyo como si fuera el unico. El
        # limite es absoluto: lo que se lleve el clasificador se lo quita al RAG.
        limite = t0 + config.api.budget_sec

        # Antes del RAG: si la frase era una orden, la contesta como orden y la
        # ejecuta la app. Si no viene `dispositivos` no se clasifica nada y el
        # camino de abajo es el de siempre, que es lo que mantiene funcionando
        # a las versiones de la app ya publicadas.
        try:
            orden, intento = await self._como_orden(
                pregunta, (cuerpo or {}).get("dispositivos"), limite
            )
        except ai_handler.LlmOcupado:
            # Una orden que no se pudo clasificar por falta de sitio NO puede
            # seguir al RAG: volveria como parrafo de documentacion, que es el
            # fallo que este endpoint vino a arreglar y encima parece que
            # funciono. Se dice que estamos ocupados y se acabo.
            self._anotar(
                uid, pregunta, response_type="ocupado",
                response=ai_handler.TEXTO_OCUPADO,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                ok=False, error="llm_ocupado",
            )
            return self._ocupado()
        if orden is not None:
            motivo_log = orden.pop("motivo", None)
            self._anotar(
                uid, pregunta,
                intent=intento.get("intent"),
                confidence=intento.get("confidence"),
                # El mismo tipo que usa el bot en `_log_action`: las dos vias
                # caen en el mismo analisis.
                response_type="action",
                response=orden["texto"],
                elapsed_ms=int((time.monotonic() - t0) * 1000),
                ok=orden["tipo"] == "accion",
                error=motivo_log,
            )
            return web.json_response(orden)

        r = await knowledge_qa.responder(
            pregunta,
            getattr(self._bot, "knowledge_base", None),
            getattr(self._bot, "ai_handler", None),
            # Lo que quede del presupuesto, menos lo que cuesta serializar y
            # contestar. Nunca menos de un segundo: pedir un techo de 0 s es
            # garantizar el timeout en vez de intentarlo.
            timeout=max(1.0, _restante(limite) - _MARGEN_RESPUESTA),
        )

        # Mismo registro que el bot: las preguntas de la app cuentan igual para
        # saber que no sabe contestar Senti.
        self._registrar(uid, pregunta, r, int((time.monotonic() - t0) * 1000))

        if r.tipo == "ocupado":
            return self._ocupado(r.texto)

        return web.json_response(
            {
                "texto": r.texto,
                "fuente": " | ".join(dict.fromkeys(r.fuentes)) or None,
                "tipo": r.tipo,
            }
        )

    def _ocupado(self, texto: str = ai_handler.TEXTO_OCUPADO) -> web.Response:
        """
        503 porque el servicio no da abasto ahora mismo. Lo que la app mira para
        saber que SI merece reintentar es `reintentar_en`: el 503 a secas ya lo
        usa "El asistente no está configurado", que es lo contrario -eso no se
        arregla esperando-. Acordado con la sesion de la app.
        """
        return web.json_response(
            {"error": texto, "reintentar_en": ai_handler.ESPERA_SUGERIDA_SEG},
            status=503,
            headers={"Retry-After": str(ai_handler.ESPERA_SUGERIDA_SEG)},
        )

    async def _como_orden(
        self, pregunta: str, dispositivos: Any, limite: float
    ) -> Tuple[Optional[dict], Optional[dict]]:
        """
        ¿Era una orden? Devuelve `(respuesta, intencion)`, o `(None, None)` para
        que siga al RAG exactamente como hasta ahora.

        Todo lo que salga mal aquí acaba en el RAG y no en un error: quien
        preguntaba algo normal no puede quedarse sin respuesta porque el
        clasificador tuviera un mal día.
        """
        ia = getattr(self._bot, "ai_handler", None)
        if not ia or not isinstance(dispositivos, list) or not dispositivos:
            return None, None

        # `parse_intent` espera las claves en inglés; el contrato con la app va
        # en español como el resto del endpoint.
        equipos = [
            {
                "id": d.get("id"),
                "name": d.get("nombre"),
                "is_armed": d.get("armado"),
                "is_online": d.get("en_linea"),
            }
            # Sin `id` no se puede resolver despues, asi que tampoco se le
            # ensena al modelo: solo serviria para que nombrase un equipo que
            # luego acaba en «no encontre ninguno que se llame asi».
            for d in dispositivos if isinstance(d, dict) and d.get("id")
        ]

        try:
            # Un cuarto del presupuesto, y nunca más de lo que queda. Clasificar
            # es una llamada corta: si tarda más que eso, la orden ya no la
            # espera nadie y sale más a cuenta tratarla como pregunta -que es
            # justo lo que pasa cuando expira-. El resto del tiempo es del RAG.
            intento = await asyncio.wait_for(
                ia.parse_intent(pregunta, equipos),
                timeout=min(
                    config.api.budget_sec * _PARTE_CLASIFICADOR,
                    _restante(limite),
                ),
            )
        except ai_handler.LlmOcupado:
            raise               # lo contesta `preguntar` como 503, no el RAG
        except Exception as e:
            logger.warning(
                "No se pudo clasificar '%s' (%s): va al RAG", pregunta[:40], e
            )
            return None, None

        if not intento:
            return None, None
        return comandos_app.decidir(intento, dispositivos), intento

    def _registrar(self, uid: str, pregunta: str, r: Any, ms: int) -> None:
        self._anotar(
            uid, pregunta,
            intent="question",
            confidence=None,
            response_type=r.tipo,
            response=r.texto,
            rag_sources=r.fuentes,
            rag_scores=r.scores,
            elapsed_ms=ms,
            ok=r.ok,
            error=r.error,
        )

    def _anotar(self, uid: str, pregunta: str, **campos: Any) -> None:
        """Lo común a las dos vías -pregunta y orden- ya puesto."""
        registro = getattr(self._bot, "interaction_logger", None)
        if not registro:
            return
        try:
            registro.record(
                user_id=f"app:{uid}",
                user_name="app",
                query=pregunta,
                backend=getattr(
                    getattr(self._bot, "ai_handler", None), "_backend", None
                ),
                **campos,
            )
        except Exception as e:
            # Que falle el registro no puede tumbar una respuesta ya calculada.
            logger.error("No se pudo registrar la interaccion de la app: %s", e)

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------

    def _cabeceras_cors(self, request: web.Request) -> dict:
        permitidos = [o.strip() for o in config.api.cors.split(",") if o.strip()]
        origen = request.headers.get("Origin", "")
        if "*" in permitidos:
            devolver = origen or "*"
        elif origen in permitidos:
            devolver = origen
        else:
            return {}
        return {
            "Access-Control-Allow-Origin": devolver,
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            # ngrok-skip-browser-warning va aqui a proposito: sin ella ngrok
            # devuelve su pantalla de aviso en vez de la respuesta, y esa
            # cabecera es justo la que obliga al navegador a hacer preflight.
            "Access-Control-Allow-Headers":
                "Content-Type, Authorization, X-Api-Key, ngrok-skip-browser-warning",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }

    @web.middleware
    async def _cors(self, request: web.Request, handler):
        """
        Sin esto la app no puede llamar al endpoint desde el WebView.

        Corre en https://localhost y el endpoint esta en otro dominio, asi que
        el navegador exige CORS. Y con una cabecera propia -la de ngrok- ni
        siquiera el GET es una peticion "simple": manda un OPTIONS antes. Desde
        curl no se nota nada de esto, porque curl no aplica CORS.
        """
        if request.method == "OPTIONS":
            return web.Response(status=204, headers=self._cabeceras_cors(request))
        respuesta = await handler(request)
        respuesta.headers.update(self._cabeceras_cors(request))
        return respuesta

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app = web.Application(middlewares=[self._cors])
        app.router.add_post("/preguntar", self.preguntar)
        app.router.add_get("/salud", self.salud)
        app.router.add_route("OPTIONS", "/{cualquiera:.*}", self._preflight)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        sitio = web.TCPSite(self._runner, config.api.host, config.api.port)
        await sitio.start()
        logger.info(
            "API de Senti escuchando en http://%s:%d (auth: %s)",
            config.api.host,
            config.api.port,
            config.api.auth,
        )
        if config.api.auth == "abierto":
            logger.warning(
                "⚠️ API SIN AUTENTICACION. Solo para pruebas en local: detras de "
                "ngrok, cualquiera que de con la URL gasta tu cuota de LLM."
            )

        self._tarea_url = asyncio.create_task(self.publicar_url())

    async def _preflight(self, request: web.Request) -> web.Response:
        return web.Response(status=204, headers=self._cabeceras_cors(request))

    async def stop(self) -> None:
        if self._tarea_url:
            self._tarea_url.cancel()
            self._tarea_url = None
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            logger.info("API de Senti detenida")

    async def publicar_url(self) -> None:
        """
        Escribe en RTDB la URL pública que ngrok esté sirviendo ahora mismo.

        Con el plan gratis de ngrok la URL cambia en cada reinicio. Si la app la
        llevara compilada dentro, habría que republicarla cada vez; leyéndola de
        RTDB, el VPS se reinicia y la app se entera sola.

        Se pregunta a la API local del agente de ngrok. Si no está corriendo, no
        se publica nada y no pasa nada: el endpoint sigue en pie para quien lo
        alcance por otra vía.
        """
        if not config.api.ngrok_api:
            return

        # Margen para que el agente de ngrok levante despues del servicio.
        await asyncio.sleep(5)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=5.0) as cliente:
                datos = (await cliente.get(config.api.ngrok_api)).json()

            url = elegir_tunel(datos, config.api.port)
            if not url:
                otros = [t.get("public_url") for t in datos.get("tunnels", [])]
                logger.warning(
                    "ngrok no tiene ningun tunel https hacia el puerto %d. "
                    "Tuneles vistos: %s",
                    config.api.port, otros or "ninguno",
                )
                return

            await asyncio.to_thread(
                self._firebase.db.reference(config.api.ruta_url).set,
                {"url": url, "actualizado": int(time.time())},
            )
            logger.info("URL de la API publicada en %s: %s", config.api.ruta_url, url)

        except Exception as e:
            logger.info(
                "No se pudo publicar la URL de la API (¿ngrok apagado?): %s", e
            )
