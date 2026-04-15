# Solucion de Problemas

## Dispositivo aparece offline

- Verificar que el Master esta encendido y tiene la luz indicadora activa.
- Verificar la conexion WiFi del Master: debe estar ubicado cerca del router.
- El sistema verifica la conexion cada 90 segundos automaticamente.
- Si se perdio la conexion WiFi, el Master intentara reconectar de forma automatica.
- Como ultimo recurso: reiniciar el Master desconectando la alimentacion y reconectando despues de unos segundos.

## Bot de Telegram no responde

- Verificar que el telefono tiene conexion a internet.
- Intentar enviar el comando /start para reiniciar la sesion con el bot.
- Si el servicio en el VPS esta caido, contactar al administrador del sistema.
- Los comandos tienen un cooldown de 8 segundos entre cada uso. Esperar antes de reintentar.

## BLE no detecta el dispositivo

- Verificar que el Bluetooth del telefono esta activado.
- Asegurar que el Master esta en modo configuracion: presionar el clip durante 5 a 8 segundos hasta escuchar un pitido.
- Acercar el telefono al Master. La distancia maxima de BLE es aproximadamente 10 metros.
- Si no aparece en la lista: reiniciar el proceso presionando nuevamente el clip.
- El modo configuracion tiene un timeout de 5 minutos. Si se pasa el tiempo, hay que volver a activarlo.

## WiFi no conecta durante configuracion

- Verificar que la contrasena WiFi ingresada es correcta.
- El Master solo soporta redes WiFi de 2.4 GHz. No es compatible con redes de 5 GHz.
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

- Verificar que las notificaciones push estan habilitadas en la seccion Configuracion dentro de la app.
- Verificar los permisos de notificacion del telefono para la app Sentinel Guard.
- Verificar que las notificaciones del telefono no estan silenciadas o en modo No Molestar.

## Olvide la contrasena del teclado

- Usar el reset de fabrica: mantener presionado Menu (*) durante 3 segundos, luego presionar 2, ingresar el codigo maestro proporcionado por el proveedor y presionar #.
- La contrasena vuelve al valor por defecto: 1234.
- Si no tienes el codigo maestro, contactar directamente al proveedor del sistema.
