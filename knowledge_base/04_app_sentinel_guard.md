# App Sentinel Guard

## Disponibilidad

La app Sentinel Guard esta disponible para Android e iOS. Permite controlar todo el sistema de alarma desde el telefono movil.

## Pantalla Login

La pantalla de inicio de sesion ofrece las siguientes opciones:

- **Registro**: Crear cuenta con nombre, email y contrasena.
- **Inicio de sesion**: Ingresar con email y contrasena, Google o Apple.
- **Recuperar contrasena**: Enviar enlace de recuperacion al email registrado.
- **Recordarme**: Opcion para mantener la sesion abierta y no tener que ingresar credenciales cada vez.

## Pantalla Dispositivos (principal)

Esta es la pantalla principal de la app y funciona como dashboard central:

- **Toggle armar/desarmar**: Control rapido para activar o desactivar el sistema de alarma.
- **Boton Activar Alarma**: Disparo manual de la alarma (sirena) desde la app.
- **Informacion del dispositivo**: Nombre, direccion MAC, senal WiFi (dBm), memoria libre, sensores LoRa activos y tiempo encendido (uptime).
- **Editar nombre**: Puedes cambiar el nombre del dispositivo para identificarlo facilmente.
- **Configurar bengala**: Tres modos disponibles: Auto (se dispara sola), Pregunta (te consulta antes de disparar) y Deshabilitada.
- **Horarios activos**: Ver los horarios de armado/desarmado programados.
- **Senti, el asistente**: Un boton flotante presente en todas las pantallas. Abre un chat donde puedes preguntar dudas sobre el sistema y tambien dar ordenes escritas: "arma la alarma", "esta armada?", "cuantos equipos tengo?". Arma y desarma de verdad, con el mismo camino que el toggle; antes de desarmar pregunta con dos botones y dice que equipo va a desarmar. Lo que todavia no hace desde ahi -silenciar una sirena, la bengala, los horarios, el historial- lo dice y remite a donde se hace. Se puede ocultar desde Configuracion.
- **Gestionar IDs de Telegram**: Configurar multiples usuarios de Telegram para recibir notificaciones y controlar el dispositivo.
- **Tiempo de salida**: Configurable de 0 a 180 segundos. Es el tiempo que tienes para salir despues de armar el sistema.
- **Estado en tiempo real**: La informacion se actualiza en tiempo real desde Firebase.

## Pantalla Alarma (horarios)

Permite programar el armado y desarmado automatico del sistema:

- **Presets rapidos**:
  - Trabajo: 7:00 a 18:00, lunes a viernes.
  - Dormir: 22:00 a 7:00, todos los dias.
  - Finde: 10:00 a 23:00, sabado y domingo.
  - Vacaciones: 24/7, armado permanente.
- **Configuracion manual**: Seleccionar hora de armado, hora de desarmado y dias de la semana.
- **Gestion de horarios**: Ver, editar o eliminar horarios existentes.

## Pantalla Configuracion

Opciones generales de la app y la cuenta:

- **Perfil**: Cambiar nombre, email o contrasena.
- **Notificaciones push**: Activar o desactivar las notificaciones en el telefono.
- **Informacion de la app**: Version y datos de la aplicacion.
- **FAQ**: Preguntas frecuentes sobre el sistema.
- **Contacto soporte**: Comunicarse con el equipo de soporte tecnico.
- **Cerrar sesion**: Salir de la cuenta actual.
- **Eliminar cuenta**: Eliminacion permanente de la cuenta y todos los datos asociados.

## Notificaciones Push

La app envia alertas en tiempo real al telefono:

- Alarma activada (intrusion detectada).
- Sistema armado o desarmado.
- Bengala disparada.
- Sensor offline o sin respuesta.

Al tocar una notificacion se abre directamente la pantalla de dispositivos para ver el estado actual.

## Vinculacion de dispositivo

El proceso de vinculacion se realiza desde la pantalla Home de la app:

1. La app escanea dispositivos Bluetooth cercanos.
2. Seleccionar el ESP32 (Master) de la lista.
3. Conectar via Bluetooth Low Energy (BLE).
4. Configurar la red WiFi (nombre y contrasena) y la ubicacion del dispositivo.
5. El dispositivo se reinicia, se conecta a WiFi y queda registrado en la cuenta.

La vinculacion con Telegram es un paso posterior y digital: el usuario debe enviar /start al bot de Telegram para registrarse. Los Chat IDs de Telegram se pueden configurar despues desde la pantalla de Dispositivos, editando la informacion del dispositivo.
