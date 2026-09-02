# Endpoint HTTP de Senti

Permite que la app pregunte a Senti sin pasar por Telegram. Contesta
`knowledge_qa.responder()`, **el mismo motor que usa el bot**, asi que los dos
canales dan la misma respuesta a la misma pregunta: dos respuestas distintas
segun el canal serian un fallo dificil de ver.

```
app (WebView)  ->  ngrok  ->  127.0.0.1:8765  ->  knowledge_qa.responder()
```

Corre **en el mismo proceso que el bot**: `KnowledgeBase` construye embeddings e
indice TF-IDF al cargar, y un segundo proceso los pagaria enteros en cada
arranque ademas de tener su propia copia en memoria.

Escucha en `127.0.0.1`. Quien lo publica hacia fuera es ngrok o un proxy
inverso, **nunca este proceso**: en `0.0.0.0` quedaria expuesto a toda la red
del VPS.

---

## Rutas

### `POST /preguntar`

```http
POST /preguntar
Authorization: Bearer <idToken de Firebase>
Content-Type: application/json
ngrok-skip-browser-warning: 1

{"pregunta": "como configuro la bengala"}
```

```json
{
  "texto": "La bengala se configura desde la ficha del equipo...",
  "fuente": "08_bengala.md | 04_app_sentinel_guard.md",
  "tipo": "rag"
}
```

La pregunta se recorta a **500 caracteres**: entra en el prompt del LLM, asi que
un campo sin limite es una factura sin limite.

| Codigo | Cuando |
|---|---|
| `200` | Respuesta (aunque `tipo` sea `fallback` o `error`) |
| `400` | Cuerpo no es JSON, o pregunta vacia |
| `401` | Falta el token, o no es valido |
| `403` | El uid no tiene ningun equipo vinculado |
| `429` | Tope de uso — el mensaje dice cuanto falta |
| `503` + `reintentar_en` | El LLM no da abasto ahora mismo. **Reintentable** |
| `503` sin `reintentar_en` | El asistente no esta configurado. NO se arregla esperando |

### Ocupado: el 503 que si merece reintentarse

Cuando hay demasiadas consultas en cola, el endpoint rebota en vez de dejar
esperando a alguien que ya no va a llegar a tiempo:

```json
HTTP 503
Retry-After: 5
{ "error": "Estoy atendiendo otras consultas en este momento. Vuelve a preguntarme en unos segundos.",
  "reintentar_en": 5 }
```

**Lo que distingue "ocupado" de "caido" es la presencia de `reintentar_en` en el
cuerpo, no el codigo.** El 503 a secas ya significaba "el asistente no esta
configurado", que es lo contrario: eso no se arregla esperando. Se manda tambien
`Retry-After`, pero la app no necesita leer cabeceras: el campo del cuerpo basta,
y el texto viaja en `error` como en el resto de rechazos.

El `429` sigue siendo otra cosa distinta: "has preguntado demasiadas veces tu",
no "el servidor esta lleno".

### `GET /salud`

Sin autenticacion. `{"ok": true, "kb": true, "ia": true}`. Si `kb` o `ia` salen
`false`, el endpoint responde pero no sabe contestar.

### `OPTIONS *`

`204` con las cabeceras CORS. Lo necesita el navegador antes de cada peticion
con cabeceras propias.

---

## Quien puede entrar

Dos condiciones, las dos obligatorias:

1. **ID token de Firebase valido**, verificado contra Firebase Auth.
2. **Al menos un equipo** en `Usuarios/{uid}/Dispositivos`.

La segunda se apoya en un dato que ya existe, en vez de una lista aparte que
habria que mantener a mano y que se desincronizaria el primer dia. Si Firebase
no contesta **no se deja pasar**: un fallo de lectura no puede convertirse en
una puerta abierta.

> De las 35 cuentas en `/Usuarios`, solo 15 tienen equipos vinculados
> (revisado el 2026-09-01). Las otras 20 reciben `403`.

### Modos de autenticacion (`API_AUTH`)

| Modo | Como identifica | Para que |
|---|---|---|
| `firebase` | ID token en `Authorization: Bearer` | **Produccion** |
| `clave` | Clave compartida en `X-Api-Key` | Demos sin sesion |
| `abierto` | Nada | Solo en local, **nunca detras de ngrok** |

