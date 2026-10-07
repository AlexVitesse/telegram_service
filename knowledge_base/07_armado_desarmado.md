# Armado y Desarmado - Sentinel Guard

## Armar desde la App

Como armo la alarma desde la app: toca "Proteger ahora" (o el atajo "Salir") en la pantalla Inicio: arma todas tus centrales. Para armar solo un equipo, abre su ficha y toca "Proteger equipo". Tambien puedes pedirselo a Senti por escrito ("arma la alarma") tocando el boton flotante del asistente. El estado pasa de "Desarmado" a "Armado" y el cambio se envia en tiempo real al Master via MQTT.

## Armar desde Telegram

Usa el comando /on en el chat con el bot de Telegram. Si tienes multiples dispositivos registrados, el bot mostrara un menu de seleccion para elegir cual armar. Tambien esta disponible la opcion "Armar TODOS" para activar todos los dispositivos simultaneamente. Puedes usar lenguaje natural como "activa la alarma", "arma la de bodega" o "enciende el sistema".

## Armar desde el Teclado fisico

Ingresa tu codigo de seguridad (4 a 6 digitos) seguido de la tecla #. El teclado envia la instruccion al Master via LoRa.

## Respuesta del sistema al armar

Cuando se arma el sistema ocurre la siguiente secuencia:

1. El Master pita para confirmar (3 pitidos si se armo desde la app o Telegram, 1 pitido si fue con el teclado) y enciende el LED de armado.
2. Inicia el tiempo de salida (60 segundos por defecto, configurable en la ficha del equipo).
3. Durante el tiempo de salida suena un pitido doble cada 5 segundos.
4. En los ultimos 10 segundos el zumbador suena de forma continua.
5. Al terminar, una serie de 10 pitidos cortos indica que el armado esta completo y el sistema esta en vigilancia activa.

El tiempo de salida permite al usuario abandonar el area protegida sin activar la alarma.

## Comportamiento con el sistema armado

Cuando el sistema esta armado, el Master monitorea activamente todos los sensores registrados. Al detectar una intrusion:

- La sirena se activa inmediatamente (110dB). No hay tiempo de entrada: si entras con el sistema armado, la alarma suena al instante, asi que desarma antes de abrir la puerta.
- La sirena sigue sonando hasta que desarmas o la detienes. En modo Pregunta, si nadie contesta en 3 minutos, la sirena se apaga sola y el sistema sigue armado.
- La bengala actua segun su configuracion actual: modo Auto (se dispara automaticamente), modo Pregunta (consulta al usuario via Telegram) o modo Deshabilitado (no se activa).
- Se envian notificaciones instantaneas a Telegram y a la App movil con detalles del sensor que detecto el evento.

## Desarmar desde la App

Toca "Desarmar" (o el atajo "En casa") en la pantalla Inicio para desarmar todas tus centrales, o "Desarmar equipo" en la ficha de un equipo. La accion se ejecuta en tiempo real. Tambien puedes pedirselo a Senti ("desarma la alarma"): en ese caso pregunta antes con dos botones y dice que equipo va a desarmar, y hasta que confirmas no manda nada.

## Desarmar desde Telegram

Usa el comando /off en el chat con el bot. Si tienes multiples dispositivos, aparecera un menu de seleccion. La opcion "Desarmar TODOS" desactiva todos los dispositivos a la vez. Tambien puedes usar lenguaje natural como "apaga el sistema", "desactiva la alarma" o "desarma todo".

## Desarmar desde el Teclado fisico

Ingresa tu codigo de seguridad seguido de la tecla #. El sistema reconoce automaticamente que debe desarmar si estaba armado.

## Respuesta del sistema al desarmar

Al desarmar el sistema:

- El Master emite 3 pitidos cortos de confirmacion (con el teclado suenan 2 pitidos mas).
- El LED de armado se apaga.
- El sistema deja de monitorear sensores (los ignora).
- Si la sirena estaba sonando, se desactiva inmediatamente.
- Si la bengala estaba en proceso de consulta, se cancela la secuencia.

## Lenguaje natural para armar y desarmar

Tanto el bot de Telegram como Senti -el asistente dentro de la app- entienden
instrucciones en lenguaje natural, y los dos arman y desarman de verdad. La
diferencia: Senti pregunta antes de desarmar, con dos botones y nombrando el
equipo; el bot desarma directo. Ejemplos validos en los dos:

- "activa la alarma"
- "apaga el sistema"
- "arma la de bodega"
- "enciende la alarma de la casa"
- "desactiva todo"
- "desarma la del local"
