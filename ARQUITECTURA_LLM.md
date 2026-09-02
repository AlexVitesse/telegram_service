# La pila del LLM y el reparto de tiempo

Plan para el cuello de botella actual: **no hay nada que limite cuantas llamadas
al LLM hay en vuelo a la vez, y el techo de tiempo se calcula por llamada en vez
de por peticion**. Las dos cosas se arreglan con un semaforo y un numero, no con
una cola externa.

Fases independientes: cada una se puede desplegar sola y deja una prueba detras.
Ninguna necesita las siguientes para tener sentido.

---

## Antes de nada: el backend de hoy NO es local

En el `.env` de este repo:

    LLM_BACKEND=groq
    GROQ_MODEL=openai/gpt-oss-20b
    OLLAMA_BASE_URL=http://localhost:11434
    OLLAMA_EMBED_MODEL=nomic-embed-text

Groq es **remoto**. Ollama aparece solo para *embeddings* (`nomic-embed-text`) y
como reserva si Groq falla (`ai_handler.py:297`, `_call_llm`). El `.env` del VPS
no esta en git, asi que esto hay que confirmarlo alli:

    grep -E '^LLM_BACKEND|^OLLAMA_MODEL' .env    # en el VPS

Cambia el diagnostico, no el plan:

| | Local (Ollama) | Remoto (Groq, lo que dice este .env) |
|---|---|---|
| 10 peticiones a la vez | Ollama las **serializa** en su propia cola: la 10ª empieza cuando acaba la 9ª | Salen a la vez; el limite es el *rate limit* de Groq (429) |
| Sintoma | Todos esperan y **todos expiran a la vez**, y la maquina sigue generando texto que ya nadie va a leer | 429, y la cadena de reserva cae a Ollama, que es lento |
| `LLM_MAX_CONCURRENT` | `1`-`2` | `4`-`8` |

En los dos casos el semaforo es el mismo codigo. Solo cambia el numero.

---

## El problema, con los numeros de hoy

Con `LLM_TIMEOUT_SEC=20` (`config.py:85`), una peticion de la app:

    preguntar()                                        api_server.py:207
    ├─ limitador (tope de uso)                         instantaneo
    ├─ _como_orden -> parse_intent      techo 10 s     llm_timeout_sec / 2
    │                 └─ _call_llm: backend A, y si falla, B (en serie)
    └─ knowledge_qa.responder           techo 45 s     llm_timeout_sec * 2 + 5
                      └─ _call_llm: otra vez A y luego B
                                        ─────────
                        peor caso        55 s, y ninguno de los dos sabe del otro

Tres cosas mal, por orden de gravedad:

1. **Nadie cuenta cuantas hay en vuelo.** Ni semaforo, ni cola, ni limite.
   `grep -rn "Semaphore" *.py` solo encuentra los locks de comandos del bot.
2. **El presupuesto se multiplica en vez de repartirse.** Cada tramo calcula su
   techo desde `llm_timeout_sec` como si fuera el unico. 10 + 45 no es un
   presupuesto, es una suma que a nadie le consta.
3. **El fallback cobra el tiempo dos veces.** Si el backend A **expira**,
   `_call_llm` prueba el B con el techo entero otra vez. Un timeout no es un "no
   estaba disponible": ya te gastaste el presupuesto esperando.

Y un cabo suelto: `telegram_bot.py:1727` llama a `parse_intent` **sin
`wait_for`**. El endpoint si lo lleva; el bot no.

---

## Fase 0 — Medir. Media hora, cero codigo

El registro que hace falta ya existe: `interaction_logger` guarda `elapsed_ms`,
`backend`, `response_type` y `ok` en cada interaccion, de las dos vias, en
`logs/ai_interactions.jsonl`.

