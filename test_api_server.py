"""
Levanta el endpoint de verdad en un puerto libre y le pega peticiones reales.

Sin Firebase y sin LLM: se sustituyen por dobles. Lo que se comprueba es la
puerta —quien pasa y quien no— que es donde un fallo se paga caro: dejar entrar
a quien no debe, o dejar fuera a un cliente legítimo.

    python test_api_server.py
"""
import asyncio
import socket
import sys
from types import SimpleNamespace

import aiohttp

import api_server
from config import config


# --------------------------------------------------------------------------
# Dobles
# --------------------------------------------------------------------------

class RespuestaFalsa:
    texto = "La bengala se configura desde la ficha del equipo."
    tipo = "rag"
    ok = True
    error = None
    fuentes = ["03_bengala.md", "03_bengala.md", "01_alta.md"]
    scores = [0.6, 0.4, 0.3]


class RefFalsa:
    def __init__(self, valor):
        self._valor = valor

    def get(self):
        return self._valor

    def set(self, _):
        pass


class FirebaseFalso:
    """`dispositivos` None simula una cuenta sin equipos; None en la ruta,
    un fallo de lectura."""

    def __init__(self, dispositivos, revienta=False):
        self._dispositivos = dispositivos
        self._revienta = revienta
        self.db = SimpleNamespace(reference=self._reference)

    def _reference(self, ruta):
        if self._revienta:
            raise RuntimeError("firebase caido")
        return RefFalsa(self._dispositivos)


class RegistroFalso:
    def __init__(self):
        self.entradas = []

    def record(self, **kw):
        self.entradas.append(kw)


class IAFalsa:
    """
    El clasificador, de mentira. Lleva la cuenta de las llamadas: que NO se le
    llame es tan importante como lo que devuelve, porque una peticion sin
    `dispositivos` no puede clasificar nada.
    """

    _backend = "ollama"

    def __init__(self, intento=None):
        self._intento = intento
        self.llamadas = 0
        self.equipos = None

    async def parse_intent(self, mensaje, equipos):
        self.llamadas += 1
        self.equipos = equipos
        return self._intento


def bot_falso(ia=None):
    return SimpleNamespace(
        knowledge_base=object(),
        ai_handler=ia or SimpleNamespace(_backend="groq"),
        interaction_logger=RegistroFalso(),
    )


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------

async def con_api(firebase, uid_valido, prueba, ia=None):
    """Levanta la API con un uid dado por bueno y ejecuta `prueba(url)`."""
    config.api.host = "127.0.0.1"
    config.api.port = puerto_libre()
    config.api.ngrok_api = ""          # que no salga a la red
    config.api.espera_min_seg = 0
    config.api.max_por_hora = 100
    config.api.auth = "firebase"
    config.api.clave = ""
    config.api.cors = "*"

    api = api_server.ApiSenti(bot_falso(ia), firebase)
    api._uid_del_token = lambda t: uid_valido if t == "bueno" else None
    api_server.knowledge_qa = SimpleNamespace(
        responder=lambda *a, **k: asyncio.sleep(0, result=RespuestaFalsa())
    )

    await api.start()
    try:
        await prueba(f"http://127.0.0.1:{config.api.port}", api)
    finally:
        await api.stop()


async def pedir(url, token=None, cuerpo=None, metodo="POST", ruta="/preguntar",
                extra=None):
    cab = {"Authorization": f"Bearer {token}"} if token else {}
    cab.update(extra or {})
    async with aiohttp.ClientSession() as s:
        m = s.post if metodo == "POST" else s.get
        kw = {"json": cuerpo} if metodo == "POST" and cuerpo is not None else {}
        async with m(url + ruta, headers=cab, **kw) as r:
            try:
                return r.status, await r.json()
            except Exception:
                return r.status, await r.text()


# --------------------------------------------------------------------------
# Pruebas
# --------------------------------------------------------------------------

async def caso_salud_no_pide_token():
    async def p(url, api):
        estado, cuerpo = await pedir(url, metodo="GET", ruta="/salud")
        assert estado == 200, estado
        assert cuerpo["ok"] is True
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_sin_cabecera_401():
    async def p(url, api):
        estado, cuerpo = await pedir(url, cuerpo={"pregunta": "hola"})
        assert estado == 401, estado
        assert "Authorization" in cuerpo["error"]
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_token_malo_401():
    async def p(url, api):
        estado, _ = await pedir(url, token="basura", cuerpo={"pregunta": "hola"})
        assert estado == 401, estado
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_sin_equipos_403():
    """Token válido pero cuenta sin equipos: no es cliente todavía."""
    async def p(url, api):
        estado, cuerpo = await pedir(url, token="bueno", cuerpo={"pregunta": "hola"})
        assert estado == 403, estado
        assert "equipo" in cuerpo["error"]
    await con_api(FirebaseFalso(None), "u1", p)


