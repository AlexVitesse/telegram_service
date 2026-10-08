# App Sentinel Guard

## Disponibilidad

La app Sentinel Guard esta disponible para Android e iOS. Permite controlar todo el sistema de alarma desde el telefono movil.

La barra inferior tiene cuatro pestañas: "Inicio" (tus equipos), "Agregar" (emparejar un equipo nuevo), "Horarios" y "Perfil" (configuracion de la cuenta).

## Pantalla Login

La pantalla de inicio de sesion ofrece las siguientes opciones:

- **Registro**: "Registrate" abre "Crear Cuenta": nombre de usuario, correo y contrasena de 6 a 20 caracteres.
- **Inicio de sesion**: Ingresar con correo y contrasena, con Google o con Apple.
- **Olvide mi contrasena**: Envia un enlace de recuperacion al correo. Si no llega, revisa la carpeta de SPAM.
- **Mantener sesion iniciada**: Casilla para no tener que ingresar las credenciales cada vez.

## Pantalla Inicio (dispositivos)

Esta es la pantalla principal de la app y funciona como dashboard central:

- **Boton de armado**: "Proteger ahora" arma y "Desarmar" desarma. Actua sobre todas tus centrales a la vez. El titulo muestra "Proteccion activa" o "Sistema desarmado".
- **Atajos**: "Salir" (arma), "En casa" (desarma) y "Programar" (abre Horarios).
- **Boton Emergencia (SOS)**: Activa la alarma (sirena) manualmente en todos tus equipos, con confirmacion previa. Que hace la bengala depende de su modo (ver "Disparo de Emergencia").
- **Boton Atras del telefono**: en la pantalla Inicio sale de la app; en las demas pantallas vuelve a la anterior.
- **Conexion**: "Central en linea" o "Central sin conexion". Una central cuenta como en linea si mando datos en los ultimos 90 segundos.
- **Tarjeta de cada equipo**: nombre, estado ("Armado", "Desarmado" o "Sin conexion") y el boton "Ver detalles y ajustes", que abre la ficha del equipo.
- **Seguridad Programada**: Ver los horarios de armado/desarmado activos.
- **Avisos**: La campana guarda el historial de notificaciones recibidas.
- **Senti, el asistente**: Un boton flotante presente en todas las pantallas. Abre un chat donde puedes preguntar dudas sobre el sistema y tambien dar ordenes escritas: "arma la alarma", "esta armada?", "cuantos equipos tengo?". Arma y desarma de verdad, con el mismo camino que el boton de armado; antes de desarmar pregunta con dos botones y dice que equipo va a desarmar. Lo que todavia no hace desde ahi -silenciar una sirena, la bengala, los horarios, el historial- lo dice y remite a donde se hace. Se puede ocultar desde Perfil > Notificaciones > Senti.

## Ficha del equipo

Se abre tocando la tarjeta del equipo o "Ver detalles y ajustes":

- **Estado**: senal WiFi (Excelente, Buena, Regular o Debil, con su valor en dBm), numero de sensores LoRa y tiempo activo.
- **Proteger equipo / Desarmar equipo**: arma o desarma solo ese equipo.
- **Bengala**: tres modos: "Auto" (se dispara sola), "Pregunta" (Telegram pregunta antes de dispararla) y "Apagada" (no se dispara nunca).
- **Modo de prueba**: "Simular disparo" muestra como se veria una alarma sin enviar nada a la central.
- **Sensores LoRa**: lista de modulos, cada uno "Activo" u "Offline".
- **Ajustes**: direccion MAC, destinatarios de Telegram y tiempo de salida.
- **Editar**: cambiar el "Nombre del equipo", agregar o quitar destinatarios de Telegram ("Agregar usuario o grupo", hasta dos usuarios y un grupo) y ajustar el "Tiempo de salida" (60 por defecto). Se elige de 10 a 180 segundos. Se guarda con "Guardar cambios"; si la central esta sin conexion, el servidor se lo manda en cuanto vuelva a conectarse.
- **Borrar dispositivo**: borra el equipo de tu cuenta y su configuracion en la nube. Con el firmware de octubre de 2026, el Master borrado tambien olvida su horario, tiempos y bengala (conserva la WiFi y el nombre). Con un firmware anterior solo se le apaga el horario y lo demas queda en su memoria; para dejarlo limpio hay que hacer el reset de fabrica (ver "Como desvinculo, quito o borro un dispositivo" en Preguntas Frecuentes).

