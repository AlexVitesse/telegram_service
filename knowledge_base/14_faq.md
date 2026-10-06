# Preguntas Frecuentes (FAQ)

## Preguntas frecuentes sobre Sentinel Guard

Este documento reune las preguntas frecuentes (FAQ) mas comunes sobre el uso y funcionamiento del sistema de alarma Sentinel Guard. Incluye dudas generales sobre dispositivos, conectividad, bateria, alcance LoRa, multiples usuarios y cobertura sin internet. Para dudas especificas sobre instalacion o solucion de problemas, consulta los documentos dedicados.

## Para que sirve la app Sentinel Guard

La app Sentinel Guard sirve para controlar y vigilar tu alarma desde el telefono, en Android e iOS. Desde la app puedes:

- Armar y desarmar el sistema, o activar la alarma (sirena) manualmente.
- Ver el estado de cada dispositivo en tiempo real: senal WiFi, sensores activos y tiempo encendido.
- Dar de alta (agregar) un dispositivo nuevo y cambiarle el nombre.
- Programar horarios de armado y desarmado automatico.
- Configurar la bengala, el tiempo de salida y los IDs de Telegram que reciben los avisos.
- Recibir notificaciones push cuando salta la alarma o un sensor deja de responder.
- Preguntar dudas a Senti, el asistente, con el boton flotante.

La app es una de las tres formas de controlar Sentinel Guard; las otras son el bot de Telegram y el teclado fisico.

## Como doy de alta, agrego o emparejo un dispositivo o equipo nuevo?

Si te preguntas como agrego, añado, registro, vinculo o emparejo mi equipo, o como doy de alta un dispositivo nuevo (el Master o central del equipo): se hace desde la app Sentinel Guard por Bluetooth. Antes de empezar ten a mano tu red WiFi de 2.4 GHz con su contraseña y, si quieres recibir avisos, tu ID de Telegram.

1. En la app, pulsa "+ Agregar".
2. Pon el equipo en modo emparejamiento: busca el orificio trasero del Master, inserta un clip y mantenlo pulsado de 5 a 8 segundos, hasta oir un pitido. No pases de 10 segundos: eso hace un reset de fabrica.
3. Acercate al dispositivo. El Bluetooth alcanza unos 10 metros.
4. En la pantalla "Configurar dispositivo" ingresa el nombre de tu red WiFi (SSID), su contraseña, tu ID de Telegram para los avisos (opcional) y un nombre para el dispositivo. Pulsa "Confirmar".
5. El Master se reinicia, se conecta a WiFi y queda registrado en tu cuenta.

### Tiempo para emparejar y modulos del kit

Desde el pitido tienes 5 minutos para emparejar el equipo. Si se pasa ese tiempo, el Master sale del modo emparejamiento y se reinicia solo; vuelve a ponerlo en modo emparejamiento con el clip. Los sensores, la sirena, la bengala y el teclado del kit ya vienen emparejados de fabrica con su Master y no hay que darlos de alta uno por uno.

La guia detallada esta en "Configuracion del Master via Bluetooth (BLE)". Si el Bluetooth no encuentra el equipo, revisa "BLE no detecta el dispositivo" en Solucion de Problemas.

## Cuantos dispositivos puedo tener?

Puedes tener multiples dispositivos en una misma cuenta. Cada dispositivo se vincula individualmente mediante Bluetooth (BLE). Todos se controlan desde la misma app Sentinel Guard y desde Telegram.

## Funciona sin internet?

Parcialmente. El ESP32 puede ejecutar los horarios programados de forma autonoma ya que utiliza NTP para mantener la hora. Sin embargo, sin internet no recibiras notificaciones ni podras controlar el sistema de forma remota desde la app o Telegram.

## Puedo usar el bot en un grupo de Telegram?

Si, pero con limitaciones. El grupo solo recibe notificaciones de alerta (alarma activada, sensores, etc.). Los comandos de control solo funcionan en chat privado con el bot. El GroupID se configura durante el setup inicial del dispositivo.

## Que pasa si se va la luz?

El Master (ESP32) y la sirena necesitan alimentacion electrica continua para funcionar. Los sensores LoRa funcionan con bateria propia y seguiran operando. Si se va la luz, el Master se desconecta, pero al volver la electricidad se reconecta automaticamente y retoma su operacion normal.

## Cuanto alcance tiene el sistema?

Los modulos LoRa tienen los siguientes alcances aproximados:

- Espacio abierto: hasta 50 metros.
- A traves de madera: hasta 35 metros.
- A traves de ladrillo o block: hasta 20 metros.
- A traves de metal: hasta 5 metros.

## Puedo tener varios usuarios?

Si. El administrador puede agregar usuarios con el comando /adduser. Cada usuario puede controlar los dispositivos que le sean asignados. Se pueden configurar hasta 2 Telegram IDs por dispositivo de forma directa, y mas usuarios a traves de grupos de Telegram.

## Como se cuanto dura la bateria de los sensores?

Los sensores LoRa son de bajo consumo energetico. La duracion de la bateria depende del modelo del sensor y la frecuencia de uso. Puedes verificar el estado de los sensores activos con el comando /sensors en Telegram.

## Es seguro el sistema?

Si. La comunicacion MQTT utiliza cifrado TLS a traves del puerto 8883. Los datos se almacenan en Firebase con autenticacion. El teclado fisico tiene proteccion anti-intrusion: despues de 5 intentos fallidos de contrasena, se bloquea durante 10 minutos.

## Puedo cambiar el nombre de un dispositivo?

Si. Desde la app, entra a la pantalla de Dispositivos, selecciona el dispositivo que quieres renombrar y edita el nombre directamente.

## Que es el tiempo de salida?

Es el periodo que tienes para salir del area protegida despues de armar el sistema. Por defecto es de 1 minuto y se puede configurar desde la app entre 0 y 180 segundos. Durante este tiempo los sensores no disparan la alarma, permitiendote salir sin activarla.

## Como desvinculo un dispositivo?

Puedes desvincular un dispositivo de dos formas:

- Desde Telegram con el comando /desvincular.
- Desde la app, eliminando el dispositivo de tu cuenta.

Para volver a vincular el dispositivo necesitaras una nueva invitacion.

## Puedo programar horarios diferentes por dispositivo?

Si. Desde la app puedes crear horarios especificos para cada dispositivo individual, o configurar horarios globales que apliquen a todo el sistema completo.
