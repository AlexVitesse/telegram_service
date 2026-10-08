# Preguntas Frecuentes (FAQ)

## Preguntas frecuentes sobre Sentinel Guard

Este documento reune las preguntas frecuentes (FAQ) mas comunes sobre el uso y funcionamiento del sistema de alarma Sentinel Guard. Incluye dudas generales sobre dispositivos, conectividad, bateria, alcance LoRa, multiples usuarios y cobertura sin internet. Para dudas especificas sobre instalacion o solucion de problemas, consulta los documentos dedicados.

## Para que sirve la app Sentinel Guard

La app Sentinel Guard sirve para controlar y vigilar tu alarma desde el telefono, en Android e iOS. Desde la app puedes:

- Armar y desarmar el sistema, o activar la alarma (sirena) manualmente.
- Ver el estado de cada dispositivo en tiempo real: senal WiFi, sensores LoRa y tiempo activo.
- Dar de alta (agregar) un dispositivo nuevo, cambiarle el nombre o borrarlo.
- Programar horarios de armado y desarmado automatico.
- Configurar la bengala, el tiempo de salida y los IDs de Telegram que reciben los avisos.
- Recibir notificaciones push cuando salta la alarma o un sensor deja de responder.
- Preguntar dudas a Senti, el asistente, con el boton flotante.

La app es una de las tres formas de controlar Sentinel Guard; las otras son el bot de Telegram y el teclado fisico.

## Como doy de alta, agrego, vinculo, registro o emparejo un dispositivo o equipo nuevo?

Si te preguntas como vinculo un dispositivo, como registro un dispositivo, como agrego, añado o emparejo mi equipo, o como doy de alta un dispositivo nuevo (el Master o central del equipo): se hace desde la app Sentinel Guard por Bluetooth. Antes de empezar ten a mano tu red WiFi de 2.4 GHz con su contraseña y, si quieres recibir avisos, tu ID de Telegram.

1. En la app, pulsa "Agregar" en la barra inferior (o el icono + de la pantalla Inicio).
2. Pon el equipo en modo emparejamiento: busca el orificio trasero del Master, inserta un clip, mantén pulsado unos 3 segundos y suelta al oír los cinco pitidos; no llegues a 10 segundos (eso borra el equipo con un reset de fabrica).
3. Acercate al dispositivo. El Bluetooth alcanza unos 10 metros.
4. Cuando aparezca "Sentinel Master", tocalo. En la pantalla "Configurar dispositivo" (Paso 2 de 3) ingresa el nombre de tu red WiFi (de la lista o con "Escribirla a mano..."), su contraseña, tu ID de Telegram en "Avisos por Telegram (opcional)" y el "Nombre del dispositivo". Pulsa "Confirmar".
5. El Master se conecta a WiFi, queda registrado en tu cuenta y se reinicia. La app termina con "CONFIGURACION COMPLETA".

### Tiempo para emparejar y modulos del kit

Desde el pitido tienes 5 minutos para emparejar el equipo. Si se pasa ese tiempo, el Master sale del modo emparejamiento y se reinicia solo; vuelve a ponerlo en modo emparejamiento con el clip. Los sensores, la sirena, la bengala y el teclado del kit ya vienen emparejados de fabrica con su Master y no hay que darlos de alta uno por uno.

La guia detallada esta en "Configuracion del Master via Bluetooth (BLE)". Si el Bluetooth no encuentra el equipo, revisa "BLE no detecta el dispositivo" en Solucion de Problemas.

## Cuantos dispositivos puedo tener?

Puedes tener multiples dispositivos en una misma cuenta. Cada dispositivo se vincula individualmente mediante Bluetooth (BLE). Todos se controlan desde la misma app Sentinel Guard y desde Telegram.

## Funciona sin internet?

Parcialmente. Sin internet el Master sigue vigilando: los sensores, la sirena y el teclado funcionan por LoRa directamente con el Master, y ejecuta los horarios programados de forma autonoma usando la hora que sincronizo por NTP. Si el Master se reinicia sin internet, no ejecuta horarios hasta recuperar la hora. Sin internet no recibiras notificaciones ni podras controlar el sistema de forma remota desde la app o Telegram.

## Puedo usar el bot en un grupo de Telegram?

Si, pero con limitaciones. El grupo solo recibe notificaciones de alerta (alarma activada, sensores, etc.). Los comandos de control solo funcionan en chat privado con el bot. El ID del grupo se pone en la app: en "CHATID GRUPAL" al emparejar, o en la ficha del equipo con "Agregar usuario o grupo". Para saberlo, escribe /id dentro del grupo.

## Que pasa si se va la luz?

El Master (ESP32) y la sirena necesitan alimentacion electrica continua para funcionar. Los sensores LoRa funcionan con bateria propia y seguiran operando. Si se va la luz, el Master se desconecta, pero al volver la electricidad se reconecta automaticamente y retoma su operacion normal: recuerda si estaba armado, su red WiFi, el modo de bengala y el horario.

## Cuanto alcance tiene el sistema?

Los modulos LoRa tienen los siguientes alcances aproximados:

- Espacio abierto: hasta 50 metros.
- A traves de madera: hasta 35 metros.
- A traves de ladrillo o block: hasta 20 metros.
- A traves de metal: hasta 5 metros.

