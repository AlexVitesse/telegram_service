# Usuarios y Permisos

Hay dos formas de darle acceso a otra persona, y son cosas distintas:

- **Desde la app: compartir la central con tu familia** (desde la version 8.2). La otra persona usa su propia cuenta de la app y puede armar, desarmar y pedir panico. Ver "Compartir la central con tu familia desde la app".
- **Desde Telegram: permisos del bot** (/adduser y /approve). La otra persona controla y recibe avisos por Telegram. Ver "Como se configuran o programan los permisos del sistema".

## Compartir la central con tu familia desde la app

Desde la version 8.2 de la app, el dueño de una central puede compartirla con otras cuentas de la app (familia). Cada persona entra con su propia cuenta; no se comparte la contraseña.

### Invitar a alguien (solo el dueño)

1. Abre la ficha de la central ("Ver detalles y ajustes") y baja a **"Personas con acceso"**.
2. Si la persona esta contigo: toca **"Invitar"**. Aparece un **codigo QR** y el mismo codigo en texto (por ejemplo ABCD-EFGH). Vence a los **15 minutos** y sirve una sola vez. "Generar otro" anula el anterior.
3. Si la persona no esta contigo: toca **"Invitar por WhatsApp (codigo de 24 h)"**. Se abre WhatsApp con el mensaje ya escrito y el codigo, que vence a las **24 horas** y sirve una sola vez.
4. La otra persona instala la app, entra con su cuenta y en Inicio toca **"Tengo un codigo"** (junto a "Agregar"): puede **escanear el QR** o escribir el codigo.
5. Al dueño le llega un aviso: "[Nombre] se unio a [central]".

Cada central admite hasta **10 personas** ademas del dueño. Solo el dueño ve la lista de personas con acceso.

### Que puede hacer un miembro de la familia

- **Si puede:** ver el estado de la central, armar, desarmar, usar el boton de panico (SOS) y recibir las notificaciones push. Ve los horarios del dueño, pero **solo para leerlos**.
- **No puede:** editar la central (nombre, tiempos, bengala, WiFi), autorizar, borrar ni renombrar sensores, cambiar los destinatarios de Telegram ni invitar o quitar a otras personas. Sin internet (cuando la app habla directo con la central en la red de la casa) un miembro puede armar, desarmar y usar el panico si la central y la app estan actualizadas; con una central sin actualizar necesita internet para armar o desarmar. Lo demas, sin internet, solo lo hace el dueño.
- **Cada vez que un miembro arma, desarma o pide panico, al dueño le llega un aviso con su nombre.** Ese aviso no se puede apagar.

### Quitar a alguien (solo el dueño)

- **El dueño quita a alguien:** en "Personas con acceso", toca **"Quitar"** junto a su nombre. Esa persona deja de ver la central al momento y le llega el aviso "Ya no tienes acceso". Si esa persona era el "Usuario 2" de Telegram de la central, tambien se le quita de ahi.
- **Si la central cambia de dueño** (alguien la resetea y la da de alta con su cuenta) o el dueño la borra, todos los miembros pierden el acceso y los codigos pendientes dejan de valer.

### Como salgo o dejo de tener acceso a una central compartida (soy miembro de la familia)

