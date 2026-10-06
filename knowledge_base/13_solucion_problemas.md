# Solucion de Problemas

## Dispositivo aparece offline

- Verificar que el Master esta encendido. Con WiFi conectado, su LED de estado queda encendido fijo; si parpadea rapido, esta intentando conectarse.
- Verificar la conexion WiFi del Master: debe estar ubicado cerca del router.
- El Master envia su estado cada 30 segundos. La app y el bot lo marcan "Sin conexion" si pasan 90 segundos sin noticias.
- Si se perdio la conexion WiFi, el Master intenta reconectar solo cada minuto.
- Si cambiaste el nombre o la contrasena de tu red WiFi, el Master no se reconecta: hay que emparejarlo otra vez desde la app con los datos nuevos.
- Como ultimo recurso: reiniciar el Master desconectando la alimentacion y reconectando despues de unos segundos.

## Bot de Telegram no responde

- Verificar que el telefono tiene conexion a internet.
- Intentar enviar el comando /start para reiniciar la sesion con el bot.
- Si el servicio en el VPS esta caido, contactar al administrador del sistema.
- Los comandos tienen un cooldown de 5 segundos entre cada uso (8 segundos para /disparo); si repites antes, el bot lo ignora. Esperar antes de reintentar.
- Los comandos no funcionan dentro de un grupo de Telegram: el grupo solo recibe avisos. Escribe al bot por chat privado.

## BLE no detecta el dispositivo

- Verificar que el Bluetooth del telefono esta activado.
- Asegurar que el Master esta en modo emparejamiento: presionar el clip durante 5 a 8 segundos hasta escuchar el pitido. El LED de estado debe quedar parpadeando.
- Acercar el telefono al Master. La distancia maxima de BLE es aproximadamente 10 metros.
- En la app el equipo aparece como "Sentinel Master". Si no aparece en la lista: reiniciar el proceso presionando nuevamente el clip.
- El modo emparejamiento tiene un timeout de 5 minutos; despues el Master se reinicia solo. Si se pasa el tiempo, hay que volver a activarlo.
- En iPhone, si la app dice "No se pudo leer el identificador de la central", el firmware del equipo es anterior a marzo de 2026: usa un telefono Android o actualiza el firmware.

## WiFi no conecta durante configuracion

- Verificar que la contrasena WiFi ingresada es correcta.
- El Master solo soporta redes WiFi de 2.4 GHz. No es compatible con redes de 5 GHz. Si tu red no aparece en la lista de la app, puede ser de 5 GHz.
- Si la app dice "La central no pudo conectarse a la red", revisa contrasena y banda; si estan bien, apaga y enciende la central y vuelve a emparejar.
- Si dice "La conexion tardo demasiado", puede que la central ya haya salido del modo emparejamiento: vuelve a poner el clip.
- Verificar que el router esta encendido y dentro del alcance del Master.
- Si persiste el problema, intentar con otra red WiFi disponible.

## Bengala LED rojo

- El cartucho de bengala no esta bien colocado en su soporte.
- Presionar el cartucho con fuerza firme hasta que el LED cambie a verde.
- Si sigue mostrando rojo: retirar el cartucho completamente y volver a colocarlo.
- Verificar que el cartucho no esta gastado o vacio.

## Alarma se activa sola (falsa alarma)

- **Sensor PIR**: Verificar que no hay objetos moviles en su campo de vision, como cortinas, ventiladores o mascotas.
- **Sensor magnetico**: Verificar la alineacion de ambas piezas del sensor. Puede haberse movido por vibraciones o uso.
- Instalar el sensor PIR a una altura media-alta para evitar detecciones de mascotas.
- Mantener el area del sensor despejada de objetos que puedan generar movimiento.

## No recibo notificaciones en la app

- Verificar que las notificaciones push estan habilitadas en Perfil > Notificaciones dentro de la app ("Notificaciones Push", "Armado y desarmado", "Conexion de la central").
- Para Telegram: revisar "Avisos por Telegram" en Perfil > Notificaciones y que tu Chat ID este entre los destinatarios en la ficha del equipo.
- Verificar los permisos de notificacion del telefono para la app Sentinel Guard.
- Verificar que las notificaciones del telefono no estan silenciadas o en modo No Molestar.

## Olvide la contrasena del teclado

- Usar el reset de fabrica: mantener presionado Menu (*) durante 3 segundos, luego presionar 2, ingresar el codigo maestro proporcionado por el proveedor y presionar #.
- La contrasena vuelve al valor por defecto: 1234.
- Si no tienes el codigo maestro, contactar directamente al proveedor del sistema.

## La alarma suena en cuanto entro a casa

- El sistema no tiene tiempo de entrada: si esta armado, la sirena suena en cuanto un sensor detecta la entrada.
- Desarma antes de entrar: desde la app ("Desarmar"), con /off en Telegram, o con el teclado si queda fuera del area vigilada.
- Si usas horarios, revisa en la pestaña Horarios que la hora de desarmado sea anterior a tu llegada.

## El equipo se arma solo

- Revisa los horarios: en la pestaña Horarios ("Alarmas Programadas") o con /horarios en Telegram. El Master guarda su propio horario y lo ejecuta aunque no haya internet.
- Para quitarlo, elimina el horario en la app o usa /horarios off.