## Puedo tener varios usuarios?

Si. El administrador puede agregar usuarios con el comando /adduser, o el dueño puede poner su Chat ID en la ficha del equipo en la app. Cada equipo admite hasta 3 destinatarios de Telegram: 2 usuarios y 1 grupo; con un grupo pueden enterarse mas personas. La cuenta de la app es personal: no hay opcion para compartir un equipo con otra cuenta de la app.

## Como se cuanto dura la bateria de los sensores?

Los sensores LoRa son de bajo consumo energetico. La duracion de la bateria depende del modelo del sensor y la frecuencia de uso. El sistema no mide el nivel de bateria, pero con el comando /sensors en Telegram puedes ver cada sensor, su senal y hace cuanto se escucho por ultima vez; un sensor que lleva mucho sin oirse puede tener la bateria agotada.

## Es seguro el sistema?

Si. La comunicacion MQTT utiliza cifrado TLS a traves del puerto 8883 (o del 8884, WebSocket tambien cifrado, si el proveedor de internet bloquea el 8883). Los datos se almacenan en Firebase con autenticacion. El teclado fisico tiene proteccion anti-intrusion: despues de 5 intentos fallidos de contrasena, se bloquea durante 10 minutos.

## Puedo cambiar el nombre de un dispositivo?

Si. Desde la app, en la pantalla Inicio toca el equipo ("Ver detalles y ajustes"), luego "Editar", cambia "Nombre del equipo" y toca "Guardar cambios".

## Que es el tiempo de salida?

Es el periodo que tienes para salir del area protegida despues de armar el sistema. Por defecto es de 60 segundos y se cambia en la ficha del equipo ("Editar" > "Tiempo de salida"), entre 10 y 180 segundos. Si eliges menos de 10, no se aplica: el Master conserva el valor que tenia. Durante este tiempo el Master pita cada 5 segundos y los sensores no disparan la alarma, permitiendote salir sin activarla. No hay tiempo de entrada: al volver, desarma antes de entrar.

## Como desvinculo, quito o borro un dispositivo?

Si te preguntas como desvinculo un dispositivo, como borro un dispositivo, como quito un equipo o como elimino un equipo de mi cuenta, hay dos cosas distintas:

- **Borrar el equipo de la app**: abre la ficha del equipo y toca "Borrar dispositivo", luego "Eliminar". Se borra el equipo de tu cuenta y su configuracion en la nube: listas de cuentas, destinatarios de Telegram y horarios. Ademas se manda a la central la orden de apagar su horario; si esta desconectada, se la manda el servidor en cuanto vuelva a conectarse, aunque pasen dias. Con el firmware de octubre de 2026, si la central esta conectada al borrarla (o en cuanto se reinicie), tambien olvida su horario, tiempo de salida y modo de bengala; conserva la WiFi y su nombre. Con un firmware anterior, la memoria local del Master (nombre, tiempo de salida y modo de bengala) no se borra. Para dejarla limpia del todo, haz el reset de fabrica (clip 10 segundos o mas). El equipo sigue funcionando, pero para volver a controlarlo desde la app hay que emparejarlo otra vez por Bluetooth (pestaña "Agregar", clip unos 3 segundos hasta los cinco pitidos). Solo el dueño de la central puede borrarla con toda su configuracion. Si la central ya es de otra cuenta (en la app sale como "Error al cargar"), "Borrar dispositivo" solo la quita de tu lista, sin tocar la central ni la cuenta de su dueño.
- **Quitar solo tu Telegram**: el comando /desvincular quita tu chat de los destinatarios de un equipo. Dejas de recibir sus avisos por Telegram y de controlarlo desde ahi, pero el equipo sigue en la app. Para volver, pide al administrador un nuevo codigo con /adduser, o que el dueño vuelva a poner tu Chat ID en la ficha del equipo.

## Puedo programar horarios diferentes por dispositivo?

Si. Cada equipo tiene su propio horario. En la pestaña Horarios eliges el "Equipo"; con "Todos mis equipos" se guarda el mismo horario en cada uno. En Telegram, /horarios pregunta primero sobre que equipo actuar.

## Como consigo mi Chat ID o ID de Telegram?

Envia /id al bot de Sentinel Guard (@esp32_space_bot) por chat privado: contesta "Tu Chat ID es: ..." con tu numero. En la app, el boton "Obtenerlo ahora" de la pantalla Agregar abre el bot directamente. Para el ID de un grupo, agrega el bot al grupo y escribe /id dentro del grupo: el numero empieza por -.

Tu Chat ID se pone en la app en Perfil > "Chat ID de Telegram", en "Avisos por Telegram (opcional)" al emparejar, o en la ficha del equipo con "Agregar usuario o grupo".

## Que pasa si mantengo el clip mas de 10 segundos (reset de fabrica)?

Con el clip pulsado unos 3 segundos el Master entra en modo emparejamiento y suenan cinco pitidos: suelta en ese momento. Si sigues pulsando hasta 10 segundos o mas, hace un reset de fabrica: borra la red WiFi, el nombre, el modo de bengala, el tiempo de salida, los horarios y el estado de armado guardados en el Master, y se reinicia. Despues hay que emparejarlo otra vez desde la app.
