# Despliegue en el VPS

Como se actualiza `telegram_service` en produccion. Los pasos van en orden y el
orden importa: casi cada rareza de esta guia viene de un fallo que ya paso.

## El entorno

| | |
|---|---|
| Maquina | `condor-ia`, usuario `space-user2` |
| Acceso | `ssh -p 2222 space-user2@100.87.103.87` (sshd userland via Tailscale). VNC queda de rescate |
| Ruta | `/home/space-user2/telegram_service` |
| Interprete | `/home/space-user2/envs/deepseek/bin/python` |
| Origen | `github.com/AlexVitesse/telegram_service`, rama `main` |

**No hay `sudo`, ni systemd de usuario** (`systemctl --user` falla: no hay
sesion D-Bus persistente), **ni `screen`, ni `tmux`**. El servicio es un
proceso suelto lanzado a mano.

---

## Procedimiento

### 1. Parar, y confirmar que paro

`SIGTERM` tarda mas de diez segundos en cerrar. Arrancar sin comprobarlo deja
**dos instancias** peleandose el polling de Telegram, con respuestas duplicadas
y errores de `Conflict`.

**Por SSH, `pgrep -f "python main.py"` se encuentra A SI MISMO.** El comando
remoto contiene esa cadena, asi que `pgrep -f` devuelve tambien el PID del
propio `bash -c` y la comprobacion de "ya murio" miente: da vivo siempre. Paso
el 2026-09-07 y dejo el servicio a medio morir -proceso vivo, puerto 8765 ya
cerrado-, que es el estado del que habla el paso 5. Por eso los bloques de aqui
filtran con `[m]ain\.py` o con `pgrep -u $USER -a python`, que compara el nombre
del proceso -el mio es `bash`- y no puede autoencontrarse.

En esa maquina corren otros servicios del mismo usuario (`admin_bot.py`, un
uvicorn en el 8001, `ml_bot`). Filtrar siempre por `main.py`.

```bash
cd /home/space-user2/telegram_service
PID=$(pgrep -u $USER -a python | grep -w "main.py" | cut -d" " -f1)
kill $PID
for i in $(seq 20); do ps -p $PID >/dev/null || break; sleep 1; done
ps -p $PID >/dev/null && { kill -9 $PID; sleep 2; }
ps -p $PID || echo detenido
```

Matar a la fuerza es de bajo riesgo: solo se pierde el cierre limpio de MQTT y
el volcado de `schedule_config.json`, que se resincroniza desde Firebase al
arrancar.

### 2. Actualizar, y solo despues instalar

El `pip install` va **despues** del `pull`. Al reves leeria el
`requirements.txt` viejo y no veria las dependencias nuevas.

```bash
git pull origin main
/home/space-user2/envs/deepseek/bin/pip install -r requirements.txt
```

### 3. Probar antes de arrancar

Segundos, sin red ni LLM. Si algo falla aqui, no arranques.

```bash
python test_api_server.py && python test_api_limites.py
python test_scheduler.py && python test_knowledge_qa.py
```

### 4. Arrancar desprendido de la terminal

```bash
setsid nohup /home/space-user2/envs/deepseek/bin/python main.py \
  > /dev/null 2>> arranque_errores.log < /dev/null &
sleep 10
ps -o pid,ppid,cmd -u $USER | grep main.py | grep -v grep
```

El **PPID debe ser 1**: sin `setsid` el servicio muere al cerrar la sesion VNC.

**`stdout` va a `/dev/null` a proposito.** `main.py` ya escribe
`alarm_service.log` con un `RotatingFileHandler`; redirigir ahi tambien la
salida estandar duplica cada linea del log y rompe la rotacion — el handler
renombra el archivo a los 10 MB pero el shell sigue escribiendo al viejo por su
descriptor.

### 5. Verificar

```bash
cat arranque_errores.log                                    # vacio
grep -E "Scheduler:|publicada en Config" alarm_service.log | tail -2
curl -s http://127.0.0.1:8765/salud                         # {"ok": true, ...}
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8765/preguntar \
  -H 'Content-Type: application/json' -d '{"pregunta":"hola"}'   # 401
```

En Telegram: `/id`, `/horarios` y una pregunta libre al bot.

**El `curl` a `/salud` no es opcional, y probar por Telegram NO lo sustituye.**
El bot habla directo con la API de Telegram: no pasa por `aiohttp` ni por ngrok.
Asi que el endpoint puede estar muerto y el bot contestar perfectamente. Paso el
2026-09-02: dos instancias a la vez, la segunda no pudo coger el puerto 8765, se
mato a la primera -que era la que lo tenia- y quedo un servicio con el bot
funcionando y sin API. Cuatro preguntas por Telegram salieron bien mientras la
app recibia `Failed to fetch`.

