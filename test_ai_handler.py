"""
Los defaults del handler, sin red y sin levantar nada.

El fallo que vigila: el nombre del modelo de Ollama esta escrito DOS veces
-`config.AIConfig.ollama_model` y el parametro de `AIHandler.__init__`- y hasta
2026-09 las dos decian "gtp-oss:20b", con la p y la t cambiadas de sitio. En un
VPS que no declare INTENT_MODEL, CHAT_MODEL ni OLLAMA_MODEL, el handler acaba
pidiendole a Ollama ese nombre y Ollama responde "model not found": ni
clasificador ni RAG, y el .env no lo delata porque ahi no pone nada.

    python test_ai_handler.py
"""
import asyncio
import inspect
import sys
from types import SimpleNamespace

import httpx

import ai_handler
from config import AIConfig


def _handler(**kw):
    kw.setdefault("llm_backend", "ollama")
    kw.setdefault("groq_api_key", "")
    return ai_handler.AIHandler(**kw)


class _RespuestaOllama:
    """Lo minimo que `_call_ollama` le pide a httpx."""

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": "ok"}}


def test_el_modelo_de_ollama_se_llama_igual_en_los_dos_sitios():
    """Dos copias del mismo nombre: lo unico que las mantiene juntas es esto."""
    del_constructor = inspect.signature(
        ai_handler.AIHandler.__init__
    ).parameters["ollama_model"].default
    assert del_constructor == AIConfig().ollama_model, (
        f"el default del constructor ({del_constructor!r}) no es el de config "
        f"({AIConfig().ollama_model!r})"
    )


def test_el_default_de_ollama_no_es_un_nombre_inventado():
    """
    No se comprueba contra una lista de modelos -eso caduca-, sino contra la
    forma: `familia:tamano`, y que la familia no sea el typo conocido.
    """
    nombre = AIConfig().ollama_model
    assert ":" in nombre, f"{nombre!r} no tiene la forma modelo:tag de Ollama"
    assert "gtp" not in nombre, f"{nombre!r}: 'gtp' es el typo de 'gpt'"


def test_el_json_se_encuentra_aunque_venga_rodeado_de_razonamiento():
    """
    El regex viejo era `\\{.*\\}` con DOTALL, goloso: capturaba desde la primera
    llave hasta la ultima de toda la respuesta. Si el modelo repasa el esquema
    en voz alta antes de contestar, hay llaves antes del JSON bueno y se
    tragaba todo lo de en medio.
    """
    p = ai_handler.AIHandler._parse_intent_json
    crudo = (
        'The schema is {"intent": "...", "device": "..."}. The user asks how '
        'many devices, so intent list_devices.\n'
        '{"intent": "list_devices", "device": "all", "confidence": 0.9, '
        '"reply": "Tienes 1 equipo."}'
    )
    r = p(crudo)
    assert r is not None, "no encontro el JSON detras del razonamiento"
    assert r["intent"] == "list_devices", r
    assert r["confidence"] == 0.9, r


def test_una_llave_dentro_de_una_cadena_no_descuadra_el_parser():
    """Por esto se usa `raw_decode` y no un contador de profundidad."""
    p = ai_handler.AIHandler._parse_intent_json
    r = p('{"intent": "question", "device": null, "confidence": 0.9, '
          '"reply": "Escribe {comando} para verlo."}')
    assert r["reply"] == "Escribe {comando} para verlo.", r


def test_un_json_cortado_a_media_cadena_no_pasa_por_bueno():
    """
    El fallo real de produccion: el razonamiento se comia `max_tokens` y el
    JSON llegaba cortado. No hay forma honesta de completarlo, asi que se
    devuelve None y quien pregunta acaba en el RAG -pero el techo de tokens
    sube para que deje de pasar-.
    """
    p = ai_handler.AIHandler._parse_intent_json
    assert p('{\n "intent": "disarm",\n "device": "garage",\n '
             '"confidence": 0.9,\n "reply": "Entendido, desactivando la') is None
    assert ai_handler.TOKENS_INTENT >= 512, ai_handler.TOKENS_INTENT


def test_ningun_default_clava_el_nombre_de_un_modelo():
    """
    El fallo que costo cuatro observaciones en produccion: el default de
    `intent_model` era "llama-3.1-8b-instant", que dejo de existir en Groq. Cada
    clasificacion daba 404, caia a la reserva de Ollama -un modelo de
    razonamiento que deja `content` vacio- y las ordenes acababan contestadas
    con documentacion.

    Clavar el nombre de un modelo de un proveedor es apostar a que ese nombre
    siga vivo. Que sigan al backend: si el backend contesta, el modelo existe.
    """
    c = AIConfig()
    assert c.intent_model == "", f"intent_model default clava {c.intent_model!r}"
    assert c.chat_model == "", f"chat_model default clava {c.chat_model!r}"

    h = ai_handler.AIHandler(
        llm_backend="groq", groq_api_key="x", groq_model=c.groq_model,
        intent_model=c.intent_model, chat_model=c.chat_model,
    )
    assert h._intent_model == c.groq_model, h._intent_model
    assert h._chat_model == c.groq_model, h._chat_model


