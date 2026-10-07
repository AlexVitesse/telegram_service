# Usuarios y Permisos

## Como se configuran o programan los permisos del sistema

Los permisos de usuario se configuran (o programan) desde Telegram. Configurar o programar un permiso significa dar acceso a un nuevo usuario para que pueda controlar los dispositivos. Los permisos se configuran y programan paso a paso con los comandos del bot y no requieren la app ni hardware adicional. Solo los administradores pueden configurar o programar permisos.

### Pasos para configurar un nuevo permiso

1. Paso 1: El administrador envia /adduser al bot de Telegram.
2. Paso 2: El bot genera un codigo de invitacion con el formato /join_DEVICE_ID.
3. Paso 3: El administrador comparte ese codigo con el nuevo usuario por un medio externo (WhatsApp, SMS, correo).
4. Paso 4: El nuevo usuario envia /join_DEVICE_ID al bot desde su Telegram.
5. Paso 5: El bot notifica al dueño del equipo con la solicitud del nuevo usuario. La solicitud expira en 5 minutos.
6. Paso 6: El administrador aprueba el permiso ejecutando /approve_CHATID.
7. Paso 7: El nuevo usuario queda registrado con permisos de acceso configurados.

Asi se configura un permiso nuevo en el sistema. Como se configuran los permisos: con los comandos /adduser, /approve_CHATID, /desvincular y /permisos desde Telegram. Para revisar quien recibe los avisos de cada equipo, mira la ficha del equipo en la app (Ajustes > Avisos de Telegram).

**Que si se hace desde la app.** El alta y la aprobacion de usuarios -invitar, aceptar, revocar- son solo de Telegram. Pero los DESTINATARIOS de cada equipo si se editan en la app, en la ficha del dispositivo: hasta tres por equipo, dos usuarios y un grupo de Telegram. Son los que reciben las notificaciones de ese equipo. Es una cosa distinta del alta de usuarios, aunque las dos hablen de "quien tiene acceso".

### Configurar permisos: resumen de comandos

- /adduser - configurar un nuevo permiso, agregar un nuevo usuario.
- /approve_CHATID - aprobar la configuracion del permiso del nuevo usuario.
- /desvincular quita tu propio acceso; /permisos en la version actual no muestra la lista de usuarios.

## Roles del sistema

Sentinel Guard maneja dos roles de usuario:

- **Administrador (Admin)**: Control total del sistema, incluyendo gestion de usuarios, configuracion de dispositivos, horarios y permisos. Puede armar, desarmar, ver estado y administrar todos los dispositivos.
- **Usuario**: Control basico de los dispositivos vinculados a su cuenta. Puede armar, desarmar, consultar estado y recibir notificaciones de alerta.

## Dueño del equipo - Administrador Principal

El dueño de un equipo es la cuenta que lo empareja en la app por Bluetooth. Su ID de Telegram queda como "Usuario 1 (Dueño)" en la ficha del equipo y es quien recibe y aprueba las solicitudes de acceso. Enviar /start al bot no da de alta a nadie como administrador: solo saluda y muestra tu Chat ID.

## Agregar nuevos usuarios

Solo un administrador puede agregar usuarios. El proceso es el siguiente:

1. El admin ejecuta el comando **/adduser** en el bot.
2. El bot genera un codigo de invitacion unico con formato: `/join_DEVICE_ID`.
3. El admin comparte ese codigo con el nuevo usuario por cualquier medio externo (WhatsApp, SMS, correo, en persona, etc.).
4. El nuevo usuario abre el bot de Telegram y envia el comando `/join_DEVICE_ID` que recibio.
5. El bot notifica al admin: "Nueva solicitud de acceso de [Nombre del usuario]".
6. El admin ejecuta **/approve_CHATID** (donde CHATID es el identificador del solicitante).
7. El usuario queda registrado con acceso a los dispositivos asignados y recibe "¡Acceso aprobado!". Ocupa un hueco libre de usuario del equipo (o el de grupo, si el ID es de un grupo).

Otra forma, sin invitacion: el dueño puede agregar el Chat ID de otra persona en la ficha del equipo en la app ("Editar" > "Agregar usuario o grupo" > "Usuario").

## Grupos de Telegram

Se puede agregar el bot a un grupo de Telegram para recibir notificaciones colectivas:

- El grupo **solo recibe notificaciones de alerta** (disparos, intrusiones, cambios de estado).
- Desde el grupo **no se pueden ejecutar comandos** de control.
- El ID del grupo se configura en la app: en "CHATID GRUPAL" al emparejar el equipo, o despues en la ficha del equipo con "Agregar usuario o grupo" > "Grupo". Para conocerlo, agrega el bot al grupo y escribe /id en el grupo.
- Esto es util para que varias personas esten informadas sin necesidad de vincular cada una individualmente.

## Multi-usuario

- Varios usuarios pueden controlar los mismos dispositivos simultaneamente.
- Cada usuario tiene su propio ChatID unico de Telegram.
- Cada equipo admite hasta tres destinatarios de Telegram: "Usuario 1 (Dueño)", "Usuario 2" y un grupo. Se editan desde la ficha del equipo en la app.
- Todos los usuarios vinculados reciben las notificaciones de alerta de los dispositivos que tienen asignados.

## Ver usuarios registrados

El comando **/permisos** (solo administradores) en la version actual responde que la lista de usuarios no esta disponible. Para ver quien recibe los avisos de un equipo, abre su ficha en la app: en Ajustes aparece "Avisos de Telegram" con el numero de destinatarios, y en "Editar" la lista completa.

## Desvincular dispositivo

El comando **/desvincular** quita tu Telegram de los destinatarios de un equipo:

- Requiere confirmacion ("Si, desvincular") antes de ejecutarse para evitar desvinculaciones accidentales.
- Una vez desvinculado, dejas de recibir notificaciones de ese equipo por Telegram y ya no puedes controlarlo desde Telegram.
- No borra el equipo de la app ni de la cuenta del dueño.
- Para volver a vincularte necesitas una nueva invitacion del administrador (/adduser), o que el dueño vuelva a poner tu Chat ID en la ficha del equipo.

Para borrar el equipo de tu cuenta de la app se usa "Borrar dispositivo" en la ficha del equipo (ver Preguntas Frecuentes).