**Lo tiene que ejecutar Eric**: al VPS se entra por VNC, no por SSH. Es de solo
lectura:

    cd /home/space-user2/telegram_service && /home/space-user2/envs/deepseek/bin/python - <<'PY'
    import json,collections
    xs=[];b=collections.Counter()
    for l in open('logs/ai_interactions.jsonl',encoding='utf-8'):
        try: d=json.loads(l)
        except: continue
        b[d.get('backend')]+=1
        if d.get('response_type')=='rag' and d.get('elapsed_ms'): xs.append(d['elapsed_ms']/1000)
    xs.sort(); p=lambda q: xs[min(len(xs)-1,int(len(xs)*q))]
    print(len(xs),'respuestas RAG | backends:',dict(b))
    if xs: print('p50 %.1fs  p90 %.1fs  p95 %.1fs  max %.1fs  |  por encima de 20s: %d'%(p(.5),p(.9),p(.95),xs[-1],sum(1 for x in xs if x>20)))
    PY

**Por que primero:** si el p95 son 3 s y nunca hay dos a la vez, no hay cuello de
botella y las fases 1 y 2 son codigo que no hay que escribir. Si el p95 se pega a
los 10 s o a los 45 s, ya sabemos cual de los dos techos duele. Y el p95 del RAG
es el numero que decide el reparto de la fase 2.

---

## Fase 1 — La pila: un semaforo en `_call_llm`

Todo pasa por `ai_handler._call_llm` (`ai_handler.py:297`). Un solo sitio.

    # ai_handler.py, en __init__
    self._pila = asyncio.Semaphore(max_concurrent)
    self._en_cola = 0

    # envolviendo _call_llm
    if self._en_cola >= self._max_cola:
        raise LlmOcupado()        # no encolar a quien ya no va a llegar a tiempo
    self._en_cola += 1
    try:
        async with self._pila:
            ...lo que ya hace hoy...
    finally:
        self._en_cola -= 1

Dos numeros nuevos en `AIConfig`, con el resto:

- `LLM_MAX_CONCURRENT` — cuantas a la vez. `2` por defecto (`1` si el backend es
  Ollama y el VPS va justo).
- `LLM_MAX_QUEUE` — cuantas esperando antes de decir que no. `8`.

**El limite de cola no es un adorno.** Un semaforo sin el solo mueve el atasco:
la peticion espera turno, se le acaba el `wait_for` mientras espera, y el usuario
recibe un timeout *despues* de haber ocupado un sitio en la cola. Con
`LlmOcupado`, quien no cabe recibe en 0 ms un "estoy ocupado, prueba en un
momento", que es una respuesta honesta y ademas barata.

- Al esperar el turno **dentro** del `wait_for` que ya esta puesto, el techo
  sigue cubriendo la espera. No hace falta un temporizador nuevo.
- La via "orden" (`_como_orden`) ya trata cualquier excepcion como "al RAG": un
  `LlmOcupado` ahi cae solo en el camino de siempre. El RAG si tiene que
  contestar el texto de ocupado.

**Prueba** (`test_ai_handler_pila.py`): 20 corrutinas contra un `_call_llm` falso
que apunta el maximo de simultaneas; `assert maximo <= 2`, y que a partir de la
10ª sale `LlmOcupado` sin haber esperado.

### Como se contesta "ocupado" (acordado con la sesion de la app)

**El codigo solo no sirve para distinguirlo**: `api_server.py:101` ya devuelve
503 para "El asistente no está configurado", que es justo lo contrario de
reintentable. Y 429 es el tope por usuario. Contrato:

    HTTP 503
    Retry-After: 5
    {"error": "Estoy atendiendo otras consultas. Prueba en unos segundos.",
     "reintentar_en": 5}

Reintentable es **la presencia de `reintentar_en` en el cuerpo**, no el codigo.
503 sin `reintentar_en` sigue significando caido. Se mantiene la forma
`{"error": ...}` porque el `mensajeDeError()` de la app ya prefiere ese texto
sobre uno generico, asi que la frase llega literal sin que ellos toquen nada.

