# Comandos del Bot de Telegram - Sentinel Guard

Documentacion completa de todos los comandos disponibles en el bot de Telegram.

---

## Comandos Basicos

### `/start`
Inicia la interaccion con el bot. Es tambien la puerta de la vinculacion desde
la app movil.

- **Permisos:** Ninguno (publico)
- **Descripcion**, en el orden en que se comprueba:
  1. **Con payload de la app** (`/start <uid>`, que genera el boton "Abrir el
     bot"): escribe `Usuarios/{uid}/telegram_id` y contesta "Listo, ya estas
     vinculado". Repetirlo contesta "Ya estabas vinculado" y no escribe nada.
  2. Si ya esta autorizado, mensaje de bienvenida con su Chat ID
  3. Si es el primer usuario del sistema, se registra como Administrador
     Principal
  4. Si no, le da su Chat ID y le explica las dos salidas: copiarlo en la app,
     o pedir un codigo de invitacion si espera acceso a un equipo ajeno

**Lo que NO hace la vinculacion, y es deliberado:**

- **No pisa un `telegram_id` que ya exista.** `Horarios` se indexa por el;
  cambiarlo en silencio desde un `/start` dejaria los horarios del usuario
  apuntando a una clave que ya no es la suya. Contesta avisando y no toca nada.
- **No crea cuentas.** El payload viene de un enlace que cualquiera puede
  teclear: si el uid no tiene cuenta, se registra un warning y sigue el camino
  normal.

El payload viejo era la palabra `app`, que no identificaba a nadie, asi que la
"vinculacion automatica" solo reconocia a quien YA tenia equipos. Al recien
registrado -el unico que la necesita- le contestaba "Usuario no registrado".
Se sigue aceptando `app` como payload, sin efecto, porque hay enlaces repartidos.

Cubierto por `test_vinculacion_app.py`.

---

### `/vincular <id>`
Vincula tu Telegram con una cuenta de la app, escribiendo el identificador.

- **Permisos:** Ninguno (publico), igual que `/id` y por lo mismo
- **Descripcion:** hace lo mismo que `/start <uid>`, que es lo que manda el boton
  "Abrir el bot" de la app sin que el usuario vea el identificador. Existe porque
  un enlace profundo se rompe por el camino mas de lo que parece -un navegador
  que no cede el control a Telegram, un pegado a medias-, y sin esto la unica
  salida era escribir el Chat ID a mano en la app.
- Sin argumento, recuerda como se usa y da el Chat ID.

---

### `/id`
Devuelve tu Chat ID de Telegram.

- **Permisos:** Ninguno (publico)
- **Descripcion:**
  - Responde con el Chat ID del usuario para copiarlo en la app
    (Configuracion -> Chat ID de Telegram)
  - Sin autorizacion a proposito: quien todavia NO esta dado de alta es
    justo el que necesita saber su ID. No expone nada, Telegram ya le da
    su propio chat_id a quien pregunta

---

### `/help`
Muestra la guia de comandos disponibles.

- **Permisos:** Usuario autorizado
- **Descripcion:** Lista todos los comandos segun el nivel de permisos del usuario

---

## Comandos de Seguridad

### `/status`
Consulta el estado actual del sistema.

- **Permisos:** Usuario autorizado
- **Cooldown:** 5 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: consulta directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Espera 5 segundos por respuesta del dispositivo
- **Respuesta incluye:**
  - Estado del sistema (ARMADO/DESARMADO)
  - Estado de bengala (HABILITADA/DESHABILITADA)
  - Intensidad de senal WiFi (dBm)

---

### `/on`
Arma el sistema de alarma.

- **Permisos:** Usuario autorizado
- **Cooldown:** 5 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: arma directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Opcion "Armar TODOS" disponible para multiples dispositivos
  - Espera confirmacion del dispositivo (5 segundos)

---

### `/off`
Desarma el sistema de alarma.

- **Permisos:** Usuario autorizado
- **Cooldown:** 5 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: desarma directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Opcion "Desarmar TODOS" disponible para multiples dispositivos
  - Espera confirmacion del dispositivo (5 segundos)

---

### `/disparo`
Activa la alarma manualmente (disparo de sirena).

- **Permisos:** Usuario autorizado
- **Cooldown:** 8 segundos
- **Descripcion:**
  - Muestra confirmacion antes de ejecutar
  - Botones: "Confirmar" / "Cancelar"
  - Activa la sirena en todos los dispositivos autorizados

---

## Comandos de Bengala

### `/bengala`
Menu de configuracion del sistema de bengala.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Muestra el modo actual de bengala
  - Opciones disponibles:
    - **Modo Auto:** Dispara bengala automaticamente con la alarma
    - **Modo Pregunta:** Pregunta antes de disparar
    - **Deshabilitar:** No dispara bengala

---

### `/auto`
Configura la bengala en modo automatico.

- **Permisos:** Usuario autorizado
- **Descripcion:** La bengala se dispara automaticamente cuando se activa la alarma, sin preguntar

---

### `/preguntar`
Configura la bengala en modo con pregunta.

- **Permisos:** Usuario autorizado
- **Descripcion:** Cuando se activa la alarma, el bot pregunta si deseas disparar la bengala

---

### Confirmar o cancelar el disparo de bengala

**No hay comandos `/si` ni `/no`.** Este documento los describia y no existen:
no estan entre los `CommandHandler` del bot y nunca lo estuvieron.

La solicitud se responde tocando los BOTONES del propio mensaje que manda el
bot (`InlineKeyboardButton` con `callback_data`). No hay que escribir nada.

Importa mas de lo que parece: esa instruccion se daba mientras suena una
sirena, que es el peor momento para pedirle a alguien que teclee un comando que
no va a funcionar. La misma equivocacion estaba en la base de conocimiento, de
donde salen las respuestas del asistente, y se corrigio ahi tambien.

---

## Comandos de Dispositivos

### `/desvincular`
Desvincula un dispositivo de tu cuenta.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Si tiene 1 dispositivo: muestra confirmacion directa
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Requiere confirmacion antes de desvincular
  - Despues de desvincular, necesitas nueva invitacion para volver a vincular

---

## Comandos de Administracion

> Estos comandos van detras de `@require_admin`: `/permisos`, `/horarios` y
> `/adduser`.
>
> **Ojo con lo que eso significa hoy.** `require_admin` consulta
> `is_user_admin()`, que en `firebase_manager.py:957` es un stub: devuelve
> cierto cuando el usuario tiene algun dispositivo autorizado, y su propio
> comentario lo dice.
>
> O sea que **cualquier usuario autorizado es administrador**: quien puede armar
> un equipo tambien puede dar de alta y aprobar a otra persona. Los dos roles
> que describe la documentacion no existen todavia en el codigo. El filtro esta
> puesto y funcionara el dia que se implementen; hasta entonces, no separa nada.

### `/permisos`
Muestra la lista de usuarios registrados.

- **Permisos:** Administrador
- **Descripcion:** Lista todos los usuarios con sus:
  - Nombre
  - Chat ID
  - Dispositivos asignados
  - Rol (admin/usuario)

---

### `/horarios`
Configura la programacion automatica del sistema.

- **Permisos:** Administrador
- **Uso:**
  ```
  /horarios              - Ver estado actual
  /horarios on           - Habilitar programacion
  /horarios off          - Deshabilitar programacion
  /horarios activar HH:MM    - Configurar hora de armado
  /horarios desactivar HH:MM - Configurar hora de desarmado
  ```
- **Ejemplos:**
  ```
  /horarios activar 22:00    - Armar a las 10:00 PM
  /horarios desactivar 06:30 - Desarmar a las 6:30 AM
  ```
- **Notas:**
  - Formato de hora: 24 horas (HH:MM)
  - Los cambios se sincronizan con el ESP32 y Firebase

---

### `/sensors`
Consulta informacion de los sensores.

- **Permisos:** Usuario autorizado
- **Descripcion:** Solicita al dispositivo la lista de sensores configurados

---

### `/adduser`
Genera un codigo de invitacion para agregar nuevos usuarios.

- **Permisos:** Administrador
- **Descripcion:**
  - Genera un codigo unico: `/join_DEVICE_ID`
  - El nuevo usuario debe enviar este codigo al bot
  - El administrador recibe notificacion para aprobar

---

## Comandos Dinamicos

### `/join_XXXXX`
Solicita acceso al sistema (usado por nuevos usuarios).

- **Permisos:** Ninguno (publico)
- **Descripcion:**
  - El usuario envia el codigo recibido del administrador
  - Se crea una solicitud pendiente
  - El administrador recibe notificacion con `/approve_CHATID`

---

### `/approve_XXXXX`
Aprueba la solicitud de un nuevo usuario.

- **Permisos:** Administrador
- **Descripcion:**
  - Aprueba al usuario con el Chat ID especificado
  - El usuario recibe notificacion de acceso aprobado
  - Se le asignan los dispositivos correspondientes

---

## Flujo de Invitacion de Usuarios

```
1. Admin ejecuta: /adduser
   Bot responde: "Envia este codigo: /join_ALARMA_MERIDA"

2. Admin envia el codigo al nuevo usuario (WhatsApp, SMS, etc.)

3. Nuevo usuario envia al bot: /join_ALARMA_MERIDA
   Bot responde: "Solicitud enviada al administrador"

4. Admin recibe: "Nueva solicitud de acceso de [Nombre]"
   Con instruccion: /approve_123456789

5. Admin ejecuta: /approve_123456789
   - Usuario queda registrado
   - Usuario recibe: "Acceso aprobado!"
```

---

## Callbacks de Botones Inline

El bot utiliza botones interactivos en varios comandos:

| Callback | Descripcion |
|----------|-------------|
| `trigger_confirm` | Confirma disparo manual de alarma |
| `trigger_cancel` | Cancela disparo manual |
| `bengala_confirm` | Confirma disparo de bengala |
| `bengala_cancel` | Cancela disparo de bengala |
| `bengala_on` | Activa bengala |
| `bengala_off` | Desactiva bengala |
| `bengala_mode_auto` | Cambia a modo automatico |
| `bengala_mode_ask` | Cambia a modo pregunta |
| `arm_DEVICEID` | Arma dispositivo especifico |
| `arm_all` | Arma todos los dispositivos |
| `disarm_DEVICEID` | Desarma dispositivo especifico |
| `disarm_all` | Desarma todos los dispositivos |
| `status_DEVICEID` | Estado de dispositivo especifico |
| `status_all` | Estado de todos los dispositivos |
| `unlink_DEVICEID` | Confirma desvinculacion |
| `unlink_cancel` | Cancela desvinculacion |

---

## Teclado Estandar

El bot muestra un teclado permanente con los comandos mas usados:

```
[ /on  ] [ /off     ]
[    /disparo       ]
[    /status        ]
[    /bengala       ]
```

---

## Sistema Anti-Spam

- **Cooldown de comandos:** Evita ejecucion repetida del mismo comando
- **Lock de ejecucion:** Previene ejecuciones concurrentes
- **Deduplicacion de mensajes:** No envia mensajes identicos en 15 segundos

---

## Que avisos manda el bot, y cuales se pueden apagar

El usuario elige desde la app. Hay DOS ejes y no son lo mismo:

| Eje | Campo | Decide |
|---|---|---|
| Categoria | `alertas/armado`, `alertas/conexion` | De QUE avisar |
| Canal | `alertas/telegram` | DONDE avisar |

Por categoria, `armado` cubre `system_armed` y `system_disarmed`, y `conexion`
los avisos de dispositivo sin conexion y reconectado. **Las alarmas no estan y no
se pueden quitar de ahi.**

El eje de canal SI las alcanza: con `alertas/telegram` en false el bot no manda
NADA a ese chat, alarmas incluidas. Quien lo apaga esta diciendo "por Telegram
no", no "de esto no". La app pide confirmacion antes de guardarlo si el usuario
tiene tambien el push apagado, porque entonces se queda sin ninguna via.

Las preferencias son POR CHAT: apagar el tuyo no calla al grupo ni al segundo
usuario de la central.

Todo vive en `Usuarios/{uid}/alertas`, el mismo sitio que lee el push. Aqui solo
se tiene el chat_id, asi que `_uid_por_chat_id()` lo resuelve con
`Usuarios.order_by_child("telegram_id")`, cacheado 5 minutos. **Hace falta la
regla `.indexOn: ["telegram_id"]`**: sin ella Firebase avisa por log y filtra en
cliente, o sea que se descarga el arbol de usuarios entero en cada evento.

El filtro se aplica en `_get_authorized_chats()` (main.py) y en
`_chats_que_quieren()` (telegram_bot.py), que son los dos sitios por los que pasa
todo lo que se manda. En el flujo de alarma se filtra UNA vez, al crear la
confirmacion, porque de esa lista salen tambien los recordatorios cada 30 s:
filtrar solo el primer mensaje dejaba a quien apago el canal recibiendo los
recordatorios.

Ausente = se recibe todo. Y un chat sin cuenta en la app -un grupo, o alguien que
solo usa Telegram- no tiene preferencias que respetar, asi que recibe todo
tambien: callarse ante la duda es lo que no puede hacer una alarma.

Cubierto por `test_avisos_opcionales.py`.

---

## Notas Tecnicas

- Los comandos que esperan respuesta del dispositivo tienen timeout de 5-7 segundos
- El cooldown es de **5 segundos** en `/status`, `/on` y `/off`, y de **8** en `/disparo`
- Los cambios en horarios se sincronizan automaticamente con Firebase y ESP32
- Las confirmaciones de bengala expiran en 2 minutos
- Los recordatorios de bengala se envian cada 30 segundos mientras la alarma esta activa
