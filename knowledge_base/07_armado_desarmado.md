# Armado y Desarmado - Sentinel Guard

## Armar desde la App

Para armar el sistema desde la app movil Sentinel Guard, utiliza el toggle en la pantalla principal. Cambia el estado de "Desarmado" a "Armado". El cambio se sincroniza en tiempo real con el Master via MQTT.

## Armar desde Telegram

Usa el comando /on en el chat con el bot de Telegram. Si tienes multiples dispositivos registrados, el bot mostrara un menu de seleccion para elegir cual armar. Tambien esta disponible la opcion "Armar TODOS" para activar todos los dispositivos simultaneamente. Puedes usar lenguaje natural como "activa la alarma", "arma la de bodega" o "enciende el sistema".

## Armar desde el Teclado fisico

Ingresa tu codigo de seguridad (4 a 6 digitos) seguido de la tecla #. El teclado envia la instruccion al Master via LoRa.

## Respuesta del sistema al armar

Cuando se arma el sistema ocurre la siguiente secuencia:

1. El Master emite un pitido de confirmacion y enciende el LED verde.
2. Inicia el tiempo de salida (1 minuto por defecto, configurable desde la app).
3. Durante el tiempo de salida, se escuchan pitidos intermitentes que se aceleran progresivamente.
4. Un pitido largo final indica que el armado esta completo y el sistema esta en vigilancia activa.

El tiempo de salida permite al usuario abandonar el area protegida sin activar la alarma.

## Comportamiento con el sistema armado

Cuando el sistema esta armado, el Master monitorea activamente todos los sensores registrados. Al detectar una intrusion:

- La sirena se activa inmediatamente (110dB).
- La bengala actua segun su configuracion actual: modo Auto (se dispara automaticamente), modo Pregunta (consulta al usuario via Telegram) o modo Deshabilitado (no se activa).
- Se envian notificaciones instantaneas a Telegram y a la App movil con detalles del sensor que detecto el evento.

## Desarmar desde la App

Cambia el toggle en la pantalla principal de "Armado" a "Desarmado". La accion se ejecuta en tiempo real.

## Desarmar desde Telegram

Usa el comando /off en el chat con el bot. Si tienes multiples dispositivos, aparecera un menu de seleccion. La opcion "Desarmar TODOS" desactiva todos los dispositivos a la vez. Tambien puedes usar lenguaje natural como "apaga el sistema", "desactiva la alarma" o "desarma todo".

## Desarmar desde el Teclado fisico

Ingresa tu codigo de seguridad seguido de la tecla #. El sistema reconoce automaticamente que debe desarmar si estaba armado.

## Respuesta del sistema al desarmar

Al desarmar el sistema:

- El Master emite un zumbido corto de confirmacion.
- El LED verde se apaga.
- El sistema deja de monitorear sensores (los ignora).
- Si la sirena estaba sonando, se desactiva inmediatamente.
- Si la bengala estaba en proceso de consulta, se cancela la secuencia.

## Lenguaje natural para armar y desarmar

El bot de Telegram entiende instrucciones en lenguaje natural. Ejemplos validos:

- "activa la alarma"
- "apaga el sistema"
- "arma la de bodega"
- "enciende la alarma de la casa"
- "desactiva todo"
- "desarma la del local"
