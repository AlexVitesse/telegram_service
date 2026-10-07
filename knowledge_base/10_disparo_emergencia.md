# Disparo de Emergencia - Sentinel Guard

## Que es el disparo de emergencia

Es una funcion que permite detonar la alarma manualmente en cualquier momento, sin importar si el sistema esta armado o desarmado. Diseñada para situaciones de emergencia donde el usuario necesita activar la alarma inmediatamente.

## Disparo desde la App

En la pantalla Inicio de la app movil hay un boton rojo "Emergencia" (SOS), "Solicitar ayuda inmediata". Al presionarlo aparece la confirmacion "¿Activar la alarma?" con los botones "No" y "Si", para evitar activaciones accidentales. Una vez confirmado, la sirena suena en todos tus equipos ("Alarma activada en todos los dispositivos").

## Disparo desde Telegram

Usa el comando /disparo en el chat con el bot. Por seguridad, el bot solicita confirmacion antes de ejecutar la accion ("¿Activar alarma manualmente?"), mostrando dos botones: "Confirmar" y "Cancelar". Al confirmar, se activa en todos tus equipos y el bot informa cuales respondieron. Existe un cooldown de 8 segundos entre disparos para evitar activaciones repetidas.

## Respuesta del sistema al disparo

Al confirmar el disparo de emergencia:

- La sirena se activa inmediatamente a maxima potencia (110dB).
- Si la bengala esta habilitada (modo Auto o Pregunta), el Master la detona de inmediato, sin preguntar. Solo con la bengala "Apagada" (deshabilitada) no se dispara.
- Se envian notificaciones a todos los usuarios autorizados y a todos los grupos de Telegram vinculados al sistema.

## Precaucion con la bengala en el disparo de emergencia

Si la bengala esta habilitada y se ejecuta un disparo de emergencia, el cartucho de humo se detona directa e instantaneamente, tambien en modo Pregunta. Una vez iniciada la secuencia, no se puede cancelar ni revertir. Si no quieres humo, pon la bengala en "Apagada" antes de usar esta funcion.

## Lenguaje natural para disparo

El disparo de emergencia no se puede pedir en lenguaje natural, ni al bot ni a Senti. Usa siempre el comando /disparo o el boton Emergencia de la app.

## Como detener la alarma tras un disparo

Para detener la sirena y desactivar el sistema despues de un disparo de emergencia:

- Usa el comando /off en Telegram, o escribe "apaga la alarma".
- En la app, toca de nuevo el boton Emergencia ("Toca para desactivar"): desactiva la alarma y desarma el sistema. Tambien sirve "Desarmar".
- Para solo silenciar la sirena y seguir armado, escribe al bot "silencia la alarma".

La bengala, si fue detonada, no se puede detener. Para despejar el humo, ventila abriendo puertas y ventanas; los datos del cartucho estan en su ficha tecnica.