def test_una_respuesta_vacia_no_pasa_por_buena():
    """
    Groq devolviendo "" subia como respuesta valida y el usuario recibia un
    mensaje que solo decia "(Fuente: ...)". `_call_ollama` ya lo comprobaba;
    `_call_groq` no. Visto en produccion.
    """
    import inspect
    fuente = inspect.getsource(ai_handler.AIHandler._call_groq)
    assert "empty response" in fuente, "_call_groq no comprueba la respuesta vacia"
    assert "empty response" in inspect.getsource(ai_handler.AIHandler._call_ollama)


def test_con_backend_ollama_ningun_modelo_acaba_siendo_de_groq():
    """
    Los defaults de intent/chat SON modelos de Groq mientras el backend por
    defecto es ollama. `__init__` lo detecta y los sustituye; esta prueba
    comprueba que la sustitucion sigue ocurriendo, porque sin ella el handler
    le pide a Ollama un modelo que solo existe en Groq.
    """
    h = ai_handler.AIHandler(
        llm_backend="ollama",
        intent_model=AIConfig().intent_model,
        chat_model=AIConfig().chat_model,
        groq_api_key="",
    )
    for etiqueta, modelo in (("intent", h._intent_model), ("chat", h._chat_model)):
        assert not ai_handler._looks_like_groq_model(modelo) or \
            ai_handler._looks_like_ollama_model(modelo), \
            f"{etiqueta}_model={modelo!r} es de Groq con backend=ollama"


# --------------------------------------------------------------------------
# La pila
# --------------------------------------------------------------------------

def test_la_pila_limita_cuantas_llamadas_hay_a_la_vez():
    """
    Se prueba a traves de `_call_ollama` y no del `_turno` a pelo: lo que hay
    que vigilar es que la llamada real siga pasando por la pila, no que un
    gestor de contexto suelto funcione.
    """
    h = _handler(max_concurrent=2, max_cola=99)
    a_la_vez = maximo = 0

    async def post(*a, **k):
        nonlocal a_la_vez, maximo
        a_la_vez += 1
        maximo = max(maximo, a_la_vez)
        await asyncio.sleep(0.01)
        a_la_vez -= 1
        return _RespuestaOllama()

    h._http_client = SimpleNamespace(post=post)

    async def correr():
        await asyncio.gather(*[h._call_ollama("s", "u") for _ in range(20)])

    asyncio.run(correr())
    assert maximo <= 2, f"{maximo} llamadas a la vez con max_concurrent=2"


def test_la_cola_llena_rebota_en_vez_de_hacer_esperar():
    """
    Sin este limite el semaforo solo mueve el atasco: el que no cabe espera
    turno hasta que se le acaba el techo y recibe un timeout DESPUES de haber
    ocupado sitio. Aqui tiene que rebotar y ademas hacerlo rapido.
    """
    h = _handler(max_concurrent=1, max_cola=2)
    suelta = asyncio.Event()

    async def correr():
        async def ocupar():
            async with h._turno():
                await suelta.wait()

        # Dos dentro (una corriendo, una esperando turno): la cola esta llena.
        tareas = [asyncio.create_task(ocupar()) for _ in range(2)]
        await asyncio.sleep(0)  # que lleguen a entrar
        assert h._en_cola == 2, h._en_cola

        try:
            async with h._turno():
                raise AssertionError("la tercera deberia haber rebotado")
        except ai_handler.LlmOcupado:
            pass

        suelta.set()
        await asyncio.gather(*tareas)
        # Y al soltar, el contador vuelve a cero: nadie se queda ocupando sitio.
        assert h._en_cola == 0, h._en_cola

    asyncio.run(correr())


# --------------------------------------------------------------------------
# La cadena de reserva
# --------------------------------------------------------------------------

def _con_backends(h, fallo):
    """Sustituye los dos backends y devuelve la lista de a quien se llamo."""
    llamadas = []

    async def groq(*a, **k):
        llamadas.append("groq")
        raise fallo

    async def ollama(*a, **k):
        llamadas.append("ollama")
        return "ok"

    h._call_groq, h._call_ollama = groq, ollama
    return llamadas


def test_un_timeout_no_se_cobra_dos_veces():
    """
    Si el backend expira, probar el otro es gastar el presupuesto entero otra
    vez con el mismo usuario esperando -y, con la pila delante, quitarle el
    sitio a alguien que todavia podia llegar-.
    """
    h = _handler(llm_backend="groq")
    llamadas = _con_backends(h, asyncio.TimeoutError())

    try:
        asyncio.run(h._call_llm("s", "u"))
        raise AssertionError("el timeout tenia que salir hacia arriba")
    except asyncio.TimeoutError:
        pass

    assert llamadas == ["groq"], llamadas


def test_un_backend_que_no_esta_si_cae_a_la_reserva():
    """Una conexion rehusada es instantanea: al otro le queda todo el tiempo."""
    h = _handler(llm_backend="groq")
    llamadas = _con_backends(h, httpx.ConnectError("connection refused"))

    assert asyncio.run(h._call_llm("s", "u")) == "ok"
    assert llamadas == ["groq", "ollama"], llamadas


def test_ocupado_tampoco_cae_a_la_reserva():
    """La pila la comparten los dos backends: si esta llena, lo esta para todos."""
    h = _handler(llm_backend="groq")
    llamadas = _con_backends(h, ai_handler.LlmOcupado("llena"))

    try:
        asyncio.run(h._call_llm("s", "u"))
        raise AssertionError("LlmOcupado tenia que salir hacia arriba")
    except ai_handler.LlmOcupado:
        pass

    assert llamadas == ["groq"], llamadas


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
