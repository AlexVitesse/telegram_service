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
- **Scheduler**: Armado/Desarmado automático programable, **un horario por dispositivo**.
- **Senti (IA + RAG)**: Responde preguntas sobre el sistema desde la base de conocimiento.
- **API HTTP**: Endpoint para que la app pregunte a Senti sin pasar por Telegram.
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

### Pruebas

Se ejecutan directamente, sin red ni LLM. **No son de pytest**: usan sus propias
fixtures y fallan si se lanzan con `pytest`.

```bash
python test_scheduler.py       # horarios por dispositivo
python test_knowledge_qa.py    # respuestas, escalado, timeouts
python test_api_server.py      # la puerta del endpoint HTTP
python test_comandos_app.py    # que frases salen como accion y sobre que equipo
python test_api_limites.py     # tope de uso
python test_chat_id_utils.py   # normalización de chat_id
```

### Despliegue en producción

El VPS no tiene `sudo` ni systemd: el procedimiento completo, con sus trampas,
está en **[DESPLIEGUE.md](DESPLIEGUE.md)**.

## 📚 Documentación

- **Comandos de Telegram:** [COMANDOS_TELEGRAM.md](COMANDOS_TELEGRAM.md) — lista detallada de todos los comandos (`/start`, `/id`, `/on`, `/off`, `/bengala`, etc.).
- **Despliegue en el VPS:** [DESPLIEGUE.md](DESPLIEGUE.md) — cómo se actualiza producción, ngrok y las fragilidades conocidas.
- **Endpoint HTTP:** [API_SENTI.md](API_SENTI.md) — contrato de la API, autenticación, topes y qué debe hacer la app.
- **Base de conocimiento:** `knowledge_base/` — los documentos con los que Senti contesta.
- **Historial:** los archivos `CHANGELOG_<fecha>.txt` de la raíz.

## 📄 Estructura del Proyecto

- `main.py`: Punto de entrada del servicio.
- `telegram_bot.py`: Lógica del bot y manejo de comandos.
- `mqtt_handler.py`: Gestión de conexión y mensajes MQTT.
- `firebase_manager.py`: Interacción con la base de datos.
- `scheduler.py`: Sistema de tareas programadas.
- `device_manager.py`: Gestión de estado de los dispositivos.
- `knowledge_qa.py`: Responde una pregunta con la base de conocimiento, sin Telegram de por medio. Lo usan el bot y la API.
- `api_server.py` / `api_limites.py`: Endpoint HTTP de Senti y su tope de uso.
- `rag_handler.py` / `ai_handler.py`: Recuperación sobre la base de conocimiento y clientes de LLM.

## 🤝 Contribución

1. Fork del repositorio
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit de tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request
