# Configuracion Inicial - Sentinel Guard

## Requisitos previos

Antes de comenzar la configuracion, asegurese de tener:

- Un telefono con Telegram instalado.
- La app Sentinel Guard descargada en el telefono.
- El Modulo Master encendido y alimentado.
- Acceso a la red WiFi donde se conectara el Master (nombre de red y contrasena).

## Registro en la App Sentinel Guard

Para crear una cuenta en la app:

1. Abrir la app Sentinel Guard.
2. Seleccionar la opcion de registro.
3. Ingresar nombre completo, correo electronico y contrasena.
4. La contrasena debe tener entre 4 y 8 caracteres. Puede incluir letras mayusculas, minusculas, numeros y caracteres especiales.

## Configuracion del Master via Bluetooth (BLE)

Este paso permite conectar el Master a la red WiFi y asignarle un nombre de ubicacion. La configuracion BLE solo transmite tres datos: SSID, contrasena WiFi y ubicacion.

### Paso 1: Entrar en modo configuracion

Insertar un clip o alfiler en el orificio trasero del Modulo Master y mantener presionado entre 5 y 8 segundos hasta escuchar un pitido. Esto indica que el Master entro en modo configuracion.

Precaucion: si se mantiene presionado por mas de 10 segundos, se ejecutara un reset de fabrica que borra toda la configuracion almacenada.

### Paso 2: Conectar desde la app

1. Activar Bluetooth en el telefono.
2. Abrir la app Sentinel Guard.
3. La app escanea automaticamente los dispositivos cercanos.
4. Presionar el boton "Conectar dispositivo" cuando aparezca el Master.

### Paso 3: Configurar WiFi y ubicacion

1. Seleccionar la red WiFi (SSID) de la lista que muestra la app.
2. Ingresar la contrasena de la red WiFi.
3. Ingresar un nombre descriptivo para identificar al Master, por ejemplo: "Recepcion", "Pasillo", "Oficina principal", "Casa playa".

### Paso 4: Guardar configuracion

Presionar el boton "Aceptar". El equipo se reiniciara automaticamente, se conectara a la red WiFi configurada y quedara listo para operar.

## Vinculacion con Telegram (paso posterior)

La vinculacion con Telegram NO se realiza durante la configuracion BLE. Es un proceso totalmente digital que se hace despues de que el Master ya esta conectado a WiFi:

1. Abrir Telegram y buscar el chatbot de Sentinel Guard (escaneando el QR del instructivo impreso o buscando el bot directamente).
2. Enviar el comando /start al bot. El primer usuario que lo haga quedara registrado como Administrador Principal.
3. El bot vincula automaticamente el dispositivo con tu cuenta de Telegram usando el ID de tu chat.
4. Para agregar mas usuarios, el administrador usa el comando /adduser para generar un codigo de invitacion.

## Configuracion de grupo de Telegram (opcional)

Si se desea que varias personas reciban notificaciones de alarma en un grupo compartido:

1. Crear un grupo en Telegram.
2. Agregar al chatbot de Sentinel Guard como miembro del grupo.
3. El grupo solo recibe alertas y notificaciones. No es posible enviar comandos al sistema desde el grupo, solo desde el chat directo con el bot.
4. El ID del grupo se puede configurar desde la app en la pantalla de Dispositivos, editando los datos del dispositivo.

## Tiempo limite de configuracion

El modo configuracion BLE tiene un timeout de 5 minutos. Si no se completa la configuracion dentro de ese tiempo, el Master sale automaticamente del modo configuracion y vuelve a su operacion normal. Sera necesario repetir el proceso desde el Paso 1.
