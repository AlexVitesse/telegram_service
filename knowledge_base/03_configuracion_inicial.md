# Configuracion Inicial - Sentinel Guard

## Como configurar Sentinel Guard por primera vez (video tutorial paso a paso)

Para configurar Sentinel Guard por primera vez, la forma mas rapida es seguir este video tutorial paso a paso. El video cubre el proceso completo del primer uso e instalacion inicial del sistema:

https://youtu.be/SpDamcPJXHs

Se recomienda ver el video antes de comenzar la configuracion. Muestra como empezar desde cero: como configurar el Modulo Master, como vincularlo con la red WiFi, como vincularlo con Telegram y como dejar el equipo listo para operar. Este video es la guia rapida recomendada para todo usuario nuevo que recien recibe el kit y necesita empezar a usarlo.

## Requisitos previos

Antes de comenzar la configuracion, asegurese de tener:

- La app Sentinel Guard descargada en el telefono, con el Bluetooth activado.
- El Modulo Master encendido y alimentado.
- El nombre (SSID) y la contrasena de la red WiFi de 2.4 GHz donde se conectara el Master. El equipo no se conecta a redes de 5 GHz.
- Opcional: Telegram instalado y tu ID de Telegram, si quieres recibir los avisos por Telegram.

## Registro en la App Sentinel Guard

Para crear una cuenta en la app:

1. Abrir la app Sentinel Guard.
2. Tocar "Registrate" (debajo de "¿No tienes cuenta?").
3. En "Crear Cuenta" ingresar nombre de usuario (minimo 3 caracteres), correo electronico y contrasena.
4. La contrasena debe tener entre 6 y 20 caracteres.
5. Tocar "Crear Cuenta" y luego iniciar sesion con ese correo y contrasena.

Tambien se puede entrar con Google o Apple sin crear una cuenta aparte.

## Configuracion del Master via Bluetooth (BLE)

Asi se da de alta, se agrega, se registra o se vincula el Master a tu cuenta: se empareja desde la app por Bluetooth. En un solo paso el Master recibe la red WiFi y su nombre, y queda registrado en tu cuenta. La app lo muestra en 3 pasos: "PASO 1 Conexion", "PASO 2 Red Wi-Fi" y "PASO 3 Alertas".

### Paso 1: Abrir la pantalla Agregar

En la app toca "Agregar" en la barra inferior, o el boton "Agregar" (o el icono +) en la pantalla Inicio. Si todavia no tienes ningun equipo, el boton principal dice "Vincular un equipo". La tarjeta "Antes de empezar" resume lo que necesitas.

### Paso 2: Poner el Master en modo emparejamiento

Insertar un clip en el orificio trasero del Modulo Master y mantenerlo pulsado unos 3 segundos y soltar al oir los cinco pitidos cortos; no llegar a 10 segundos (eso borra el equipo). Desde ese momento el LED de estado del Master parpadea: el equipo esta en modo emparejamiento.

Precaucion: si se mantiene pulsado 10 segundos o mas, se ejecuta un reset de fabrica que borra toda la configuracion guardada en el Master: red WiFi, nombre, modo de bengala, tiempo de salida, horarios y estado de armado.

### Paso 3: Conectar desde la app

1. Acercate al Master: el Bluetooth alcanza unos 10 metros.
2. La app busca sola ("Buscando dispositivos cercanos…"). El equipo aparece como "Sentinel Master" con el texto "Listo para vincular".
3. Toca el equipo. Si solo hay uno cerca, la app se conecta sola ("Conectando con la central…").

### Paso 4: Configurar dispositivo (WiFi, Telegram y nombre)

Se abre "Configurar dispositivo" (PASO 2 DE 3):

1. **Red WiFi (Requerido)**: elige tu red de la lista. Si no aparece, elige "Ingresar manualmente..." y escribela en "Ingresar SSID". Si no aparece en la lista puede ser de 5 GHz. Tambien puedes usar "Escanear el QR de la red".
2. **Contraseña de la WiFi (Requerido)**: la contrasena de la red WiFi.
3. **Avisos por Telegram (opcional)**: tu CHATID y, si quieres avisos en un grupo, el CHATID GRUPAL.
4. **Nombre del dispositivo (Requerido)**: un nombre para identificar al Master, por ejemplo "Recepcion", "Oficina principal" o "Casa playa".

Toca "Confirmar". Por Bluetooth solo viajan al Master la red WiFi, la contrasena y el nombre; los IDs de Telegram los guarda la app en tu cuenta.

### Paso 5: Conexion y registro

El Master intenta conectarse a la red WiFi; mientras tanto la app muestra "Comprobando la conexión a tu WiFi…" y espera hasta 50 segundos. Si conecta, muestra "Conectado a Wi-Fi exitosamente.", registra el equipo en tu cuenta y espera a que se reinicie ("Dispositivo reiniciando en: N segundos"). Al final aparece "CONFIGURACION COMPLETA - Tu Sentinel ya esta en linea" y el boton "Ir al inicio".

Si el equipo ya estaba en otra cuenta, al emparejarlo pasa a la tuya; la app puede mostrar "Esperando a que la central se conecte…" mientras tanto.

## Si el emparejamiento falla

Mensajes que puede mostrar la app y que hacer:

