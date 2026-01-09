# Comandos del Bot de Telegram - Sentinel Guard

Documentacion completa de todos los comandos disponibles en el bot de Telegram.

---

## Comandos Basicos

### `/start`
Inicia la interaccion con el bot.

- **Permisos:** Ninguno (publico)
- **Descripcion:**
  - Si es el primer usuario, se registra como Administrador Principal
  - Si ya esta autorizado, muestra mensaje de bienvenida
  - Si no esta autorizado, muestra instrucciones para solicitar acceso

---

### `/help`
Muestra la guia de comandos disponibles.

- **Permisos:** Usuario autorizado
- **Descripcion:** Lista todos los comandos segun el nivel de permisos del usuario

---

## Comandos de Seguridad

### `/status`
Consulta el estado actual del sistema.

- **Permisos:** Usuario autorizado
- **Cooldown:** 8 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: consulta directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Espera 5 segundos por respuesta del dispositivo
- **Respuesta incluye:**
  - Estado del sistema (ARMADO/DESARMADO)
  - Estado de bengala (HABILITADA/DESHABILITADA)
  - Intensidad de senal WiFi (dBm)

---

### `/on`
Arma el sistema de alarma.

- **Permisos:** Usuario autorizado
- **Cooldown:** 8 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: arma directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Opcion "Armar TODOS" disponible para multiples dispositivos
  - Espera confirmacion del dispositivo (5 segundos)

---

### `/off`
Desarma el sistema de alarma.

- **Permisos:** Usuario autorizado
- **Cooldown:** 8 segundos
- **Descripcion:**
  - Si tiene 1 dispositivo: desarma directamente
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Opcion "Desarmar TODOS" disponible para multiples dispositivos
  - Espera confirmacion del dispositivo (5 segundos)

---

### `/disparo`
Activa la alarma manualmente (disparo de sirena).

- **Permisos:** Usuario autorizado
- **Cooldown:** 8 segundos
- **Descripcion:**
  - Muestra confirmacion antes de ejecutar
  - Botones: "Confirmar" / "Cancelar"
  - Activa la sirena en todos los dispositivos autorizados

---

## Comandos de Bengala

### `/bengala`
Menu de configuracion del sistema de bengala.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Muestra el modo actual de bengala
  - Opciones disponibles:
    - **Modo Auto:** Dispara bengala automaticamente con la alarma
    - **Modo Pregunta:** Pregunta antes de disparar
    - **Deshabilitar:** No dispara bengala

---

### `/auto`
Configura la bengala en modo automatico.

- **Permisos:** Usuario autorizado
- **Descripcion:** La bengala se dispara automaticamente cuando se activa la alarma, sin preguntar

---

### `/preguntar`
Configura la bengala en modo con pregunta.

- **Permisos:** Usuario autorizado
- **Descripcion:** Cuando se activa la alarma, el bot pregunta si deseas disparar la bengala

---

### `/si`
Confirma el disparo de bengala.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Confirma una solicitud pendiente de bengala
  - Si no hay solicitud pendiente, dispara bengala en dispositivos en alarma activa

---

### `/no`
Cancela el disparo de bengala.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Cancela una solicitud pendiente de bengala
  - La alarma continua activa pero sin disparar la bengala

---

## Comandos de Dispositivos

### `/desvincular`
Desvincula un dispositivo de tu cuenta.

- **Permisos:** Usuario autorizado
- **Descripcion:**
  - Si tiene 1 dispositivo: muestra confirmacion directa
  - Si tiene multiples dispositivos: muestra menu de seleccion
  - Requiere confirmacion antes de desvincular
  - Despues de desvincular, necesitas nueva invitacion para volver a vincular

---

## Comandos de Administracion

> Estos comandos solo estan disponibles para usuarios con rol de Administrador.

### `/permisos`
Muestra la lista de usuarios registrados.

- **Permisos:** Administrador
- **Descripcion:** Lista todos los usuarios con sus:
  - Nombre
  - Chat ID
  - Dispositivos asignados
  - Rol (admin/usuario)

---

### `/horarios`
Configura la programacion automatica del sistema.

- **Permisos:** Administrador
- **Uso:**
  ```
  /horarios              - Ver estado actual
  /horarios on           - Habilitar programacion
  /horarios off          - Deshabilitar programacion
  /horarios activar HH:MM    - Configurar hora de armado
  /horarios desactivar HH:MM - Configurar hora de desarmado
  ```
