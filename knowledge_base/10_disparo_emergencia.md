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
- Bengala en modo "Auto": el Master la detona de inmediato.
- Bengala en modo "Pregunta": los equipos con el firmware de octubre de 2026 o posterior NO la detonan. Suena la sirena y Telegram te pregunta, igual que ante una intrusion ("Disparar bengala", "Dejar armado", "Desactivar sistema"). Los equipos con un firmware anterior la detonan de inmediato, sin preguntar. Si no sabes cual tiene tu equipo, cuenta con que puede detonarla.
- Bengala "Apagada" (deshabilitada): no se dispara nunca.
- Se envian notificaciones a todos los usuarios autorizados y a todos los grupos de Telegram vinculados al sistema.

## Precaucion con la bengala en el disparo de emergencia

En modo Auto, un disparo de emergencia detona el cartucho de humo directa e instantaneamente. En modo Pregunta tambien puede detonarlo si el equipo no tiene el firmware de octubre de 2026; por eso el aviso de la app dice que "puede dispararse de inmediato". Una vez iniciada la secuencia, no se puede cancelar ni revertir. Si no quieres humo, pon la bengala en "Apagada" antes de usar esta funcion.

## Lenguaje natural para disparo

El disparo de emergencia no se puede pedir en lenguaje natural, ni al bot ni a Senti. Usa siempre el comando /disparo o el boton Emergencia de la app.

## Como detener la alarma tras un disparo

Para detener la sirena y desactivar el sistema despues de un disparo de emergencia:

- Usa el comando /off en Telegram, o escribe "apaga la alarma".
- En la app, toca de nuevo el boton Emergencia ("Toca para desactivar"): desactiva la alarma y desarma el sistema. Tambien sirve "Desarmar".
- Para solo silenciar la sirena y seguir armado, escribe al bot "silencia la alarma".

La bengala, si fue detonada, no se puede detener. Para despejar el humo, ventila abriendo puertas y ventanas; los datos del cartucho estan en su ficha tecnica.