Y **usa los bloques de este documento tal cual**. El que dejo el sistema asi fue
un `kill <pid>` escrito a mano con el hueco sin rellenar: bash leyo el `<` como
una redireccion, dio error de sintaxis, el proceso viejo no murio y el nuevo
arranco encima. El bloque del paso 1 resuelve el PID solo y no tiene ese
problema.

**Volver atras:** `git reset --hard <sha anterior>` y repetir los pasos 1 y 4.

---

## ngrok

El endpoint HTTP escucha en `127.0.0.1:8765`; quien lo publica es ngrok.

```bash
setsid nohup ngrok http 8765 --log=stdout > ~/ngrok_senti.log 2>&1 < /dev/null &
grep -E "starting web service|started tunnel" ~/ngrok_senti.log | tail -2
```

En el VPS **conviven varios agentes de ngrok** (otro proyecto en el puerto 5000
y uno con dominio estatico hacia nginx). Como el primero ocupa el `4040`, el de
Senti coge el `4041`; de ahi la clave `NGROK_API` del `.env`. El binario del
snap **no acepta `--web-addr`**, asi que ese puerto depende del orden de
arranque: para fijarlo hay que poner `web_addr` en el YAML del agente.

Si ngrok se reinicia, la URL cambia y **hay que reiniciar tambien el servicio**
para que la republique: solo lo intenta una vez, al arrancar.

---

## Claves del `.env` en produccion

| Clave | Valor | Para que |
|---|---|---|
| `API_ENABLED` | `true` | Enciende el endpoint HTTP |
| `API_AUTH` | `firebase` | ID token. **Nunca `abierto` detras de ngrok** |
| `NGROK_API` | `http://127.0.0.1:4041/api/tunnels` | El agente de Senti |
| `DEBUG` | `false` | Baja el log de DEBUG a INFO |
| `SUPPORT_EMAIL` | `pedro.nicolas@i-condor.com` | Confirmado el 28/09 |
| `SUPPORT_PHONE` | `+52 1 55 6815 5033` | WhatsApp de soporte, confirmado el 28/09 |
| `TELEGRAM_ADMIN_CHAT_ID` | **pendiente** | Recibe los eventos técnicos (watchdog, reinicios, modo configuración) y los avisos de nuevos contactos. Vacío = no le llegan a nadie. Se saca con `/id` en el bot |

> **Cuidado con las claves repetidas.** `config.py` usa `load_dotenv()` sin
> `override`, asi que ante una clave duplicada dentro del `.env` **gana la
> primera aparicion, no la ultima**. Añadir `DEBUG=false` al final no hace nada
> mientras arriba siga el `DEBUG=true` original: hay que editar la linea
> existente.

---

## Migracion de propiedad y horarios (aplicada el 28/09/2026)

`migrar_retro_banco.py` pone `ownerUid` a cada central, quita la MAC de las
listas de quien no es dueño y deja un horario por equipo en
`Horarios/{uid}/devices/{mac}`. **Ya se aplicó en producción**; solo haría falta
repetirla si se restaurara una copia anterior al 28/09.

```bash
python backup_firebase.py backup          # siempre antes
python migrar_retro_banco.py              # ensayo: solo informa
python migrar_retro_banco.py --aplicar    # escribe, en una sola actualizacion
```

Las centrales que están en varias cuentas y no se pueden decidir salen como
**conflicto** y se dejan sin dueño. El 28/09 fueron `20_E7_C8_AD_43`,
`AC_15_18_D5_2D` y `C8_2E_18_25_CA_6`: las reclama por BLE quien las tenga.

Va junto con las reglas de `APP/database.rules.json`: sin `ownerUid`, las reglas
dejarían a los dueños sin acceso a su propia central.

---

## Fragilidades conocidas

- **Nada levanta los procesos.** Ni el bot ni ngrok tienen supervisor: si se
  caen, o si se reinicia el VPS, no vuelven solos. La salida seria systemd de
  usuario, que necesita que el administrador habilite
  `loginctl enable-linger space-user2`.
- **La URL de ngrok se publica una sola vez**, al arrancar.
- **El tope de uso del endpoint vive en memoria**: correcto con un solo
  proceso, incorrecto si algun dia hay varias instancias.
- **El token del bot aparece en `alarm_service.log`** en cada linea de `httpx`,
  y tambien en los rotados. Antes de compartir un log, redactalo.