- **Ejemplos:**
  ```
  /horarios activar 22:00    - Armar a las 10:00 PM
  /horarios desactivar 06:30 - Desarmar a las 6:30 AM
  ```
- **Notas:**
  - Formato de hora: 24 horas (HH:MM)
  - Los cambios se sincronizan con el ESP32 y Firebase

---

### `/sensors`
Consulta informacion de los sensores.

- **Permisos:** Usuario autorizado
- **Descripcion:** Solicita al dispositivo la lista de sensores configurados

---

### `/adduser`
Genera un codigo de invitacion para agregar nuevos usuarios.

- **Permisos:** Administrador
- **Descripcion:**
  - Genera un codigo unico: `/join_DEVICE_ID`
  - El nuevo usuario debe enviar este codigo al bot
  - El administrador recibe notificacion para aprobar

---

## Comandos Dinamicos

### `/join_XXXXX`
Solicita acceso al sistema (usado por nuevos usuarios).

- **Permisos:** Ninguno (publico)
- **Descripcion:**
  - El usuario envia el codigo recibido del administrador
  - Se crea una solicitud pendiente
  - El administrador recibe notificacion con `/approve_CHATID`

---

### `/approve_XXXXX`
Aprueba la solicitud de un nuevo usuario.

- **Permisos:** Administrador
- **Descripcion:**
  - Aprueba al usuario con el Chat ID especificado
  - El usuario recibe notificacion de acceso aprobado
  - Se le asignan los dispositivos correspondientes

---

## Flujo de Invitacion de Usuarios

```
1. Admin ejecuta: /adduser
   Bot responde: "Envia este codigo: /join_ALARMA_MERIDA"

2. Admin envia el codigo al nuevo usuario (WhatsApp, SMS, etc.)

3. Nuevo usuario envia al bot: /join_ALARMA_MERIDA
   Bot responde: "Solicitud enviada al administrador"

4. Admin recibe: "Nueva solicitud de acceso de [Nombre]"
   Con instruccion: /approve_123456789

5. Admin ejecuta: /approve_123456789
   - Usuario queda registrado
   - Usuario recibe: "Acceso aprobado!"
```

---

## Callbacks de Botones Inline

El bot utiliza botones interactivos en varios comandos:

| Callback | Descripcion |
|----------|-------------|
| `trigger_confirm` | Confirma disparo manual de alarma |
| `trigger_cancel` | Cancela disparo manual |
| `bengala_confirm` | Confirma disparo de bengala |
| `bengala_cancel` | Cancela disparo de bengala |
| `bengala_on` | Activa bengala |
| `bengala_off` | Desactiva bengala |
| `bengala_mode_auto` | Cambia a modo automatico |
| `bengala_mode_ask` | Cambia a modo pregunta |
| `arm_DEVICEID` | Arma dispositivo especifico |
| `arm_all` | Arma todos los dispositivos |
| `disarm_DEVICEID` | Desarma dispositivo especifico |
| `disarm_all` | Desarma todos los dispositivos |
| `status_DEVICEID` | Estado de dispositivo especifico |
| `status_all` | Estado de todos los dispositivos |
| `unlink_DEVICEID` | Confirma desvinculacion |
| `unlink_cancel` | Cancela desvinculacion |

---

## Teclado Estandar

El bot muestra un teclado permanente con los comandos mas usados:

```
[ /on  ] [ /off     ]
[    /disparo       ]
[    /status        ]
[    /bengala       ]
```

---

## Sistema Anti-Spam

- **Cooldown de comandos:** Evita ejecucion repetida del mismo comando
- **Lock de ejecucion:** Previene ejecuciones concurrentes
- **Deduplicacion de mensajes:** No envia mensajes identicos en 15 segundos

---

## Notas Tecnicas

- Los comandos que esperan respuesta del dispositivo tienen timeout de 5-7 segundos
- El cooldown de `/status`, `/on`, `/off`, `/disparo` es de 8 segundos
- Los cambios en horarios se sincronizan automaticamente con Firebase y ESP32
- Las confirmaciones de bengala expiran en 2 minutos
- Los recordatorios de bengala se envian cada 30 segundos mientras la alarma esta activa