## Pantalla Horarios

La pestaña "Horarios" (titulo "Programar Alarma") permite programar el armado y desarmado automatico del sistema:

- **Configuracion Rapida (presets)**:
  - Salida al Trabajo: 7:00 a 18:00, lunes a viernes.
  - Hora de Dormir: 22:00 a 7:00, todos los dias.
  - Fin de Semana: 10:00 a 23:00, sabado y domingo.
  - Viaje/Vacaciones: 00:00 a 23:59, todos los dias (proteccion 24 horas).
- **Configuracion manual**: elegir "Equipo" (si tienes varios, uno o "Todos mis equipos"), "Hora de Activacion", "Hora de Desactivacion" y los dias, y tocar "Guardar horario". Las horas se muestran como HH:MM en hora del centro de Mexico (la de CDMX; Merida tiene la misma). Si la central esta sin conexion, el horario se aplica cuando vuelva a conectarse.
- **Alarmas Programadas**: lista de horarios con un icono de papelera para eliminarlos. No hay boton de editar: para cambiar un horario se programa de nuevo.

## Pantalla Perfil (Configuracion)

Opciones generales de la app y la cuenta:

- **Editar Informacion**: "Cambiar Nombre", "Chat ID de Telegram", "Cambiar Correo" y "Cambiar Contrasena" (pide la contrasena actual). La app ya no pide el Chat ID al iniciar sesion: se pone aqui o en la ficha del equipo, solo si quieres avisos por Telegram.
- **Ver los consejos**: vuelve a mostrar los consejos del primer dia (como se usan Salir, En casa y los horarios).
- **Notificaciones**: "Notificaciones Push", "Armado y desarmado", "Conexion de la central", "Avisos por Telegram" y "Senti" (mostrar u ocultar el asistente).
- **Cerrar Sesion**: Salir de la cuenta actual.
- **Eliminar Cuenta**: Eliminacion permanente de la cuenta, de sus equipos y de todos los datos asociados.
- **Acerca de**: version de la app, "Contacto y Soporte" (correo, WhatsApp y sitio web) y "Preguntas Frecuentes".

## Notificaciones Push

La app envia alertas en tiempo real al telefono:

- Alarma activada (intrusion detectada).
- Sistema armado o desarmado.
- Bengala disparada.
- Central sin conexion o que vuelve a conectarse.

Los avisos de alarma y de bengala no se pueden apagar. Los de armado/desarmado y de conexion se activan o desactivan en Perfil > Notificaciones.

Al tocar una notificacion se abre la pantalla Inicio; si el aviso es de un equipo sin conexion, se abre directamente la ficha de ese equipo.

## Vinculacion de dispositivo

Para dar de alta, agregar, registrar o vincular un equipo se usa la pestaña "Agregar":

1. Poner el Master en modo emparejamiento: clip en el orificio trasero, mantener pulsado unos 3 segundos y soltar al oir los cinco pitidos; no llegar a 10 segundos (eso borra el equipo).
2. La app busca por Bluetooth y encuentra "Sentinel Master".
3. En "Configurar dispositivo" se ingresa la red WiFi de 2.4 GHz (SSID y Password), los avisos por Telegram (opcional) y el nombre del dispositivo.
4. Al tocar "Confirmar", el dispositivo se conecta a WiFi, queda registrado en la cuenta y se reinicia.

Los detalles estan en "Configuracion del Master via Bluetooth (BLE)". Los Chat IDs de Telegram se pueden cambiar despues desde la ficha del equipo.
