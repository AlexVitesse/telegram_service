# App Sentinel Guard

## Disponibilidad

La app Sentinel Guard esta disponible para Android e iOS. Permite controlar todo el sistema de alarma desde el telefono movil.

La barra inferior tiene cuatro pestañas: "Inicio" (tus equipos), "Agregar" (emparejar un equipo nuevo), "Horarios" y "Perfil" (configuracion de la cuenta).

## Pantalla Login

La pantalla de inicio de sesion ofrece las siguientes opciones:

- **Registro**: "Registrate" abre "Crear Cuenta": nombre de usuario, correo y contrasena de exactamente 6 caracteres.
- **Inicio de sesion**: Ingresar con correo y contrasena, con Google o con Apple.
- **Olvide mi contrasena**: Envia un enlace de recuperacion al correo. Si no llega, revisa la carpeta de SPAM.
- **Mantener sesion iniciada**: Casilla para no tener que ingresar las credenciales cada vez.

## Pantalla Inicio (dispositivos)

Esta es la pantalla principal de la app y funciona como dashboard central:

- **Boton de armado**: "Proteger ahora" arma y "Desarmar" desarma. Actua sobre todas tus centrales a la vez. El titulo muestra "Proteccion activa" o "Sistema desarmado".
- **Atajos**: "Salir" (arma), "En casa" (desarma) y "Programar" (abre Horarios).
- **Boton Emergencia (SOS)**: "Solicitar ayuda inmediata". Activa la alarma (sirena) manualmente en todos tus equipos, con confirmacion previa. Que hace la bengala depende de su modo (ver "Disparo de Emergencia"). Si la central no tiene conexion, la app al menos avisa a tu grupo de Telegram.
- **Tengo un codigo**: junto a "Agregar"; sirve para unirte a una central que te compartieron (ver Usuarios y Permisos).
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
- **Bengala**: tres modos: "Auto" (se dispara sola), "Pregunta" (Telegram pregunta antes de dispararla) y "OFF" (Apagada: no se dispara nunca).
- **Modo de prueba**: "Simular disparo" muestra como se veria una alarma sin enviar nada a la central.
- **Sensores nuevos**: aparece solo si hay sensores esperando permiso (ver "Que es un sensor nuevo o en cuarentena" en Preguntas Frecuentes). Cada uno tiene "Autorizar", que pide confirmacion, y en las versiones nuevas tambien "Ignorar". Mientras no se autoriza, ese sensor no dispara la alarma. Los ignorados pasan a la lista **Ignorados**, con "Autorizar" por si fue un error, y no vuelven a avisar.
- **Sensores LoRa**: lista de modulos autorizados, cada uno "Activo" u "Offline". Cada sensor tiene dos botones: el lapiz para renombrarlo (hasta 32 caracteres) y la papelera para eliminarlo (pide confirmacion). Funcionan tambien sin internet si el telefono esta en la misma red WiFi que la central.
- **Personas con acceso** (desde la version 8.2, solo la ve el dueño): la lista de personas de la familia que comparten la central, con "Invitar" (codigo QR de 15 minutos), "Invitar por WhatsApp (codigo de 24 h)" y "Quitar" junto a cada nombre. Quien recibe el codigo lo canjea con "Tengo un codigo" en la pantalla de Inicio. Ver "Compartir la central con tu familia desde la app" en Usuarios y Permisos.
- **Si la central es compartida contigo** (eres de la familia, no el dueño): la ficha muestra el estado, "Proteger equipo / Desarmar equipo", el modo de prueba y los horarios del dueño solo para ver. No aparecen "Editar", la bengala, los sensores, los destinatarios de Telegram ni la red WiFi, y en lugar de "Borrar dispositivo" dice "Salir de esta central".
- **Ajustes**: "Red WiFi" (para cambiar de red si cambiaste el modem o su contrasena, ver Solucion de Problemas), direccion MAC, "Avisos de Telegram" (numero de destinatarios) y tiempo de salida.
- **Editar**: cambiar el "Nombre del equipo", agregar o quitar destinatarios de Telegram ("Agregar usuario o grupo", hasta dos usuarios y un grupo) y ajustar el "Tiempo de salida" (60 por defecto). Se elige de 10 a 180 segundos. Se guarda con "Guardar cambios"; si la central esta sin conexion, el cambio se le aplica en cuanto vuelva a conectarse.
- **Borrar dispositivo**: borra el equipo de tu cuenta y su configuracion en la nube. En los equipos actualizados (octubre de 2026 en adelante), el Master borrado tambien olvida su horario, tiempos y bengala (conserva la WiFi y el nombre). En un equipo sin actualizar solo se le apaga el horario y lo demas queda en su memoria; para dejarlo limpio hay que hacer el reset de fabrica (ver "Como desvinculo, quito o borro un dispositivo" en Preguntas Frecuentes).