async def caso_firebase_caido_no_abre_la_puerta():
    """Si no se puede comprobar, NO se deja pasar."""
    async def p(url, api):
        estado, _ = await pedir(url, token="bueno", cuerpo={"pregunta": "hola"})
        assert estado == 403, estado
    await con_api(FirebaseFalso(["AA_BB"], revienta=True), "u1", p)


async def caso_pregunta_vacia_400():
    async def p(url, api):
        estado, _ = await pedir(url, token="bueno", cuerpo={"pregunta": "   "})
        assert estado == 400, estado
        estado, _ = await pedir(url, token="bueno", cuerpo={})
        assert estado == 400, estado
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_feliz():
    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno", cuerpo={"pregunta": "¿Cómo configuro la bengala?"}
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["texto"].startswith("La bengala se configura")
        # Fuentes sin repetir y en orden de relevancia.
        assert cuerpo["fuente"] == "03_bengala.md | 01_alta.md"
        assert cuerpo["tipo"] == "rag"
        # Y queda registrado, igual que las de Telegram.
        assert api._bot.interaction_logger.entradas[0]["user_id"] == "app:u1"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_rafaga_429():
    async def p(url, api):
        api._limitador.espera_min_seg = 30
        e1, _ = await pedir(url, token="bueno", cuerpo={"pregunta": "una"})
        e2, c2 = await pedir(url, token="bueno", cuerpo={"pregunta": "otra"})
        assert e1 == 200, e1
        assert e2 == 429, e2
        assert "Espera" in c2["error"]
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_modo_clave_exige_la_cabecera():
    async def p(url, api):
        config.api.auth = "clave"
        config.api.clave = "secreto-de-la-demo"
        # Sin clave, fuera.
        estado, cuerpo = await pedir(url, cuerpo={"pregunta": "hola"})
        assert estado == 401, estado
        assert "Clave" in cuerpo["error"]
        # Con la clave equivocada, tambien.
        async with aiohttp.ClientSession() as s2:
            async with s2.post(url + "/preguntar",
                               headers={"X-Api-Key": "otra"},
                               json={"pregunta": "hola"}) as r:
                assert r.status == 401, r.status
        # Con la buena, pasa. Y NO hace falta tener equipos: en modo clave no
        # hay usuario de Firebase a quien comprobarselos.
        async with aiohttp.ClientSession() as s2:
            async with s2.post(url + "/preguntar",
                               headers={"X-Api-Key": "secreto-de-la-demo"},
                               json={"pregunta": "hola"}) as r:
                assert r.status == 200, r.status
    await con_api(FirebaseFalso(None), "u1", p)


async def caso_modo_clave_sin_clave_configurada_no_abre():
    """Olvidar API_CLAVE no puede dejar el endpoint abierto de par en par."""
    async def p(url, api):
        config.api.auth = "clave"
        config.api.clave = ""
        estado, _ = await pedir(url, cuerpo={"pregunta": "hola"})
        assert estado == 503, estado
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_modo_abierto_deja_pasar_y_sigue_contando():
    async def p(url, api):
        config.api.auth = "abierto"
        estado, cuerpo = await pedir(url, cuerpo={"pregunta": "hola"})
        assert estado == 200, estado
        # Aunque no haya usuario, el tope sigue llevando cuenta por conexion.
        api._limitador.espera_min_seg = 30
        estado2, _ = await pedir(url, cuerpo={"pregunta": "otra"})
        assert estado2 == 429, estado2
    await con_api(FirebaseFalso(None), "u1", p)


