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
"""
import asyncio
import json
import logging
import time
from typing import Any, Optional

from aiohttp import web

import knowledge_qa
from api_limites import Limitador, normalizar_pregunta
from config import config

logger = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------
    # Autenticación y autorización
    # ------------------------------------------------------------------

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

    def _esta_habilitado(self, uid: str) -> bool:
        """
        Solo gente habilitada: que el uid tenga al menos un equipo dado de alta.

        Un cliente real tiene equipos; quien solo se registró, no. Se apoya en
        un dato que ya existe en vez de en una lista aparte que habría que
        mantener a mano y que se desincronizaría el primer día.
        """
        try:
            datos = self._firebase.db.reference(f"Usuarios/{uid}/Dispositivos").get()
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

        token = self._token_de(request)
        if not token:
            return web.json_response(
                {"error": "Falta la cabecera Authorization: Bearer <token>."},
                status=401,
            )

        uid = self._uid_del_token(token)
        if not uid:
            return web.json_response(
                {"error": "Sesión no válida. Vuelve a iniciar sesión."}, status=401
            )

        if not self._esta_habilitado(uid):
            return web.json_response(
                {"error": "Tu cuenta todavía no tiene ningún equipo vinculado."},
                status=403,
            )

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

        r = await knowledge_qa.responder(
            pregunta,
            getattr(self._bot, "knowledge_base", None),
            getattr(self._bot, "ai_handler", None),
        )

        # Mismo registro que el bot: las preguntas de la app cuentan igual para
        # saber que no sabe contestar Senti.
        self._registrar(uid, pregunta, r, int((time.monotonic() - t0) * 1000))

        return web.json_response(
            {
                "texto": r.texto,
                "fuente": " | ".join(dict.fromkeys(r.fuentes)) or None,
                "tipo": r.tipo,
            }
        )

    def _registrar(self, uid: str, pregunta: str, r: Any, ms: int) -> None:
        registro = getattr(self._bot, "interaction_logger", None)
        if not registro:
            return
        try:
            registro.record(
                user_id=f"app:{uid}",
                user_name="app",
                query=pregunta,
                intent="question",
                confidence=None,
                backend=getattr(
                    getattr(self._bot, "ai_handler", None), "_backend", None
                ),
                response_type=r.tipo,
                response=r.texto,
                rag_sources=r.fuentes,
                rag_scores=r.scores,
                elapsed_ms=ms,
                ok=r.ok,
                error=r.error,
            )
        except Exception as e:
            # Que falle el registro no puede tumbar una respuesta ya calculada.
            logger.error("No se pudo registrar la interaccion de la app: %s", e)

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post("/preguntar", self.preguntar)
        app.router.add_get("/salud", self.salud)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        sitio = web.TCPSite(self._runner, config.api.host, config.api.port)
        await sitio.start()
        logger.info(
            "API de Senti escuchando en http://%s:%d",
            config.api.host,
            config.api.port,
        )

        asyncio.create_task(self.publicar_url())

    async def stop(self) -> None:
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

            url = next(
                (
                    t["public_url"]
                    for t in datos.get("tunnels", [])
                    if t.get("public_url", "").startswith("https://")
                ),
                None,
            )
            if not url:
                logger.warning("ngrok esta corriendo pero sin tunel https")
                return

            self._firebase.db.reference(config.api.ruta_url).set(
                {"url": url, "actualizado": int(time.time())}
            )
            logger.info("URL de la API publicada en %s: %s", config.api.ruta_url, url)

        except Exception as e:
            logger.info(
                "No se pudo publicar la URL de la API (¿ngrok apagado?): %s", e
            )
