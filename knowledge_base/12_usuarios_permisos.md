# Usuarios y Permisos

## Roles del sistema

Sentinel Guard maneja dos roles de usuario:

- **Administrador (Admin)**: Control total del sistema, incluyendo gestion de usuarios, configuracion de dispositivos, horarios y permisos. Puede armar, desarmar, ver estado y administrar todos los dispositivos.
- **Usuario**: Control basico de los dispositivos vinculados a su cuenta. Puede armar, desarmar, consultar estado y recibir notificaciones de alerta.

## Primer usuario - Administrador Principal

El primer usuario que envie el comando /start al bot queda registrado automaticamente como Administrador Principal. No se requiere ninguna configuracion adicional. Este usuario tiene control total y es quien gestiona el acceso de los demas.

## Agregar nuevos usuarios

Solo un administrador puede agregar usuarios. El proceso es el siguiente:

1. El admin ejecuta el comando **/adduser** en el bot.
2. El bot genera un codigo de invitacion unico con formato: `/join_DEVICE_ID`.
3. El admin comparte ese codigo con el nuevo usuario por cualquier medio externo (WhatsApp, SMS, correo, en persona, etc.).
4. El nuevo usuario abre el bot de Telegram y envia el comando `/join_DEVICE_ID` que recibio.
5. El bot notifica al admin: "Nueva solicitud de acceso de [Nombre del usuario]".
6. El admin ejecuta **/approve_CHATID** (donde CHATID es el identificador del solicitante).
7. El usuario queda registrado con acceso a los dispositivos asignados.

## Grupos de Telegram

Se puede agregar el bot a un grupo de Telegram para recibir notificaciones colectivas:

- El grupo **solo recibe notificaciones de alerta** (disparos, intrusiones, cambios de estado).
- Desde el grupo **no se pueden ejecutar comandos** de control.
- El GroupID se configura durante el setup inicial del sistema.
- Esto es util para que varias personas esten informadas sin necesidad de vincular cada una individualmente.

## Multi-usuario

- Varios usuarios pueden controlar los mismos dispositivos simultaneamente.
- Cada usuario tiene su propio ChatID unico de Telegram.
- Se pueden agregar IDs adicionales desde la aplicacion movil mediante el campo Telegram_ID_2.
- Todos los usuarios vinculados reciben las notificaciones de alerta de los dispositivos que tienen asignados.

## Ver usuarios registrados

El comando **/permisos** (solo disponible para administradores) lista todos los usuarios del sistema mostrando:

- Nombre del usuario
- ChatID de Telegram
- Dispositivos vinculados
- Rol asignado (Admin o Usuario)

## Desvincular dispositivo

El comando **/desvincular** permite desasociar un dispositivo de tu cuenta:

- Requiere confirmacion antes de ejecutarse para evitar desvinculaciones accidentales.
- Una vez desvinculado, dejas de recibir notificaciones y pierdes el control de ese dispositivo.
- Para volver a vincular el dispositivo necesitaras una nueva invitacion del administrador (/adduser).
