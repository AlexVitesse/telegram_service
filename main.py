#!/usr/bin/env python3
"""
Servicio Bridge MQTT-Telegram para Sistema de Alarma
====================================================
Nueva arquitectura: ESP32 publica eventos, Python maneja usuarios y notificaciones.
Usa Firebase para buscar chats autorizados por deviceId.

Funcionalidades:
- Recibe eventos del ESP32 via MQTT (dispositivos/eventos)
- Busca en Firebase los chats autorizados para el deviceId
- Envia notificaciones a los usuarios autorizados via Telegram
- Recibe comandos de Telegram, verifica permisos en Firebase
- Publica comandos al topic MQTT especifico del dispositivo

Uso:
    python main.py
"""
import asyncio
import logging
import os
import signal
import sys
import time as _time
from typing import Dict, Any

from config import config
from device_manager import DeviceManager
from mqtt_handler import MqttHandler
from telegram_bot import TelegramBot
from api_server import ApiSenti
from scheduler import scheduler
from fcm_handler import FCMHandler

from firebase_manager import firebase_manager
from mqtt_protocol import MqttEvent, MqttTelemetry, EventType
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Configurar logging con rotación automática
from logging.handlers import RotatingFileHandler

# Paths para comunicación con admin_bot
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(_BASE_DIR, ".service.pid")
PAUSE_FLAG = os.path.join(_BASE_DIR, ".pause_flag")

logging.basicConfig(
    level=logging.DEBUG if config.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(
            config.log_file,
            maxBytes=10 * 1024 * 1024,  # 10 MB por archivo
            backupCount=3,              # Mantener 3 archivos anteriores
            encoding='utf-8'
        )
    ]
)
logger = logging.getLogger(__name__)


