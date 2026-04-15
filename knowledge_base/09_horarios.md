# Horarios y Programacion - Sentinel Guard

## Que es la programacion de horarios

El sistema de horarios permite programar el armado y desarmado automatico de la alarma por hora y dia de la semana. Asi el sistema se activa y desactiva solo, sin intervencion manual.

## Configurar horarios desde Telegram

Los siguientes comandos estan disponibles para gestionar horarios desde el bot de Telegram:

- **/horarios** - Ver el estado actual de la programacion (habilitada/deshabilitada, horas y dias configurados).
- **/horarios on** - Habilitar la programacion automatica.
- **/horarios off** - Deshabilitar la programacion (el sistema no se armara ni desarmara automaticamente).
- **/horarios activar HH:MM** - Configurar la hora de armado automatico en formato 24 horas (ejemplo: /horarios activar 22:00).
- **/horarios desactivar HH:MM** - Configurar la hora de desarmado automatico en formato 24 horas (ejemplo: /horarios desactivar 07:00).
- **/horarios dias** - Configurar los dias activos. Opciones: todos (lunes a domingo), semana (lunes a viernes), finde (sabado y domingo) o personalizado (seleccionar dias individuales).

## Configurar horarios desde la App

La pantalla "Alarma" en la app movil incluye presets rapidos y configuracion manual.

Presets rapidos disponibles:

- **Salida al Trabajo**: Arma a las 7:00, desarma a las 18:00, activo de lunes a viernes.
- **Hora de Dormir**: Arma a las 22:00, desarma a las 7:00, activo todos los dias.
- **Fin de Semana**: Arma a las 10:00, desarma a las 23:00, activo sabado y domingo.
- **Viaje/Vacaciones**: Arma a las 00:00, desarma a las 23:59, activo 24/7 los 7 dias.

La configuracion manual permite seleccionar libremente la hora de activacion, la hora de desactivacion y los dias de la semana (lunes a domingo, seleccionables individualmente).

## Lenguaje natural para horarios

El bot de Telegram entiende instrucciones en lenguaje natural para configurar horarios. Ejemplo: "arma lunes a viernes de 10pm a 6am".

## Sincronizacion de horarios

Los horarios se sincronizan automaticamente entre todas las plataformas del sistema:

App movil <-> Firebase <-> Servidor Python (VPS) <-> ESP32 (Master)

Cualquier cambio realizado desde la app o desde Telegram se propaga a todos los componentes.

## Ejecucion autonoma en el ESP32

El ESP32 puede ejecutar los horarios de forma autonoma, incluso si pierde conexion a internet. Utiliza NTP (protocolo de tiempo de red) para mantener la hora sincronizada. Esto garantiza que la alarma se arme y desarme en horario incluso durante cortes de internet.

## Notificacion previa

El sistema envia un aviso 5 minutos antes de ejecutar un armado o desarmado programado. Esto permite al usuario cancelar o modificar la accion si es necesario.

## Ejecucion unica por dia

Cada accion programada (armar o desarmar) se ejecuta una sola vez por dia. Si la hora ya paso cuando se habilita la programacion, no se ejecuta retroactivamente.

## Almacenamiento de horarios

La configuracion de horarios se almacena en el archivo schedule_config.json del servidor y en Firebase para sincronizacion con la app movil.