## Pantalla Horarios

La pestaña "Horarios" (titulo "Programar horario") arma y desarma tu central sola a la hora que elijas, aunque no haya internet:

- **Lista de horarios**: cada horario muestra su nombre, a que hora "Se arma" y "Se desarma", los dias (o las fechas de vacaciones) y el proximo paso. Tiene un interruptor para pausarlo ("En pausa: no hara nada"), "Editar" y "Eliminar".
- **Crear un horario** ("Programar" o "Agregar otro horario"):
  1. "Nombre", por ejemplo Trabajo, Noche o Playa.
  2. El tipo: "Cada semana" o "Vacaciones".
  3. Si tienes varias centrales, elige una o "Todas mis centrales".
  4. Cada semana: atajos "Trabajo" (7:00 a 18:00, lunes a viernes), "Noche" (22:00 a 7:00, todos los dias) y "Fin de semana" (10:00 a 23:00, sabado y domingo), o elige tu "Se arma" y "Se desarma" y los dias ("Entre semana", "Fin de semana", "Todos" o dia por dia). "Sin hora de regreso": solo se arma, y la desarmas tu al volver.
  5. Vacaciones: fechas "Desde" y "Hasta" y la hora a la que se arma el primer dia y se desarma el ultimo.
  6. Toca "Guardar horario" ("Guardar cambios" si estabas editando).
- **Cuantos horarios**: hasta 4 por central en los equipos actualizados. Una central sin actualizar admite uno solo (el nuevo reemplaza al anterior) y no acepta "Vacaciones" ni "Sin hora de regreso": la app te avisa de que necesita una actualizacion. Si dos horarios de la misma central se enciman, la app no deja guardarlo y te dice con cual choca.
- Las horas son las del centro de Mexico (la de CDMX; Merida tiene la misma). Si la central esta sin conexion, el horario se aplica cuando vuelva a conectarse.

## Pantalla Perfil (Configuracion)

Opciones generales de la app y la cuenta:

- **Editar Informacion**: "Cambiar Nombre", "Chat ID de Telegram", "Cambiar Correo" y "Cambiar Contrasena" (pide la contrasena actual). La app ya no pide el Chat ID al iniciar sesion: se pone aqui o en la ficha del equipo, solo si quieres avisos por Telegram. En "Chat ID de Telegram", "Abrir el bot" vincula tu Telegram solo: pulsas "Iniciar" en Telegram y al volver el numero aparece (o toca "Comprobar ahora").
- **Ver los consejos**: vuelve a mostrar los consejos del primer dia (como se usan Salir, En casa y los horarios).
- **Notificaciones**: "Notificaciones Push", "Armado y desarmado", "Conexion de la central", "Avisos por Telegram" (apagado silencia todo lo que te llega a ti por Telegram, alarmas incluidas; el grupo y los demas siguen igual), "Grupo de Telegram: todos los avisos" (apagado, el grupo solo recibe alarmas y SOS), "Senti" (mostrar u ocultar el asistente) y "Sonidos".
- **Apariencia**: "Tema" claro u oscuro.
- **Cerrar Sesion**: Salir de la cuenta actual.
- **Eliminar Cuenta**: Eliminacion permanente de la cuenta, de sus equipos y de todos los datos asociados.
- **Acerca de**: version de la app, "Catalogo Familia Sentinel" (los equipos que puedes sumar), "Contacto y Soporte" (correo, WhatsApp y sitio web) y "Preguntas Frecuentes".

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

1. Poner el Master en modo emparejamiento: clip en el orificio trasero, mantener presionado de 5 a 8 segundos, hasta escuchar un pitido; no llegar a 10 segundos (eso borra el equipo).
2. La app busca por Bluetooth y encuentra "Sentinel Master".
3. En "Configurar dispositivo" se ingresa la red WiFi de 2.4 GHz (SSID y Password), los avisos por Telegram (opcional) y el nombre del dispositivo.
4. Al tocar "Confirmar", el dispositivo se conecta a WiFi, queda registrado en la cuenta y se reinicia (unos 30 segundos).

Los detalles estan en "Configuracion del Master via Bluetooth (BLE)". Los Chat IDs de Telegram se pueden cambiar despues desde la ficha del equipo.