Contexto del lado de la app: hoy **cualquier** respuesta no-2xx marca el
asistente como caido y pinta "Sin conexión con el asistente"
(`asistente-chat.service.ts:302`). Sin este contrato, nuestro "estoy ocupado" se
veria como "no hay conexion", que es lo contrario de lo que queremos decir.

**Lo que NO se hace:** ni Redis, ni Celery, ni un proceso worker, ni prioridad
entre bot y app. `asyncio.Semaphore` es la cola. Si algun dia hay que sobrevivir
a un reinicio del proceso con trabajo a medias, entonces se habla de una cola de
verdad — y no antes.

---

## Fase 2 — Un presupuesto por peticion, no por llamada

Un numero, `API_BUDGET_SEC` (40 s: los 45 del cliente menos margen), y
`preguntar()` lo reparte:

    limite = time.monotonic() + config.api.budget_sec
    ...
    await asyncio.wait_for(ia.parse_intent(...), timeout=restante(limite) / 2)
    await knowledge_qa.responder(..., timeout=restante(limite))

`restante()` son tres lineas. Lo que se llevo el clasificador se le descuenta al
RAG, en vez de que cada uno pida los suyos como si fuera el primero.

**Por que importa:** hoy el peor caso son 55 s, y **la app no tiene timeout**.
Verificado por la sesion de la app: `AsistenteChatService.preguntar()`
(`asistente-chat.service.ts:290`) hace un `fetch` sin `signal` ni
`AbortController`; no hay ninguno en todo `src/app`. Asi que hoy los 55 s no
producen "respuestas que nadie recibe" — las recibe, despues de 55 s de
animacion de "pensando", y solo si el sistema operativo no mato antes la
peticion por un cambio de radio o por el doze. Van a poner 30 s con
`AbortController` (pendiente de aprobacion de su usuario).

**La regla que sale de ahi, y es la importante:** el presupuesto del servidor
tiene que ser **estrictamente menor** que el timeout del cliente. Si ellos
cortan y nosotros seguimos en 55, solo hemos cambiado "colgado para siempre" por
"abort mientras el VPS sigue generando": el usuario ve un error igual y el
modelo se paga igual.

**El numero del cliente ya es firme: 45 s**, decidido por su usuario e
implementado (`AbortController`, no `AbortSignal.timeout()`, que falta en
WebViews viejos). Asi que aqui hay **40 s** para repartir: **10 s de
clasificador + 28 s de RAG + 2 de margen**. Con ese aire, el p95 de la fase 0
pasa de decidir el numero a confirmarlo — sigue mereciendo la pena correrlo,
pero ya no bloquea.

Si el cliente corta antes que nosotros, el usuario lee "Tardé demasiado en
contestar. Prueba a preguntarlo más corto". Ese texto no deberia verlo nadie: su
corte es la red de seguridad, no el camino normal.

**Prueba:** un `parse_intent` falso que tarda 9 s deja al RAG con ~21 s, no con
45. Y la suma total nunca pasa de `API_BUDGET_SEC`.

**De paso:** `telegram_bot.py:1727` recibe el mismo trato — `parse_intent` con
techo, como en el endpoint.

---

## Fase 3 — Que el fallback no cobre dos veces

En `_call_llm`, distinguir *no estaba* de *no llego a tiempo*:

    except Exception as e:
        if isinstance(e, (httpx.TimeoutException, asyncio.TimeoutError)):
            raise                  # ya se gasto el presupuesto esperando
        ...prueba el otro backend...

Una conexion rehusada o un 503 son instantaneos y el otro backend tiene todo el
tiempo por delante: ahi el fallback vale. Un timeout no. Ademas, con la fase 1
delante, cada reintento ocupa **otra** plaza de la pila: reintentar un timeout es
quitarle el sitio a alguien que todavia podia llegar.

**Prueba:** backend A que expira -> no se llama a B. Backend A que rehusa la
conexion -> si se llama a B.

---

## Fase 4 — Los dos cabos del commit anterior  ✅ HECHO