class AlarmBridgeService:
    """Servicio principal que conecta MQTT con Telegram"""

    def __init__(self):
        self.device_manager = DeviceManager(firebase_manager)
        self.mqtt = MqttHandler(self.device_manager, firebase_manager)
        self.telegram = TelegramBot(self.device_manager, firebase_manager)
        self.fcm = FCMHandler(firebase_manager)  # Push notifications
        self.api = None
        self.running = False
        self._loop = None
        self.firebase_available = False
        self._connection_monitor_task = None
        self._alarm_reminder_task = None
        self._firebase_monitor_task = None
        # Marca por dispositivo de la última acción arm/disarm lanzada por horario.
        # Cuando el ESP32 responde con source="remote", lo reemplazamos por "schedule"
        # {device_id: ("arm"|"disarm", timestamp)}
        self._pending_scheduled: dict = {}

        # Registrar callbacks de MQTT
        self._setup_mqtt_callbacks()

        # Configurar scheduler
        self._setup_scheduler()

        # Conectar bot de Telegram con MQTT
        self.telegram.set_mqtt_handler(self.mqtt)

    def _setup_mqtt_callbacks(self):
        """Configura los callbacks para eventos MQTT"""
        self.mqtt.on_event(self._handle_event)
        self.mqtt.on_telemetry(self._handle_telemetry)
        self.mqtt.on_reconnect(self._handle_device_reconnect)

    def _setup_scheduler(self):
        """Configura el scheduler de horarios automaticos"""
        scheduler.on_arm(self._scheduled_arm)
        scheduler.on_disarm(self._scheduled_disarm)
        scheduler.on_reminder(self._scheduled_reminder)

    def _state_is_fresh(self, device_id: str, max_age: float = 90.0) -> bool:
        """
        ¿El estado armado/desarmado que tenemos de este dispositivo es reciente?
        Solo sirve para omitir comandos redundantes: ante la duda se manda el
        comando, perder un armado por un dato viejo es peor que duplicar un aviso.
        """
        # ponytail: ventana fija de 90s (telemetria llega cada ~20-30s).
        # Si cambia la cadencia de telemetria, derivarla de ahi.
        info = self.device_manager.get_device_info(device_id) if self.device_manager else None
        if not info:
            return False
        return (_time.time() - info.get("last_telemetry_time", 0)) < max_age

    async def _scheduled_arm(self, device_id: str):
        """Callback para activacion automatica programada"""
        # El ESP32 tiene su propio horario en NVS y puede haberse armado solo en
        # este mismo minuto: repetir el comando duplicaria el evento y el aviso.
        if self._state_is_fresh(device_id) and self.device_manager.is_armed(device_id):
            logger.info(f"Activacion automatica omitida: {device_id} ya está armado")
            return

        logger.info(f"Activacion automatica programada para {device_id}")

        # Marcar que esta acción es por horario para que el event handler
        # use source="schedule" en vez de "remote" y no duplique push.
        # El ESP32 responderá con SYSTEM_ARMED (source="remote").
        self._pending_scheduled[device_id] = ("arm", _time.time())
        self.mqtt.send_arm(device_id)

    async def _scheduled_disarm(self, device_id: str):
        """Callback para desactivacion automatica programada"""
        if self._state_is_fresh(device_id) and not self.device_manager.is_armed(device_id):
            logger.info(f"Desactivacion automatica omitida: {device_id} ya está desarmado")
            return

        logger.info(f"Desactivacion automatica programada para {device_id}")

        self._pending_scheduled[device_id] = ("disarm", _time.time())
        self.mqtt.send_disarm(device_id)

    async def _scheduled_reminder(self, device_id: str, action: str, minutes: int):
        """
        Callback para recordatorio de accion programada.
        Solo notifica a los chats privados del dispositivo dueño del horario.
        """
        cfg = scheduler.cfg(device_id)
        if action == "on":
            msg = (
                f"⏰ *RECORDATORIO*\n\n"
                f"🔒 El sistema se *activará* en {minutes} minutos\n"
                f"Hora: {cfg.format_on_time()}"
            )
        else:
            msg = (
                f"⏰ *RECORDATORIO*\n\n"
                f"🔓 El sistema se *desactivará* en {minutes} minutos\n"
                f"Hora: {cfg.format_off_time()}"
            )

        enviados = 0
        for chat_id in self._get_authorized_chats(device_id):
            # Solo chats privados (ID positivo); los grupos no reciben recordatorio
            if int(chat_id) < 0:
                continue
            if self._loop and self.telegram.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.telegram.send_message(chat_id, msg, "Markdown", has_keyboard=True),
                    self._loop
                )
                enviados += 1

        logger.info(f"⏰ [{device_id}] recordatorio enviado a {enviados} chat(s) privado(s)")

    def _handle_event(self, event: MqttEvent):
        """
        Maneja eventos recibidos del ESP32.
        Delega al TelegramBot para manejar lógica de bengala y notificaciones.
        También envía push notifications a la App.
        """
        logger.info(f"[{event.device_id}] Evento recibido: {event.event_type}")

        # Log adicional para eventos de alarma
        if event.event_type == EventType.ALARM_TRIGGERED:
            logger.info(f"🚨 [MAIN] ALARM_TRIGGERED de {event.device_id}")
            logger.info(f"🚨 [MAIN] loop={self._loop}, telegram_running={self.telegram.is_running() if self.telegram else False}")

        # Detectar si este evento arm/disarm fue originado por el scheduler
        # El ESP32 reporta source="remote" pero nosotros sabemos que fue por horario
        pending = self._pending_scheduled.get(event.device_id)
        if pending and (_time.time() - pending[1]) < 30:
            if (event.event_type == EventType.SYSTEM_ARMED and pending[0] == "arm") or \
               (event.event_type == EventType.SYSTEM_DISARMED and pending[0] == "disarm"):
                logger.info(f"⏰ Evento {event.event_type} detectado como acción de HORARIO (reemplazando source)")
                event.data["source"] = "schedule"
                del self._pending_scheduled[event.device_id]

        # Delegar al TelegramBot que tiene la lógica de confirmación de bengala
        if self._loop and self.telegram.is_running():
            asyncio.run_coroutine_threadsafe(
                self.telegram.handle_mqtt_event(event),
                self._loop
            )

        # Enviar push notification a la App
        self._send_push_for_event(event)

    def _handle_telemetry(self, telemetry: MqttTelemetry):
        """Maneja telemetria recibida del ESP32"""
        logger.debug(
            f"[{telemetry.device_id}] Telemetria: armed={telemetry.armed}, "
            f"rssi={telemetry.wifi_rssi}dBm, heap={telemetry.heap_free}"
        )

    def _handle_device_reconnect(self, device_id: str):
        """Maneja reconexión de un dispositivo"""
        logger.info(f"Dispositivo {device_id} reconectado - notificando usuarios")

        # Obtener ubicación desde Firebase (más confiable)
        location = firebase_manager.get_device_location(device_id) or "Desconocida"

        message = (
            "🟢 *DISPOSITIVO RECONECTADO*\n\n"
            f"📍 Ubicación: {location}\n"
            f"📱 ID: `{device_id}`\n\n"
            "El dispositivo ha restablecido la conexión."
        )
        self._schedule_telegram_broadcast_for_device(device_id, message)

    async def _monitor_device_connections(self):
        """Tarea que monitorea la conexión de dispositivos periódicamente"""
        # Esperar 60 segundos antes de empezar a monitorear
        # para dar tiempo a que los dispositivos envíen telemetría inicial
        await asyncio.sleep(60)

        while self.running:
            try:
                # Verificar dispositivos offline (90 segundos sin telemetría)
                offline_devices = self.device_manager.check_offline_devices(timeout_seconds=90)

                for device_data in offline_devices:
                    device_id = device_data.get("id", "desconocido")
                    # Obtener ubicación desde Firebase (más confiable)
                    location = firebase_manager.get_device_location(device_id) or "Desconocida"

                    logger.warning(f"Dispositivo {device_id} sin conexión - notificando usuarios")

                    message = (
                        "🔴 *DISPOSITIVO SIN CONEXIÓN*\n\n"
                        f"📍 Ubicación: {location}\n"
                        f"📱 ID: `{device_id}`\n\n"
                        "⚠️ El dispositivo ha dejado de responder.\n"
                        "Verifique la conexión a internet o alimentación."
                    )
                    self._schedule_telegram_broadcast_for_device(device_id, message)

                    # También enviar push notification
                    self._send_push_device_offline(device_id, location)

            except Exception as e:
                logger.error(f"Error monitoreando conexiones: {e}")

            # Verificar cada 30 segundos
            await asyncio.sleep(30)

    async def _send_alarm_reminders(self):
        """
        Tarea que envía recordatorios periódicos cuando hay alarmas activas.
        Solo aplica cuando is_alarming=True (alarma sonando), NO cuando se pierde conexión.
        Los recordatorios solo se envían a chats privados, NO a grupos.
        """
        # Esperar 30 segundos antes de empezar
        await asyncio.sleep(30)

        while self.running:
            try:
                # Obtener dispositivos que están en alarma y necesitan recordatorio (cada 60s)
                alarming_devices = self.device_manager.get_alarming_devices(reminder_interval_seconds=60)

                for device_data in alarming_devices:
                    device_id = device_data.get("id", "desconocido")

                    # Obtener ubicación desde Firebase (más confiable)
                    display_name = firebase_manager.get_device_location(device_id) or device_id

                    # Verificar el modo de bengala del dispositivo
                    bengala_mode = self.device_manager.get_bengala_mode(device_id)

                    logger.info(f"Enviando recordatorio de alarma activa para {device_id} (bengala_mode={bengala_mode})")

                    # Solo preguntar por bengala si está en modo pregunta (bengala_mode=1)
                    if bengala_mode == 1:
                        # Modo pregunta: incluir botones de bengala
                        message = (
                            "🚨 *ALARMA SIGUE ACTIVA*\n\n"
                            f"📍 *{display_name}*"
                        )
                        keyboard = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🔥 Disparar bengala", callback_data="bengala_confirm")
                            ],
                            [
                                InlineKeyboardButton("🔒 Dejar armado", callback_data="bengala_cancel"),
                                InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")
                            ]
                        ])
                    else:
                        # Modo automático (bengala_mode=0): solo botones de dejar armado y desactivar
                        message = (
                            "🚨 *ALARMA SIGUE ACTIVA*\n\n"
                            f"📍 *{display_name}*"
                        )
                        keyboard = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🔒 Dejar armado", callback_data="bengala_cancel"),
                                InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")
                            ]
                        ])

                    # Enviar solo a chats privados (no a grupos)
                    self._schedule_telegram_reminder_private_only(device_id, message, keyboard)

            except Exception as e:
                logger.error(f"Error enviando recordatorios de alarma: {e}")

            # Verificar cada 15 segundos (el interval real de 60s lo controla get_alarming_devices)
            await asyncio.sleep(15)

    async def _monitor_firebase_listener(self):
        """Tarea que monitorea la salud del listener de Firebase y reconecta si es necesario"""
        # Esperar 2 minutos antes de empezar a monitorear
        await asyncio.sleep(120)

        while self.running:
            try:
                if self.firebase_available:
                    # Verificar si el listener está saludable
                    if not firebase_manager.check_listener_health():
                        logger.warning("Listener de Firebase desconectado - reconectando...")
                        if firebase_manager.reconnect_listeners():
                            logger.info("Listener de Firebase reconectado exitosamente")
                        else:
                            logger.error("Fallo la reconexión del listener de Firebase")

            except Exception as e:
                logger.error(f"Error monitoreando listener de Firebase: {e}")

            # Verificar cada 60 segundos
            await asyncio.sleep(60)

    def _get_authorized_chats(self, device_id: str):
        """
        Obtiene los chats autorizados para un dispositivo desde Firebase.
        """
        if self.firebase_available:
            return firebase_manager.get_authorized_chats(device_id)
        logger.warning("Firebase no está disponible, no se pueden obtener los chats autorizados.")
        return []

    def _schedule_telegram_broadcast_for_device(self, device_id: str, message: str):
        """Envia un mensaje a todos los chats autorizados para un dispositivo"""
        if not self._loop or not self.telegram.is_running():
            return

        chat_ids = self._get_authorized_chats(device_id)

        for chat_id in chat_ids:
            asyncio.run_coroutine_threadsafe(
                self.telegram.send_message(
                    chat_id,
                    message,
                    "Markdown",
                    has_keyboard=True
                ),
                self._loop
            )

    def _schedule_telegram_broadcast_with_buttons(self, device_id: str, message: str, reply_markup, notification_message: str = None):
        """Envia un mensaje con botones inline a chats privados y solo notificación a grupos"""
        if not self._loop or not self.telegram.is_running():
            return

        chat_ids = self._get_authorized_chats(device_id)

        for chat_id in chat_ids:
            # Los grupos tienen chat_id negativo - solo enviar notificación sin botones
            is_group = int(chat_id) < 0

            if is_group:
                # A grupos: solo notificación sin botones de acción
                msg = notification_message if notification_message else message.replace("🔥 ¿Disparar bengala?", "")
                asyncio.run_coroutine_threadsafe(
                    self.telegram.send_message(chat_id, msg, "Markdown", has_keyboard=True),
                    self._loop
                )
            else:
                # A chats privados: mensaje completo con botones
                asyncio.run_coroutine_threadsafe(
                    self.telegram.send_message(chat_id, message, "Markdown", reply_markup=reply_markup),
                    self._loop
                )

    def _schedule_telegram_reminder_private_only(self, device_id: str, message: str, reply_markup):
        """Envia recordatorio solo a chats privados (no a grupos)"""
        if not self._loop or not self.telegram.is_running():
            return

        chat_ids = self._get_authorized_chats(device_id)

        for chat_id in chat_ids:
            # Solo enviar a chats privados (ID positivo)
            is_group = int(chat_id) < 0
            if not is_group:
                asyncio.run_coroutine_threadsafe(
                    # skip_anti_spam=True porque recordatorios de alarma son críticos
                    self.telegram.send_message(chat_id, message, "Markdown", reply_markup=reply_markup, skip_anti_spam=True),
                    self._loop
                )
                logger.debug(f"⚠️ Recordatorio de alarma enviado a {chat_id}")

    def _schedule_telegram_broadcast_private_only(self, device_id: str, message: str):
        """Envia un mensaje de texto solo a chats privados (no a grupos)"""
        if not self._loop or not self.telegram.is_running():
            logger.warning("⏰ No se puede enviar recordatorio: loop o telegram no disponible")
            return

        if not device_id:
            logger.warning("⏰ No se puede enviar recordatorio: device_id es None")
            return

        chat_ids = self._get_authorized_chats(device_id)
        logger.debug(f"⏰ Chats autorizados para {device_id}: {chat_ids}")

        if not chat_ids:
            logger.warning(f"⏰ No hay chats autorizados para dispositivo {device_id}")
            return

        private_count = 0
        for chat_id in chat_ids:
            # Solo enviar a chats privados (ID positivo)
            is_group = int(chat_id) < 0
            if not is_group:
                private_count += 1
                asyncio.run_coroutine_threadsafe(
                    self.telegram.send_message(
                        chat_id,
                        message,
                        "Markdown",
                        has_keyboard=True
                    ),
                    self._loop
                )

        logger.info(f"⏰ Recordatorio enviado a {private_count} chat(s) privado(s)")

    def _schedule_telegram_message(
        self,
        chat_id: str,
        message: str,
        parse_mode: str = "",
        has_keyboard: bool = False
    ):
        """Programa el envio de un mensaje de Telegram a un chat especifico"""
        if self._loop and self.telegram.is_running():
            asyncio.run_coroutine_threadsafe(
                self.telegram.send_message(
                    chat_id,
                    message,
                    parse_mode,
                    has_keyboard=has_keyboard
                ),
                self._loop
            )

    # ========================================
    # Push Notifications (FCM)
    # ========================================

    def _send_push_for_event(self, event: MqttEvent):
        """
        Envía push notification a la App basado en el tipo de evento.
        Se ejecuta en paralelo con las notificaciones de Telegram.
        """
        if not self.fcm.is_available():
            return

        try:
            device_id = event.device_id
            location = firebase_manager.get_device_location(device_id) or "Dispositivo"

            notification = None

            # Crear notificación según tipo de evento
            if event.event_type == EventType.ALARM_TRIGGERED:
                sensor_name = event.data.get("sensorName", "Sensor")
                notification = self.fcm.create_alarm_notification(
                    device_location=location,
                    sensor_name=sensor_name,
                    device_id=device_id
                )

            elif event.event_type == EventType.SYSTEM_ARMED:
                source = event.data.get("source", "Sistema")
                # Traducir sources del ESP32 a español
                source_traducido = {
                    "schedule": "Horario",
                    "remote": "Remoto",
                    "local": "Local",
                    "keypad": "Teclado",
                    "alexa": "Alexa"
                }.get(source, source)
                notification = self.fcm.create_armed_notification(
                    device_location=location,
                    source=source_traducido,
                    device_id=device_id
                )

            elif event.event_type == EventType.SYSTEM_DISARMED:
                source = event.data.get("source", "Sistema")
                # Traducir sources del ESP32 a español
                source_traducido = {
                    "schedule": "Horario",
                    "remote": "Remoto",
                    "local": "Local",
                    "keypad": "Teclado",
                    "alexa": "Alexa"
                }.get(source, source)
                notification = self.fcm.create_disarmed_notification(
                    device_location=location,
                    source=source_traducido,
                    device_id=device_id
                )

            elif event.event_type == EventType.BENGALA_ACTIVATED:
                notification = self.fcm.create_bengala_notification(
                    device_location=location,
                    device_id=device_id
                )

            elif event.event_type == EventType.SENSOR_OFFLINE:
                sensor_name = event.data.get("sensorName", "Sensor")
                notification = self.fcm.create_sensor_offline_notification(
                    sensor_name=sensor_name,
                    device_location=location,
                    device_id=device_id
                )

            elif event.event_type == EventType.MOVEMENT_DETECTED:
                sensor_name = event.data.get("sensorName", "Sensor")
                sensor_location = event.data.get("location", "")
                notification = self.fcm.create_movement_notification(
                    sensor_name=sensor_name,
                    sensor_location=sensor_location,
                    device_location=location,
                    device_id=device_id
                )

            elif event.event_type == EventType.DOOR_OPEN:
                sensor_name = event.data.get("sensorName", "Sensor")
                sensor_location = event.data.get("location", "")
                notification = self.fcm.create_door_notification(
                    sensor_name=sensor_name,
                    sensor_location=sensor_location,
                    device_location=location,
                    device_id=device_id
                )

            # Enviar notificación si se creó una
            if notification:
                sent = self.fcm.send_to_device_users(device_id, notification)
                if sent > 0:
                    logger.info(f"Push enviado a {sent} usuarios para evento {event.event_type}")

        except Exception as e:
            logger.error(f"Error enviando push notification: {e}")

    def _send_push_device_offline(self, device_id: str, location: str):
        """Envía push notification cuando un dispositivo se desconecta"""
        if not self.fcm.is_available():
            return

        try:
            notification = self.fcm.create_device_offline_notification(
                device_location=location,
                device_id=device_id
            )
            self.fcm.send_to_device_users(device_id, notification)
        except Exception as e:
            logger.error(f"Error enviando push de dispositivo offline: {e}")

    def _send_push_scheduled_arm(self):
        """Envía push notification cuando el sistema se arma por horario"""
        if not self.fcm.is_available():
            return

        try:
            # Obtener todos los dispositivos conocidos para enviar push
            all_device_ids = self.device_manager.get_all_device_ids() if self.device_manager else []

            if not all_device_ids and self.mqtt:
                all_device_ids = [self.mqtt.device_id] if self.mqtt.device_id else []

            for device_id in all_device_ids:
                location = firebase_manager.get_device_location(device_id) or "Sistema"
                notification = self.fcm.create_armed_notification(
                    device_location=location,
                    source="Horario",  # Traducido
                    device_id=device_id
                )
                sent = self.fcm.send_to_device_users(device_id, notification)
                if sent > 0:
                    logger.info(f"Push de armado por horario enviado a {sent} usuarios ({device_id})")

        except Exception as e:
            logger.error(f"Error enviando push de armado por horario: {e}")

    def _send_push_scheduled_disarm(self):
        """Envía push notification cuando el sistema se desarma por horario"""
        if not self.fcm.is_available():
            return

        try:
            # Obtener todos los dispositivos conocidos para enviar push
            all_device_ids = self.device_manager.get_all_device_ids() if self.device_manager else []

            if not all_device_ids and self.mqtt:
                all_device_ids = [self.mqtt.device_id] if self.mqtt.device_id else []

            for device_id in all_device_ids:
                location = firebase_manager.get_device_location(device_id) or "Sistema"
                notification = self.fcm.create_disarmed_notification(
                    device_location=location,
                    source="Horario",  # Traducido
                    device_id=device_id
                )
                sent = self.fcm.send_to_device_users(device_id, notification)
                if sent > 0:
                    logger.info(f"Push de desarmado por horario enviado a {sent} usuarios ({device_id})")

        except Exception as e:
            logger.error(f"Error enviando push de desarmado por horario: {e}")

    async def start_async(self):
        """Inicia el servicio de forma asincrona"""
        logger.info("=" * 50)
        logger.info("Iniciando Alarm Bridge Service")
        logger.info("=" * 50)

        # Inicializar Firebase
        self.firebase_available = firebase_manager.initialize()
        if self.firebase_available:
            logger.info("Firebase inicializado correctamente")
        else:
            logger.warning("Firebase no disponible, usando almacenamiento local")

        # Conectar a MQTT
        if not self.mqtt.connect():
            logger.error("No se pudo conectar a MQTT")
            return False

        self.mqtt.start()

        # Iniciar bot de Telegram
        await self.telegram.start()

        # Iniciar scheduler
        await scheduler.start()

        # Iniciar listener de comandos de la App en Firebase
        if self.firebase_available: # Only start if Firebase is connected
            firebase_manager.start_app_command_listener(self.mqtt)

        self.running = True
        self._loop = asyncio.get_event_loop()

        # Iniciar tarea de monitoreo de conexiones
        self._connection_monitor_task = asyncio.create_task(
            self._monitor_device_connections()
        )

        # Iniciar tarea de recordatorios de alarma activa
        self._alarm_reminder_task = asyncio.create_task(
            self._send_alarm_reminders()
        )

        # Iniciar tarea de monitoreo de listener de Firebase
        if self.firebase_available:
            self._firebase_monitor_task = asyncio.create_task(
                self._monitor_firebase_listener()
            )

        # Endpoint HTTP de Senti. En este mismo proceso a proposito: la
        # KnowledgeBase construye sus embeddings al cargar y no tiene sentido
        # pagarlos dos veces ni tener dos copias en memoria.
        if config.api.enabled:
            self.api = ApiSenti(self.telegram, firebase_manager)
            await self.api.start()

        # Escribir PID file para admin_bot
        try:
            with open(PID_FILE, "w") as f:
                f.write(str(os.getpid()))
            logger.info(f"PID {os.getpid()} escrito en {PID_FILE}")
        except Exception as e:
            logger.warning(f"No se pudo escribir PID file: {e}")

        logger.info("Servicio iniciado correctamente")
        logger.info(f"Broker MQTT: {config.mqtt.broker}:{config.mqtt.port}")
        logger.info(f"TLS: {'Habilitado' if config.mqtt.use_tls else 'Deshabilitado'}")
        logger.info(f"Device ID: {config.device_id or 'Auto-detectar'}")
        logger.info(f"Firebase: {'Conectado' if self.firebase_available else 'No disponible'}")
        logger.info(f"Bot Token: {config.telegram.bot_token[:20]}...")
        activos = sum(1 for c in scheduler.configs.values() if c.enabled)
        logger.info(f"Scheduler: {activos} horario(s) activo(s) de {len(scheduler.configs)} dispositivo(s)")

        return True

    async def stop_async(self):
        """Detiene el servicio de forma asincrona"""
        logger.info("Deteniendo servicio...")
        self.running = False

        if getattr(self, "api", None):
            await self.api.stop()

        # Cancelar tarea de monitoreo de conexiones
        if self._connection_monitor_task:
            self._connection_monitor_task.cancel()
            try:
                await self._connection_monitor_task
            except asyncio.CancelledError:
                pass

        # Cancelar tarea de recordatorios de alarma
        if self._alarm_reminder_task:
            self._alarm_reminder_task.cancel()
            try:
                await self._alarm_reminder_task
            except asyncio.CancelledError:
                pass

        # Cancelar tarea de monitoreo de Firebase
        if self._firebase_monitor_task:
            self._firebase_monitor_task.cancel()
            try:
                await self._firebase_monitor_task
            except asyncio.CancelledError:
                pass

        await scheduler.stop()
        await self.telegram.stop()
        self.mqtt.stop()

        # Limpiar PID file
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass

        logger.info("Servicio detenido")

    async def run_async(self):
        """Ejecuta el servicio principal"""
        if not await self.start_async():
            return

        try:
            # Mantener el servicio corriendo
            _paused = False
            while self.running:
                if os.path.exists(PAUSE_FLAG):
                    if not _paused:
                        logger.warning("Servicio PAUSADO por admin_bot (flag detectado)")
                        self.mqtt.stop()
                        _paused = True
                else:
                    if _paused:
                        logger.info("Servicio REANUDADO por admin_bot (flag eliminado)")
                        self.mqtt.connect()
                        self.mqtt.start()
                        _paused = False
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Servicio cancelado")
        finally:
            await self.stop_async()


async def main_async():
    """Punto de entrada asincrono"""
    service = AlarmBridgeService()

    # Manejar senales de shutdown
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Senal de terminacion recibida")
        service.running = False

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows no soporta add_signal_handler
            pass

    await service.run_async()


def main():
    """Punto de entrada principal"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Interrupcion de teclado")
    except Exception as e:
        logger.error(f"Error fatal: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
