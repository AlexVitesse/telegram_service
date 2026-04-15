# Disparo de Emergencia - Sentinel Guard

## Que es el disparo de emergencia

Es una funcion que permite detonar la alarma manualmente en cualquier momento, sin importar si el sistema esta armado o desarmado. Diseñada para situaciones de emergencia donde el usuario necesita activar la alarma inmediatamente.

## Disparo desde la App

En la pantalla principal de la app movil hay un boton "Activar Alarma". Al presionarlo, aparece una ventana de confirmacion para evitar activaciones accidentales por toques involuntarios. Una vez confirmado, el comando se envia al Master.

## Disparo desde Telegram

Usa el comando /disparo en el chat con el bot. Por seguridad, el bot solicita confirmacion antes de ejecutar la accion, mostrando dos botones: "Confirmar" y "Cancelar". Existe un cooldown de 8 segundos entre disparos para evitar activaciones repetidas.

## Respuesta del sistema al disparo

Al confirmar el disparo de emergencia:

- La sirena se activa inmediatamente a maxima potencia (110dB).
- La bengala actua segun su configuracion actual. Si esta en modo Auto, el cartucho de humo se dispara de forma instantanea e irreversible.
- Se envian notificaciones a todos los usuarios autorizados y a todos los grupos de Telegram vinculados al sistema.

## Precaucion con la bengala en modo Auto

Si la bengala esta configurada en modo Auto y se ejecuta un disparo de emergencia, el cartucho de humo se detona directa e instantaneamente. Una vez iniciada la secuencia, no se puede cancelar ni revertir. Asegurate de que el modo de la bengala es el adecuado antes de usar esta funcion.

## Lenguaje natural para disparo

El bot de Telegram entiende instrucciones en lenguaje natural para activar el disparo de emergencia. Ejemplos:

- "dispara la alarma"
- "activa la sirena"
- "emergencia"
- "detona la alarma"

## Como detener la alarma tras un disparo

Para detener la sirena y desactivar el sistema despues de un disparo de emergencia:

- Usa el comando /off en Telegram.
- Usa lenguaje natural: "apaga la alarma", "desactiva la sirena", "para la alarma".
- Cambia el toggle a "Desarmado" en la app movil.

La bengala, si fue detonada, no se puede detener. El humo se disipara por si solo en 3 a 10 minutos con ventilacion adecuada.
