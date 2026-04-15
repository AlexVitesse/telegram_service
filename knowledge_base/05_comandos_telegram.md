# Comandos del Bot de Telegram

## Comandos basicos

- **/start** - Inicia la interaccion con el bot. Si eres el primer usuario en escribir, quedas registrado como Administrador Principal. Si ya estas autorizado, recibiras un mensaje de bienvenida. Si no estas autorizado, el bot te indicara como solicitar acceso.
- **/help** - Muestra la guia de comandos disponibles segun tus permisos (admin o usuario regular).

## Comandos de seguridad

- **/on** - Armar el sistema de alarma. Si solo tienes un dispositivo vinculado, se arma directamente. Si tienes multiples dispositivos, aparece un menu de seleccion con la opcion adicional "Armar TODOS". Cooldown de 5 segundos.
- **/off** - Desarmar el sistema de alarma. Funciona igual que /on: seleccion directa con un dispositivo o menu con multiples. Incluye opcion "Desarmar TODOS". Cooldown de 5 segundos.
- **/status** - Consulta el estado actual del dispositivo: armado o desarmado, modo bengala activo, intensidad de senal WiFi (en dBm). El bot espera hasta 5 segundos la respuesta del dispositivo via MQTT. Cooldown de 5 segundos.
- **/disparo** - Ejecuta un disparo manual de la sirena/alarma. Requiere confirmacion antes de ejecutarse para evitar activaciones accidentales. Cooldown de 8 segundos (mas alto que otros comandos por seguridad).
- **/sensors** - Muestra informacion tecnica detallada del dispositivo: senal WiFi, memoria libre, tiempo de actividad (uptime) y estado de sensores LoRa.

## Detener sirena sin desarmar

No existe un comando dedicado tipo /stop para detener la sirena. Sin embargo, se puede lograr de dos formas:
- **Desde Telegram con lenguaje natural**: Escribir "detener la sirena", "silencia la alarma" o "para el ruido". La IA lo interpreta como intent stop_alarm, que detiene la sirena pero mantiene el sistema armado.
- **Desde el boton "Dejar Armado"**: Cuando se dispara la alarma y la bengala esta en modo pregunta, aparece un boton "Dejar Armado" que detiene la sirena sin desarmar el sistema.

Esto es util cuando quieres silenciar la sirena pero mantener el sistema vigilando.

## Comandos de bengala

- **/bengala** - Abre el menu de configuracion de bengala. Muestra el modo actual y las opciones disponibles para cambiar.
- **/auto** - Activa el modo automatico de bengala. La bengala se dispara automaticamente cuando se detecta una intrusion sin preguntar al usuario.
- **/preguntar** - Activa el modo con pregunta. Cuando se detecta una intrusion, el bot pregunta al usuario si desea disparar la bengala antes de hacerlo.
- **/si** - Confirma el disparo de la bengala cuando el bot pregunta (modo preguntar).
- **/no** - Cancela el disparo de la bengala cuando el bot pregunta (modo preguntar).

## Comandos de administracion

- **/permisos** - Solo para administradores. Lista todos los usuarios registrados con su nombre, ChatID, dispositivos vinculados y rol asignado.
- **/horarios** - Gestion de la programacion automatica de armado y desarmado. Permite configurar horarios por dia de la semana. Consulta la documentacion de horarios para el plan completo de configuracion.
- **/adduser** - Solo para administradores. Genera un codigo de invitacion unico con el formato /join_DEVICE_ID para compartir con un nuevo usuario.
- **/desvincular** - Permite desasociar un dispositivo de tu cuenta. Requiere confirmacion. Para volver a vincular necesitaras una nueva invitacion del administrador.
- **/reload_kb** - Solo para administradores. Recarga la base de conocimiento del asistente IA sin reiniciar el servicio.

## Comandos dinamicos

- **/join_XXXXX** - Comando que usa el nuevo usuario para solicitar acceso. XXXXX es el codigo generado por el admin con /adduser. El nuevo usuario envia este comando al bot para iniciar el proceso de vinculacion.
- **/approve_XXXXX** - Comando que usa el administrador para aprobar la solicitud de un nuevo usuario. XXXXX corresponde al ChatID del solicitante.

## Teclado permanente

El bot muestra un teclado fijo en la parte inferior del chat con los comandos mas usados:

[/on] [/off] [/disparo] [/status] [/bengala]

Esto permite acceso rapido sin necesidad de escribir los comandos manualmente.

## Proteccion anti-spam

El sistema incluye varias medidas para evitar el uso abusivo:

- **Cooldown de comandos**: Espera de 5 segundos entre ejecuciones del mismo comando (8 segundos para /disparo por seguridad).
- **Lock de ejecucion**: Impide que un comando se ejecute multiples veces simultaneamente.
- **Deduplicacion de mensajes**: Ignora mensajes duplicados recibidos en un intervalo de 15 segundos.
