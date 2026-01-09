# Sentinel Guard - Telegram Service

Servicio de backend en Python que actúa como puente entre dispositivos de alarma ESP32 (vía MQTT), usuarios (vía Telegram) y gestión de datos (Firebase).

## 📋 Descripción

Este servicio es el núcleo de la lógica de negocio del sistema de alarmas "Sentinel Guard". Se encarga de:
- Recibir eventos y telemetría de los dispositivos ESP32 a través de MQTT.
- Gestionar usuarios y permisos mediante Firebase.
- Enviar notificaciones y alertas en tiempo real a Telegram.
- Procesar comandos de usuario desde Telegram para controlar la alarma (armar, desarmar, pánico, etc.).
- Gestionar la lógica de disparo de "bengalas" (sistemas disuasorios) y horarios automáticos.

## 🚀 Características

- **Bridge MQTT-Telegram**: Comunicación bidireccional en tiempo real.
- **Gestión Multi-Tenant**: Soporte para múltiples dispositivos y usuarios.
- **Firebase Integration**: Almacenamiento de usuarios, chats autorizados y logs.
- **Scheduler**: Armado/Desarmado automático programable.
- **Lógica de Bengala**: Modos automático y manual (con pregunta de confirmación).
- **Notificaciones Inteligentes**: Alertas con botones interactivos (Inline Keyboards).
- **Monitorización**: Detección de dispositivos offline.

## 🛠️ Requisitos

- Python 3.8+
- Broker MQTT (HiveMQ, Mosquitto, etc.)
- Proyecto en Firebase (Realtime Database)
- Bot de Telegram (creado con @BotFather)

## 📦 Instalación

1. **Clonar el repositorio:**
   ```bash
   git clone <url-del-repo>
   cd telegram_service
   ```

2. **Crear entorno virtual:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Linux/Mac
   # o
   venv\Scripts\activate     # En Windows
   ```

3. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

## ⚙️ Configuración

### 1. Variables de Entorno
Crea un archivo `.env` en la raíz del proyecto (puedes basarte en el siguiente ejemplo) y configura tus credenciales:

```ini
# MQTT
MQTT_BROKER=broker.hivemq.com
MQTT_PORT=1883
MQTT_USER=tu_usuario
MQTT_PASS=tu_contraseña
MQTT_KEEPALIVE=60
MQTT_CLIENT_ID=alarma_telegram_bridge

# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_ADMIN_CHAT_ID=

# Configuración
DEVICE_ID=  # Dejar vacío para auto-detectar
DEBUG=true
LOG_FILE=alarm_service.log
```

### 2. Credenciales de Firebase
Necesitas un archivo `firebase_credentials.json` en la raíz del proyecto con las credenciales de servicio de tu proyecto Firebase.
*Este archivo debe ser descargado desde la consola de Firebase > Configuración del proyecto > Cuentas de servicio.*

**Nota:** Asegúrate de que tanto `.env` como `firebase_credentials.json` estén incluidos en tu `.gitignore` para no subir secretos al repositorio.

## ▶️ Ejecución

Para iniciar el servicio:

```bash
python main.py
```

El servicio se conectará al broker MQTT y comenzará a escuchar eventos y comandos de Telegram.

## 📚 Documentación

- **Comandos de Telegram:** Consulta [COMANDOS_TELEGRAM.md](COMANDOS_TELEGRAM.md) para una lista detallada de todos los comandos disponibles (`/start`, `/on`, `/off`, `/bengala`, etc.).
- **Arquitectura:** Detalles sobre la estructura del sistema en [ARQUITECTURA_PROPUESTA.txt](ARQUITECTURA_PROPUESTA.txt).

## 📄 Estructura del Proyecto

- `main.py`: Punto de entrada del servicio.
- `telegram_bot.py`: Lógica del bot y manejo de comandos.
- `mqtt_handler.py`: Gestión de conexión y mensajes MQTT.
- `firebase_manager.py`: Interacción con la base de datos.
- `scheduler.py`: Sistema de tareas programadas.
- `device_manager.py`: Gestión de estado de los dispositivos.

## 🤝 Contribución

1. Fork del repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit de tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request
