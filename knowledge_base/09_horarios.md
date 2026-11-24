# Horarios y Programacion - Sentinel Guard

## Que es la programacion de horarios

El sistema de horarios permite programar el armado y desarmado automatico de la alarma por hora y dia de la semana. Asi el sistema se activa y desactiva solo, sin intervencion manual.

## Un horario para cada equipo

Cada dispositivo tiene su propio horario, independiente del resto. Si tienes
varios equipos, puedes armar uno a las 22:00 y otro a las 7:00 sin que se
pisen entre si.

Al usar /horarios con varios dispositivos vinculados, el bot pregunta primero
sobre cual quieres actuar, o si prefieres aplicar el cambio a todos.

## Configurar horarios desde Telegram

Para configurar, programar, activar o desactivar los horarios automaticos desde el bot de Telegram, usa los siguientes comandos (reservados a administradores):

- **/horarios** - Ver el estado actual de la programacion (habilitada/deshabilitada, horas y dias configurados).
- **/horarios on** - Habilitar la programacion automatica.
- **/horarios off** - Deshabilitar la programacion (el sistema no se armara ni desarmara automaticamente).
- **/horarios activar HH:MM** - Configurar la hora de armado automatico en formato 24 horas (ejemplo: /horarios activar 22:00).
- **/horarios desactivar HH:MM** - Configurar la hora de desarmado automatico en formato 24 horas (ejemplo: /horarios desactivar 07:00).
- **/horarios cambiar** - Elegir otro dispositivo, si tienes varios.
- **/horarios dias** - Configurar los dias activos. Opciones: todos (lunes a domingo), semana (lunes a viernes), finde (sabado y domingo) o una lista de dias, por ejemplo /horarios dias L,M,X,J,V.

La hora de armado y la de desarmado no pueden ser la misma.

Si la central esta desconectada cuando cambias el horario desde Telegram (comandos /horarios o lenguaje natural, incluido /horarios off), el bot te avisa: "esta sin conexion: el horario se aplicara cuando la central se conecte". El cambio queda guardado en la nube y se le manda en cuanto vuelva a conectarse. Mientras tanto, la central sigue con su horario anterior.

## Configurar horarios desde la App

La pestaña "Horarios" de la app (titulo "Programar horario") permite crear, editar, pausar y eliminar horarios. Para crear uno:

1. Toca "Programar" (o "Agregar otro horario") y ponle un "Nombre", por ejemplo Trabajo, Noche o Playa.
2. Elige el tipo: "Cada semana" o "Vacaciones".
3. Si tienes varias centrales, elige una o "Todas mis centrales".
4. Cada semana: usa un atajo o elige tu hora "Se arma", tu hora "Se desarma" y los dias ("Entre semana", "Fin de semana", "Todos" o dia por dia). Si solo quieres que se arme, marca "Sin hora de regreso": la desarmas tu al volver.
5. Vacaciones: elige las fechas "Desde" y "Hasta" en el calendario y la hora a la que se arma el primer dia y se desarma el ultimo.
6. Toca "Guardar horario".

Atajos rapidos disponibles en "Cada semana" (solo rellenan el formulario; se guarda con "Guardar horario"):

- **Trabajo**: Arma a las 7:00, desarma a las 18:00, de lunes a viernes.
- **Noche**: Arma a las 22:00, desarma a las 7:00, todos los dias.
- **Fin de semana**: Arma a las 10:00, desarma a las 23:00, sabado y domingo.

Cada horario guardado aparece en la lista con su interruptor para pausarlo, "Editar" y "Eliminar". Una central actualizada admite hasta 4 horarios que no se enciman; una sin actualizar admite uno solo (el nuevo reemplaza al anterior) y no acepta "Vacaciones" ni "Sin hora de regreso".

Los horarios con nombre, varios por central, "Vacaciones" y "Sin hora de regreso" se crean en la app; desde Telegram se ajustan la hora de armado, la de desarmado y los dias.

## Lenguaje natural para horarios

El bot de Telegram entiende instrucciones en lenguaje natural para configurar horarios. Ejemplo: "arma lunes a viernes de 10pm a 6am". Despues comprueba con /horarios que quedo como querias.

## Sincronizacion de horarios

Los horarios se guardan en la nube de Sentinel Guard y en la propia central, y se ven igual en la app y en Telegram.

Un cambio solo tiene efecto en la central cuando esta en linea y lo recibe. Si esta desconectada, el Master sigue usando el horario que tenia guardado hasta que se conecte: los cambios hechos desde la app o desde Telegram quedan guardados en la nube, sin caducar, y se le mandan en cuanto vuelve. Al conectarse, la central recibe tambien el horario vigente.

## La central cumple el horario aunque no haya internet

La central guarda su horario y lo ejecuta por su cuenta, incluso si pierde la conexion a internet. Toma la hora de internet y la sigue contando sola, asi que se arma y desarma a su hora durante un corte de internet.

Limite: el Master no tiene reloj con pila. Si se reinicia o se va la luz y vuelve sin internet, no ejecuta los horarios hasta que recupera la conexion y vuelve a tomar la hora. Un armado programado tambien pasa por el tiempo de salida.

## Notificacion previa

El bot de Telegram envia un aviso "RECORDATORIO" por chat privado 5 minutos antes de ejecutar un armado o desarmado programado. Esto permite al usuario cancelar o modificar la accion si es necesario. Se puede silenciar con el interruptor "Armado y desarmado" de Perfil > Notificaciones.

## Ejecucion unica por dia

Cada accion programada (armar o desarmar) se ejecuta una sola vez por dia. Si la hora ya paso cuando se habilita la programacion, no se ejecuta retroactivamente.