Dos lineas, sin discusion:

- `api_server._como_orden` le ensena al modelo equipos con `id` en `None` (solo
  filtra `isinstance(d, dict)`), pero `comandos_app._equipos` si los descarta.
  Resultado: un equipo sin `id` sale en el prompt y luego nunca se puede
  resolver. Anadir `and d.get("id")` a la comprension.
- `comandos_app.decidir` con `list_devices` y lista vacia devuelve accion sobre
  `"all"`. Hoy es inalcanzable porque `_como_orden` corta antes, pero es una
  trampa para el siguiente que llame al modulo directamente.

---

## Fase 6 — Los defaults piden un modelo que no existe  ✅ HECHO

Encontrado por la sesion de la app, confirmado aqui. Los valores por defecto de
`AIConfig` (`config.py:70-77`) son incoherentes entre si:

    llm_backend = "ollama"                    # local
    intent_model = "llama-3.1-8b-instant"     # modelo de Groq
    chat_model   = "openai/gpt-oss-20b"       # modelo de Groq

`AIHandler.__init__` (`ai_handler.py:199`) lo detecta y sustituye los dos por
`ollama_model`... cuyo default es **`"gtp-oss:20b"`** (`config.py:73` y
`ai_handler.py:179`): *gtp*, con la p y la t cambiadas de sitio. En un VPS que no
declare `INTENT_MODEL`, `CHAT_MODEL` ni `OLLAMA_MODEL` en su `.env`, tanto el
clasificador como el RAG acaban pidiendole a Ollama un modelo que no existe.

En esta maquina no salta porque el `.env` trae `LLM_BACKEND=groq`. Por eso hay
que mirar el `.env` del VPS antes de dar por bueno **cual** es el modelo que esta
contestando de verdad: puede no ser el que uno cree.

Arreglo: corregir el typo, y que los defaults de `intent_model` y `chat_model`
sigan al backend por defecto en vez de contradecirlo. Prueba: construir un
`AIHandler()` sin argumentos y comprobar que los tres modelos son del mismo
proveedor.

---

## Fase 5 — El fallback que desarma la casa entera (bot)  ✅ HECHO

`telegram_bot._resolve_device_ids_by_name` acaba en:

    return matched if matched else authorized_ids

Un nombre que no coincide con nada actua sobre **todos** los equipos: "apaga la
alarma del garage", sin ningun equipo llamado garage, desarma la casa. En el
endpoint ya no pasa — `comandos_app.resolver` devuelve aviso con cero o con dos
coincidencias — pero en el bot sigue vivo.

Reusar `comandos_app.resolver` en el bot y borrar el fallback. Es el mismo
emparejamiento, ya probado, y deja de haber dos.

**No es arquitectura, es seguridad.** Si solo se hace una fase de esta lista, que
sea esta.

---

## Orden y coste

| Fase | Que arregla | Tamano | Depende de |
|---|---|---|---|
| 0 Medir | Saber si 1 y 2 hacen falta, y el reparto de la 2 | 0, lo corre Eric | — |
| ✅ 5 Bot | Desarme accidental de toda la casa | hecho | — |
| ✅ 4 Cabos | Dos trampas menores | hecho | — |
| ✅ 6 Defaults | Pedirle a Ollama un modelo mal escrito | hecho | — |
| 1 Pila | Que 10 a la vez no expiren las 10 | ~15 lineas | 0 |
| 2 Presupuesto | 55 s de peor caso -> 40 s repartidos | ~20 lineas | 1 (los 45 s de la app ya estan) |
| 3 Fallback | Pagar el timeout dos veces | ~4 lineas | 1 |

Fuera de este plan, a proposito: cache de preguntas repetidas (la clave ya
existe, `normalizar_pregunta`), *circuit breaker* por backend, metricas
Prometheus, cola persistente. Todo eso se anade **cuando la fase 0 ensene el
numero que lo justifique**, no antes.