- "No se pudo conectar a la WiFi. Revisa la contraseña (la red debe ser de 2.4 GHz).": con el firmware de octubre de 2026 sale a los pocos segundos si la contrasena es incorrecta. La central sigue en emparejamiento y conserva la WiFi que tenia antes, asi que puedes corregir la contrasena y tocar "Confirmar" otra vez. Si ya estaba bien, apaga y enciende la central y vuelve a empezar.
- "La conexion tardo demasiado": puede ser una red de 5 GHz, un SSID o contrasena incorrectos, o que la central ya salio del modo emparejamiento.
- "Se perdio la conexion con la central" o "No hay conexion con la central": vuelve a ponerla en modo emparejamiento con el clip e intentalo otra vez.

Si la contrasena WiFi esta mal, el Master sigue en modo emparejamiento hasta que se acaban los 5 minutos y se reinicia; dentro de ese tiempo puedes reintentar desde la misma pantalla. Una contrasena equivocada no se guarda: el Master vuelve a conectarse con la WiFi que ya tenia.

## Tiempo limite de emparejamiento

El modo emparejamiento dura 5 minutos desde los pitidos. Si no se completa en ese tiempo, el Master apaga el Bluetooth, sale del modo emparejamiento y se reinicia solo. Sera necesario repetir el proceso desde el Paso 2 (clip unos 3 segundos, hasta los cinco pitidos).

## Vinculacion con Telegram

Telegram es opcional y se vincula dentro del mismo emparejamiento, en "Avisos por Telegram (opcional)":

1. Para conocer tu ID de Telegram, toca "Obtenerlo ahora" en la tarjeta "Antes de empezar" (abre el bot de Sentinel Guard, @esp32_space_bot, que te muestra tu ID), o envia /id al bot. El bot contesta "Tu Chat ID es: ...".
2. Escribe ese numero en CHATID al configurar el dispositivo.
3. Si lo agregas mas tarde, se hace en la ficha del equipo ("Ver detalles y ajustes" > "Editar" > "Agregar usuario o grupo"), o en Perfil > "Chat ID de Telegram" para tu cuenta.

Cada equipo admite hasta tres destinatarios de Telegram: dos usuarios y un grupo. Para que otra persona controle el equipo desde Telegram, el administrador usa /adduser (ver Usuarios y Permisos).

## Configuracion de grupo de Telegram (opcional)

Si se desea que varias personas reciban notificaciones de alarma en un grupo compartido:

1. Crear un grupo en Telegram.
2. Agregar al bot de Sentinel Guard como miembro del grupo y escribir /id en el grupo. El bot contesta con el numero del grupo (empieza por -).
3. Copiar ese numero en "CHATID GRUPAL" al emparejar, o en la ficha del equipo con "Agregar usuario o grupo" > "Grupo".
4. El grupo solo recibe alertas y notificaciones. No es posible enviar comandos al sistema desde el grupo, solo desde el chat directo con el bot.

## Configuracion del kit completo paso a paso

El kit Sentinel Guard incluye el Modulo Master (ESP32 + LoRa), sensores PIR, sensores magneticos, sirena, modulo de bengala y teclado. Para configurar todo el sistema como un kit nuevo:

### Paso 1: Encender el Master

1. Conectar el Master a su fuente de alimentacion 12V.
2. Al encender, los LEDs y el zumbador se activan un segundo como prueba.
3. Verificar que no haya interferencias fisicas en su ubicacion.

### Paso 2: Crear la cuenta y emparejar el Master

Crear la cuenta en la app (si no existe) y seguir el procedimiento de la seccion "Configuracion del Master via Bluetooth (BLE)". Al terminar, el Master queda conectado a WiFi y registrado en tu cuenta; no hay que agregarlo otra vez.

### Paso 3: Encender los modulos secundarios (slaves)

Los sensores PIR, magneticos, la sirena, la bengala y el teclado vienen ya emparejados de fabrica con el Master incluido en el kit. No se dan de alta desde la app. Solo hay que:

1. Colocar cada modulo en su ubicacion fisica definitiva.
2. Conectar o insertar sus pilas segun el caso.
3. Verificar que cada modulo parpadee su LED de encendido.

La comunicacion entre el Master y los slaves usa LoRa con un canal preconfigurado: el Master reconoce cada modulo la primera vez que lo escucha, por eso no se requiere emparejamiento manual.

### Paso 4: Telegram (opcional)

Si no pusiste tu ID de Telegram al emparejar, agregalo despues como se explica en "Vinculacion con Telegram".

### Paso 5: Probar el sistema

1. Armar la alarma desde la app ("Proteger ahora") o con /on en Telegram.
2. Esperar a que termine el tiempo de salida (60 segundos por defecto).
3. Activar un sensor (abrir una puerta con sensor magnetico o pasar frente a un PIR).
4. Confirmar que la sirena suena y que llega el aviso.
5. Desarmar desde la app ("Desarmar") o con /off.

### Sincronizacion automatica

Los horarios, la configuracion de bengala, el tiempo de salida y demas ajustes se guardan en la nube y llegan al Master cuando esta en linea. No es necesario repetir la configuracion en cada canal. La contrasena del teclado es la excepcion: se guarda solo en el teclado.