Si eres miembro de la familia y quieres salir de una central que te compartieron, o dejar de tener acceso (por
ejemplo: "ya no quiero estar en la alarma de mi mamá", "me quiero salir de la casa de mis papás", "quitarme de la
alarma de un familiar"):
1. Abre la ficha de esa central ("Ver detalles y ajustes").
2. Baja hasta el final de la ficha y toca el boton **"Salir de esta central"**.
3. La app pregunta "¿Salir de esta central?": dejaras de verla y de recibir sus avisos. Toca **"Salir"**.

Como miembro no ves la seccion "Personas con acceso" (es solo del dueño): el boton de salir esta al final de la
ficha. Al dueño no le llega ningun aviso; simplemente dejas de aparecer en su lista. La central sigue igual para el
dueño y los demas. Para volver, el dueño tiene que invitarte otra vez.

Como miembro no puedes usar "Editar" en esa central. Si ademas el dueño te puso como destinatario de Telegram de
esa central y ya no quieres esos avisos, pidele que te quite en "Editar"; salir de la central en la app no cambia
Telegram si no eras su "Usuario 2".

### Cuanto dura el codigo de invitacion

El codigo de invitacion de la familia dura, vence o caduca asi: el **QR de "Invitar" dura 15 minutos** y el
**codigo de "Invitar por WhatsApp" dura 24 horas**. Los dos sirven una sola vez: cuando alguien lo usa, ya no vale.
Si se vencio, el dueño genera otro.

### Un familiar puede cambiar, crear o borrar horarios?

No. Un miembro de la familia ve los horarios del dueño en la app, pero **solo para leerlos**: no puede crearlos,
cambiarlos ni borrarlos. Los horarios los cambia unicamente el dueño de la central, desde la app (seccion Horarios)
o con /horarios en Telegram.

### Me mandaron un codigo: como me uno?

Depende de como es el codigo:
- **Codigo de la app**, de 8 letras y numeros como ABCD-EFGH (o un QR): es una invitacion de la familia. Abre la
  app Sentinel Guard, entra con tu cuenta y en Inicio toca **"Tengo un codigo"**; escanea el QR o escribe el codigo.
- **Comando que empieza por /join_**: es un permiso del bot de Telegram, no de la app. Envialo tal cual al bot
  @esp32_space_bot en un chat privado y espera a que el dueño lo apruebe.

### Soy familiar en la app: puedo usar el bot de Telegram?

Si. Vincula tu Telegram con tu cuenta: en la app entra en Perfil > Editar Informacion > "Chat ID de Telegram" y toca "Abrir el bot"; en Telegram pulsa "Iniciar". Desde ese momento, en el chat privado con el bot puedes hacer lo mismo que en la app como familiar:
- Armar (/on), desarmar (/off) y ver el estado (/status), o escribirlo con tus palabras: "arma la alarma", "como esta la casa".
- Activar la sirena con /disparo (pide confirmar).

Lo demas es solo del dueño: horarios, sensores, bengala, modo, invitar y aprobar personas. Si lo pides, el bot te contesta que eso solo lo puede hacer el dueño de la central.

Cada vez que armas, desarmas o activas la sirena por Telegram, al dueño le llega un aviso con tu nombre, igual que desde la app. Si el dueño te quita de "Personas con acceso" o tu sales de la central, el bot deja de obedecerte al momento.

Los avisos de la central (alarma, armado, conexion) te siguen llegando en la app; por Telegram no.

### Familia de la app y destinatarios de Telegram son cosas distintas

Ser familiar no te pone entre los destinatarios de Telegram de la central, y estar en Telegram no te pone en la familia de la app. Los destinatarios de Telegram (dos usuarios y un grupo) son los que reciben los avisos por Telegram y se siguen editando en la ficha del equipo, en "Editar".

## Como se configuran o programan los permisos del sistema

Los permisos de usuario del bot se configuran (o programan) desde Telegram. Configurar o programar un permiso significa dar acceso a un nuevo usuario para que pueda controlar los dispositivos por Telegram. Los permisos del bot se configuran y programan paso a paso con los comandos del bot. Solo los administradores pueden configurar o programar permisos. Para compartir la central con otra cuenta de la app, ver "Compartir la central con tu familia desde la app".

### Pasos para configurar un nuevo permiso

1. Paso 1: El dueño de la central envia /adduser al bot de Telegram, en chat privado.
2. Paso 2: El bot genera un codigo de invitacion: un comando que empieza por /join_ seguido de un codigo.
3. Paso 3: El administrador comparte ese codigo con el nuevo usuario por un medio externo (WhatsApp, SMS, correo).
4. Paso 4: El nuevo usuario envia ese comando /join_... al bot desde un chat privado (no desde un grupo).
5. Paso 5: El bot notifica al dueño del equipo con la solicitud del nuevo usuario. La solicitud expira en 5 minutos.
6. Paso 6: El dueño aprueba el permiso tocando el comando /approve_... que le llega ya escrito en el aviso. Solo el dueño de esa central puede aprobarlo.
7. Paso 7: El nuevo usuario queda registrado con permisos de acceso configurados.

Asi se configura un permiso nuevo en el sistema. Como se configuran los permisos: con los comandos /adduser, /approve_..., /desvincular y /permisos desde Telegram. Para revisar quien recibe los avisos de cada equipo, mira la ficha del equipo en la app (Ajustes > Avisos de Telegram).

**Que si se hace desde la app.** El alta y la aprobacion de usuarios del bot -/adduser, /approve, /desvincular- son de Telegram. En la app se hacen dos cosas: compartir la central con otras cuentas de la app (familia, desde la version 8.2, en "Personas con acceso") y editar los DESTINATARIOS de Telegram de cada equipo, en la ficha del dispositivo: hasta tres por equipo, dos usuarios y un grupo de Telegram. Son los que reciben las notificaciones de ese equipo por Telegram.

### Configurar permisos: resumen de comandos

- /adduser - configurar un nuevo permiso, agregar un nuevo usuario.
- /approve_... - aprobar el permiso del nuevo usuario (el bot te lo da ya escrito).
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
2. El bot genera un codigo de invitacion unico: un comando que empieza por `/join_`.
3. El admin comparte ese codigo con el nuevo usuario por cualquier medio externo (WhatsApp, SMS, correo, en persona, etc.).
4. El nuevo usuario abre el bot de Telegram y envia el comando `/join_...` que recibio.
5. El bot notifica al admin: "Nueva solicitud de acceso de [Nombre del usuario]".
6. El admin toca el comando **/approve_...** que le llega en el aviso.
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