async def caso_cabecera_falsificada_no_estrena_cuota():
    """
    El tope por IP se lleva por el ULTIMO valor de X-Forwarded-For.

    Se simula lo que hace ngrok: el cliente manda la cabecera que quiere y el
    proxy añade al final la IP desde la que se conecto de verdad. Tomando el
    primer valor -el del cliente- bastaba con inventarse una IP distinta en
    cada peticion para tener cuota infinita.
    """
    async def p(url, api):
        config.api.auth = "abierto"
        api._limitador.espera_min_seg = 30
        estado, _ = await pedir(
            url, cuerpo={"pregunta": "hola"},
            extra={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"},
        )
        assert estado == 200, estado
        estado2, _ = await pedir(
            url, cuerpo={"pregunta": "otra"},
            extra={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"},
        )
        assert estado2 == 429, f"estreno cuota cambiando la cabecera: {estado2}"
    await con_api(FirebaseFalso(None), "u1", p)


async def caso_elige_el_tunel_de_su_puerto():
    """
    Caso real: el agente de ngrok ya estaba publicando OTRO proyecto y se
    anuncio esa URL como endpoint de la app. La URL existia y contestaba, solo
    que contestaba otra cosa: nadie se entera hasta que la app pregunta.
    """
    respuesta = {"tunnels": [
        {"public_url": "https://otro-proyecto.ngrok-free.app",
         "config": {"addr": "http://localhost:3000"}},
        {"public_url": "https://el-nuestro.ngrok-free.app",
         "config": {"addr": "http://localhost:8765"}},
    ]}
    assert api_server.elegir_tunel(respuesta, 8765) == "https://el-nuestro.ngrok-free.app"
    # Sin tunel hacia nuestro puerto no se publica nada, aunque haya otros.
    assert api_server.elegir_tunel(respuesta, 9999) is None
    # Un 18765 no cuela como 8765.
    casi = {"tunnels": [{"public_url": "https://x.ngrok-free.app",
                         "config": {"addr": "http://localhost:18765"}}]}
    assert api_server.elegir_tunel(casi, 8765) is None
    # http a secas no vale, y una respuesta vacia tampoco revienta.
    solo_http = {"tunnels": [{"public_url": "http://x.ngrok-free.app",
                              "config": {"addr": "http://localhost:8765"}}]}
    assert api_server.elegir_tunel(solo_http, 8765) is None
    assert api_server.elegir_tunel({}, 8765) is None


async def caso_preflight_contesta():
    """
    El WebView de la app corre en https://localhost y el endpoint esta en otro
    dominio: antes de cada peticion manda un OPTIONS. Sin esta ruta, el
    navegador bloquea TODO -incluso el GET-, y desde curl no se nota porque
    curl no aplica CORS. Fue exactamente el fallo que se escapo.
    """
    async def p(url, api):
        async with aiohttp.ClientSession() as s2:
            async with s2.options(
                url + "/preguntar",
                headers={
                    "Origin": "https://localhost",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            ) as r:
                assert r.status == 204, r.status
                assert r.headers["Access-Control-Allow-Origin"] == "https://localhost"
                permitidas = r.headers["Access-Control-Allow-Headers"].lower()
                assert "authorization" in permitidas
                # La de ngrok tambien: es la que obliga al preflight.
                assert "ngrok-skip-browser-warning" in permitidas
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_las_respuestas_llevan_cors():
    async def p(url, api):
        async with aiohttp.ClientSession() as s2:
            async with s2.get(url + "/salud",
                              headers={"Origin": "https://localhost"}) as r:
                assert r.status == 200
                assert r.headers["Access-Control-Allow-Origin"] == "https://localhost"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


async def caso_cors_cerrado_no_devuelve_cabecera():
    async def p(url, api):
        config.api.cors = "https://solo-este.example"
        async with aiohttp.ClientSession() as s2:
            async with s2.get(url + "/salud",
                              headers={"Origin": "https://otro.example"}) as r:
                assert "Access-Control-Allow-Origin" not in r.headers
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p)


# --------------------------------------------------------------------------
# Órdenes: clasificar antes del RAG
# --------------------------------------------------------------------------

EQUIPOS = [
    {"id": "6C_C8_40_4F_C7", "nombre": "Casa", "armado": True, "en_linea": True},
    {"id": "A4_CF_12_9B_20", "nombre": "Bodega", "armado": False, "en_linea": False},
]


async def caso_sin_dispositivos_responde_como_siempre():
    """
    La promesa de compatibilidad: las versiones de la app ya publicadas no
    mandan `dispositivos` y no saben que el endpoint cambio. Ni se clasifica.
    """
    ia = IAFalsa({"intent": "disarm", "device": "Casa", "confidence": 0.95})

    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno", cuerpo={"pregunta": "apaga la alarma"}
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["tipo"] == "rag", cuerpo
        assert cuerpo["texto"].startswith("La bengala se configura")
        assert cuerpo["fuente"] == "03_bengala.md | 01_alta.md"
        assert ia.llamadas == 0, "se clasifico sin que la app mandara equipos"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


async def caso_intent_none_cae_al_rag():
    """El camino de las preguntas no puede romperse arreglando el de las ordenes."""
    ia = IAFalsa(None)

    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno",
            cuerpo={"pregunta": "como configuro la bengala?", "dispositivos": EQUIPOS},
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["tipo"] == "rag", cuerpo
        assert ia.llamadas == 1
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


async def caso_una_orden_vuelve_como_accion():
    ia = IAFalsa({"intent": "disarm", "device": "Casa", "confidence": 0.95,
                  "reply": "Alarma desactivada"})

    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno",
            cuerpo={"pregunta": "apaga la alarma de casa", "dispositivos": EQUIPOS},
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["tipo"] == "accion", cuerpo
        assert cuerpo["accion"] == "disarm"
        # El id que mando la app, nunca el nombre.
        assert cuerpo["dispositivo"] == "6C_C8_40_4F_C7"
        assert cuerpo["confirmar"] is True
        # Y el "motivo" del registro no se le manda a la app.
        assert "motivo" not in cuerpo
        # Las claves se traducen al ingles solo para el LLM.
        assert ia.equipos[0] == {"id": "6C_C8_40_4F_C7", "name": "Casa",
                                 "is_armed": True, "is_online": True}
        # Registrado como el bot, para que las dos vias caigan en el mismo analisis.
        entrada = api._bot.interaction_logger.entradas[0]
        assert entrada["response_type"] == "action", entrada
        assert entrada["intent"] == "disarm"
        assert entrada["user_id"] == "app:u1"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


async def caso_nombre_desconocido_no_desarma_todo():
    """El bug del bot, que aqui no se copia: sin coincidencia, aviso."""
    ia = IAFalsa({"intent": "disarm", "device": "garage", "confidence": 0.95})

    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno",
            cuerpo={"pregunta": "apaga la alarma del garage", "dispositivos": EQUIPOS},
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["tipo"] == "aviso", cuerpo
        assert "accion" not in cuerpo and "dispositivo" not in cuerpo
        assert "Casa" in cuerpo["texto"]
        entrada = api._bot.interaction_logger.entradas[0]
        assert entrada["ok"] is False and entrada["error"] == "device_not_found"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


async def caso_confianza_baja_no_ejecuta_nada():
    """
    El umbral de 0.6 es la unica barrera contra una orden inventada. Se usa el
    `AIHandler` de verdad -sin red, con la llamada al LLM sustituida- porque el
    umbral vive ahi y una IA de mentira no lo probaria.
    """
    import ai_handler

    ia = ai_handler.AIHandler(llm_backend="ollama", groq_api_key="")

    async def responde(**kw):
        return ('{"intent":"disarm","device":"Casa","confidence":0.59,'
                '"reply":"ok","params":{}}')

    ia._call_llm = responde

    async def p(url, api):
        estado, cuerpo = await pedir(
            url, token="bueno",
            cuerpo={"pregunta": "apaga eso", "dispositivos": EQUIPOS},
        )
        assert estado == 200, (estado, cuerpo)
        assert cuerpo["tipo"] == "rag", f"se ejecuto con confianza 0.59: {cuerpo}"
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


async def caso_un_equipo_sin_id_no_llega_al_modelo():
    """
    Un equipo sin `id` no se puede resolver despues, asi que ensenarselo al
    modelo solo sirve para que lo nombre y acabe en «no encontre ninguno». Que
    entre en el prompt y no en la resolucion es la unica forma de que pase.
    """
    ia = IAFalsa()

    async def p(url, api):
        await pedir(
            url, token="bueno",
            cuerpo={
                "pregunta": "arma la alarma",
                "dispositivos": EQUIPOS + [{"nombre": "Fantasma", "armado": False}],
            },
        )
        assert ia.llamadas == 1
        nombres = [e["name"] for e in ia.equipos]
        assert "Fantasma" not in nombres, ia.equipos
        assert len(ia.equipos) == len(EQUIPOS)
    await con_api(FirebaseFalso(["AA_BB"]), "u1", p, ia=ia)


CASOS = [
    caso_elige_el_tunel_de_su_puerto,
    caso_salud_no_pide_token,
    caso_sin_cabecera_401,
    caso_token_malo_401,
    caso_sin_equipos_403,
    caso_firebase_caido_no_abre_la_puerta,
    caso_pregunta_vacia_400,
    caso_feliz,
    caso_rafaga_429,
    caso_modo_clave_exige_la_cabecera,
    caso_modo_clave_sin_clave_configurada_no_abre,
    caso_modo_abierto_deja_pasar_y_sigue_contando,
    caso_cabecera_falsificada_no_estrena_cuota,
    caso_preflight_contesta,
    caso_las_respuestas_llevan_cors,
    caso_cors_cerrado_no_devuelve_cabecera,
    caso_sin_dispositivos_responde_como_siempre,
    caso_intent_none_cae_al_rag,
    caso_una_orden_vuelve_como_accion,
    caso_nombre_desconocido_no_desarma_todo,
    caso_confianza_baja_no_ejecuta_nada,
    caso_un_equipo_sin_id_no_llega_al_modelo,
]


async def correr_todo():
    fallos = 0
    for c in CASOS:
        try:
            await c()
            print(f"  ok  {c.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {c.__name__}: {e}")
        except Exception as e:
            fallos += 1
            print(f"ERROR  {c.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(CASOS) - fallos}/{len(CASOS)} pruebas pasan")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(correr_todo()) else 0)
