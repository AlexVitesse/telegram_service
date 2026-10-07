# Comandos del Bot de Telegram

## Comandos basicos

- **/start** - Inicia la interaccion con el bot. Si ya estas autorizado en algun equipo, recibes un saludo con el numero de dispositivos a los que tienes acceso y tu ID. Si todavia no, el bot te muestra tu Chat ID para copiarlo en la app y te explica que, para acceder a un equipo ajeno, el administrador debe usar /adduser. Si llegas desde el boton de la app, tu Telegram queda vinculado a tu cuenta automaticamente.
- **/id** - Muestra tu Chat ID de Telegram para copiarlo en la app (Perfil > Chat ID de Telegram, o en la ficha del equipo). Funciona aunque todavia no estes dado de alta en el sistema. Escrito dentro de un grupo, devuelve el ID del grupo.
- **/vincular** - Vincula tu Telegram con tu cuenta de la app. Normalmente lo hace solo el enlace de la app que abre el bot; el comando sirve de respaldo si ese enlace falla.
- **/help** - Muestra la guia de comandos disponibles segun tus permisos.
- **/info** - Presentacion del producto para quien todavia no tiene acceso.
- **/soporte** - Muestra los datos de contacto del soporte humano.

## Comandos de seguridad

- **/on** - Armar el sistema de alarma. Si solo tienes un dispositivo vinculado, se arma directamente. Si tienes multiples dispositivos, aparece un menu de seleccion con la opcion adicional "Armar TODOS". Cooldown de 5 segundos.
- **/off** - Desarmar el sistema de alarma. Funciona igual que /on: seleccion directa con un dispositivo o menu con multiples. Incluye opcion "Desarmar TODOS". Cooldown de 5 segundos.
- **/status** - Consulta el estado actual del dispositivo: en linea o sin respuesta, armado o desarmado, modo bengala e intensidad de senal WiFi (en dBm). El bot espera unos segundos la respuesta del dispositivo. Con varios equipos ofrece "Ver TODOS". Cooldown de 5 segundos.
- **/disparo** - Ejecuta un disparo manual de la sirena/alarma en todos tus equipos. Requiere confirmacion con los botones "Confirmar" y "Cancelar" para evitar activaciones accidentales. Cooldown de 8 segundos (mas alto que otros comandos por seguridad).
- **/sensors** - Muestra informacion tecnica detallada de cada equipo: sensores LoRa (senal y hace cuanto se vieron), senal WiFi, memoria libre, tiempo de actividad (uptime), estado de armado, modo de bengala, tiempo de salida y horario.

## Detener sirena sin desarmar

No existe un comando dedicado tipo /stop para detener la sirena. Sin embargo, se puede lograr de dos formas:
- **Desde Telegram con lenguaje natural**: Escribir "detener la sirena", "silencia la alarma" o "para el ruido". La IA lo interpreta como intent stop_alarm, que detiene la sirena pero mantiene el sistema armado.
- **Desde el boton "Dejar armado"**: Cuando se dispara la alarma y la bengala esta en modo Pregunta, el aviso de alarma trae el boton "Dejar armado", que detiene la sirena sin desarmar el sistema.

Esto es util cuando quieres silenciar la sirena pero mantener el sistema vigilando.

## Comandos de bengala

- **/bengala** - Abre el menu de configuracion de bengala con los botones "Modo Auto", "Modo Pregunta" y "Deshabilitar". Con varios equipos, primero eliges cual o "Configurar TODOS".
- **/auto** - Activa el modo automatico de bengala. La bengala se dispara automaticamente cuando se detecta una intrusion sin preguntar al usuario.
- **/preguntar** - Activa el modo con pregunta. Cuando se detecta una intrusion, el bot pregunta al usuario si desea disparar la bengala antes de hacerlo.
- **/deshabilitar** - Deshabilita la bengala: no se disparara cuando se active la alarma. Para habilitarla de nuevo usa /auto o /preguntar.

La pregunta del modo Pregunta se contesta con los botones del propio mensaje de alarma. No existen los comandos /si ni /no.

## Comandos de administracion

- **/permisos** - Solo para administradores. En la version actual el bot responde que la lista de usuarios no esta disponible; los destinatarios de cada equipo se ven en la ficha del equipo en la app.
- **/horarios** - Solo para administradores. Gestion de la programacion automatica de armado y desarmado: on, off, activar HH:MM, desactivar HH:MM y dias. Con varios equipos pregunta primero sobre cual actuar. Consulta la documentacion de horarios para el detalle.
- **/adduser** - Solo el dueño de la central (no el "Usuario 2" ni un grupo). Genera un codigo de invitacion con el formato /join_DEVICE_ID para compartir con un nuevo usuario. Si eres dueño de varias centrales, el bot te pregunta para cual.
- **/desvincular** - Quita tu Telegram de los destinatarios de un equipo ("Ya no podras controlarlo desde Telegram"). Requiere confirmacion con "Si, desvincular". No borra el equipo de la app. Para volver, pide al administrador un nuevo codigo de invitacion o que te agregue de nuevo en la ficha del equipo.
- **/reload_kb** - Solo para administradores. Recarga la base de conocimiento del asistente IA sin reiniciar el servicio.

## Comandos dinamicos

- **/join_XXXXX** - Comando que usa el nuevo usuario para solicitar acceso, en un chat privado con el bot (en grupos no funciona). XXXXX es el codigo generado por el dueño con /adduser; si el codigo no corresponde a ninguna central, el bot responde "Codigo no valido". La solicitud expira en 5 minutos.
- **/approve_XXXXX** - Comando que usa el dueño de la central para aprobar la solicitud de un nuevo usuario. El bot se lo manda ya escrito en el aviso de la solicitud (/approve_CHATID_CENTRAL). Solo lo puede aprobar el dueño de esa central.

## Teclado permanente

El bot muestra un teclado fijo en la parte inferior del chat con los comandos mas usados:

[/on] [/off] [/disparo] [/status] [/bengala]

Esto permite acceso rapido sin necesidad de escribir los comandos manualmente.

## Proteccion anti-spam

El sistema incluye varias medidas para evitar el uso abusivo:

- **Cooldown de comandos**: Espera de 5 segundos entre ejecuciones del mismo comando (8 segundos para /disparo por seguridad). Si repites el comando antes, se ignora.
- **Lock de ejecucion**: Impide que un comando se ejecute multiples veces simultaneamente.
- **Deduplicacion de mensajes**: Ignora mensajes duplicados recibidos en un intervalo de 15 segundos.