La clave se compara con `hmac.compare_digest` y no con `==`: comparar cadenas
normalmente tarda mas cuanto mas coincide el principio, y eso deja adivinarla
caracter a caracter midiendo tiempos.

En los modos sin usuario real el tope cuenta por IP, leyendo el **ultimo** valor
de `X-Forwarded-For` — cada proxy añade al final la IP de quien le hablo, asi
que el primero es el que escribe el cliente y falsificarlo es escribir una
cabecera.

---

## Tope de uso

Dos limites por usuario, porque hacen falta los dos:

- **20 preguntas por hora** (`API_MAX_POR_HORA`) — el gasto sostenido.
- **3 segundos entre preguntas** (`API_ESPERA_MIN_SEG`) — la rafaga. Un bucle
  mal escrito dispara veinte peticiones en dos segundos y el limite por hora no
  las para hasta que ya se gastaron.

Vive en memoria: el servicio es un solo proceso y el tope no tiene que
sobrevivir a un reinicio. Con varias instancias habria que moverlo a Redis.

---

## CORS

El WebView de la app corre en `https://localhost`, asi que llamar al tunel es
cruzar a otro dominio. Y como las peticiones llevan cabeceras propias
(`Authorization` y la de ngrok), el navegador manda antes un `OPTIONS` de
reconocimiento.

`API_CORS` controla los origenes; por defecto `*`. **Aqui `*` es seguro**: la
barrera es el ID token, que viaja en una cabecera puesta a mano, y no se usan
cookies. CORS solo decide quien puede *leer* la respuesta, y sin token no hay
respuesta que leer.

> Desde `curl` nada de esto se nota, porque curl no aplica CORS. Es lo que hizo
> que 16 pruebas estuvieran en verde mientras la app no conseguia ni hacer un
> GET.

---

## La URL publica

Con el plan gratuito de ngrok la URL cambia en cada reinicio, asi que el VPS le
pregunta a la API local del agente y publica la que toque en RTDB:

```
Config/ai_endpoint = { "url": "https://....ngrok-free.app", "actualizado": 1788306602 }
```

La app la lee de ahi en vez de llevarla compilada dentro. Se publica **el tunel
que apunta a nuestro puerto**, no el primero: el agente puede estar sirviendo
otros proyectos, y anunciar el de otro no se ve — la URL existe y contesta,
solo que contesta otra cosa.

---

## Lo que la app debe hacer

1. Leer la URL de `Config/ai_endpoint` (no compilarla).
2. Mandar el ID token en `Authorization: Bearer <token>`.
3. Añadir siempre `ngrok-skip-browser-warning: 1`, o ngrok devuelve su pantalla
   de aviso en lugar del JSON.
4. Tratar `403` como "cuenta sin equipos vinculados", no como error generico.
5. Tratar un `503` **con `reintentar_en`** como reintentable y pintarlo como un
   mensaje normal, no como "sin conexion": la conexion estaba bien.
6. Cortar por su cuenta a los **45 s**. El endpoint se compromete a contestar
   antes -su presupuesto son 40 s, `API_BUDGET_SEC`-, asi que ese corte es la
   red de seguridad y no deberia dispararse nunca.

---

## Configuracion

| Clave | Defecto | |
|---|---|---|
| `API_ENABLED` | `false` | Apagado por defecto |
| `API_HOST` | `127.0.0.1` | No cambiar sin motivo |
| `API_PORT` | `8765` | |
| `API_AUTH` | `firebase` | |
| `API_CLAVE` | vacio | Solo con `API_AUTH=clave` |
| `API_CORS` | `*` | Origenes permitidos |
| `API_MAX_POR_HORA` | `20` | |
| `API_ESPERA_MIN_SEG` | `3` | |
| `NGROK_API` | `http://127.0.0.1:4040/api/tunnels` | **En el VPS: `4041`** |
| `API_RUTA_URL` | `Config/ai_endpoint` | Donde se publica la URL |

Ver [DESPLIEGUE.md](DESPLIEGUE.md) para el detalle de ngrok en el VPS.
