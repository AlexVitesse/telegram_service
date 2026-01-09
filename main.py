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
import signal
import sys
from typing import Dict, Any

from config import config
from device_manager import DeviceManager
from mqtt_handler import MqttHandler
from telegram_bot import TelegramBot
from scheduler import scheduler

from firebase_manager import firebase_manager
from mqtt_protocol import MqttEvent, MqttTelemetry, EventType
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# Configurar logging
logging.basicConfig(
    level=logging.DEBUG if config.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.log_file, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


class AlarmBridgeService:
    """Servicio principal que conecta MQTT con Telegram"""

    def __init__(self):
        self.device_manager = DeviceManager(firebase_manager)
        self.mqtt = MqttHandler(self.device_manager, firebase_manager)
        self.telegram = TelegramBot(self.device_manager, firebase_manager)
        self.running = False
        self._loop = None
        self.firebase_available = False
        self._connection_monitor_task = None
        self._alarm_reminder_task = None

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

    async def _scheduled_arm(self):
        """Callback para activacion automatica programada"""
        logger.info("Activacion automatica programada")

        # Enviar comando al ESP32
        self.mqtt.send_arm()

        # Notificar a todos los usuarios
        msg = (
            "🔒 *ACTIVACION AUTOMATICA*\n\n"
            f"⏰ Hora programada: {scheduler.config.format_on_time()}\n"
            "El sistema se esta armando automaticamente."
        )
        self._schedule_telegram_broadcast_for_device(self.mqtt.device_id, msg)

    async def _scheduled_disarm(self):
        """Callback para desactivacion automatica programada"""
        logger.info("Desactivacion automatica programada")

        self.mqtt.send_disarm()

        msg = (
            "🔓 *DESACTIVACION AUTOMATICA*\n\n"
            f"⏰ Hora programada: {scheduler.config.format_off_time()}\n"
            "El sistema se ha desarmado automaticamente."
        )
        self._schedule_telegram_broadcast_for_device(self.mqtt.device_id, msg)

    async def _scheduled_reminder(self, action: str, minutes: int):
        """Callback para recordatorio de accion programada"""
        if action == "on":
            msg = (
                f"⏰ *RECORDATORIO*\n\n"
                f"🔒 El sistema se *activara* en {minutes} minutos\n"
                f"Hora: {scheduler.config.format_on_time()}"
            )
        else:
            msg = (
                f"⏰ *RECORDATORIO*\n\n"
                f"🔓 El sistema se *desactivara* en {minutes} minutos\n"
                f"Hora: {scheduler.config.format_off_time()}"
            )

        self._schedule_telegram_broadcast_for_device(self.mqtt.device_id, msg)

    def _handle_event(self, event: MqttEvent):
        """
        Maneja eventos recibidos del ESP32.
        Delega al TelegramBot para manejar lógica de bengala y notificaciones.
        """
        logger.info(f"[{event.device_id}] Evento: {event.event_type}")

        # Delegar al TelegramBot que tiene la lógica de confirmación de bengala
        if self._loop and self.telegram.is_running():
            asyncio.run_coroutine_threadsafe(
                self.telegram.handle_mqtt_event(event),
                self._loop
            )

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

            except Exception as e:
                logger.error(f"Error monitoreando conexiones: {e}")

            # Verificar cada 30 segundos
            await asyncio.sleep(30)

    async def _send_alarm_reminders(self):
        """
        Tarea que envía recordatorios periódicos cuando hay alarmas activas.
        Solo aplica cuando is_alarming=True (alarma sonando), NO cuando se pierde conexión.
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

                    # Mensaje base para grupos (siempre sin pregunta de bengala)
                    notification_message = (
                        "🚨 *ALARMA SIGUE ACTIVA*\n\n"
                        f"📍 *{display_name}*\n\n"
                        "Contactar con usuario."
                    )

                    # Solo preguntar por bengala si está en modo pregunta (bengala_mode=1)
                    if bengala_mode == 1:
                        # Modo pregunta: incluir pregunta de bengala
                        message = (
                            "🚨 *ALARMA SIGUE ACTIVA*\n\n"
                            f"📍 *{display_name}*\n\n"
                            "La sirena continúa sonando.\n"
                            "🔥 ¿Disparar bengala?"
                        )
                        keyboard = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🔥 Disparar bengala", callback_data="bengala_confirm"),
                                InlineKeyboardButton("🔒 Dejar Armado", callback_data="bengala_cancel")
                            ],
                            [
                                InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")
                            ]
                        ])
                        self._schedule_telegram_broadcast_with_buttons(device_id, message, keyboard, notification_message)
                    else:
                        # Modo automático (bengala_mode=0): solo recordatorio sin pregunta de bengala
                        message = (
                            "🚨 *ALARMA SIGUE ACTIVA*\n\n"
                            f"📍 *{display_name}*\n\n"
                            "La sirena continúa sonando."
                        )
                        keyboard = InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")
                            ]
                        ])
                        self._schedule_telegram_broadcast_with_buttons(device_id, message, keyboard, notification_message)

            except Exception as e:
                logger.error(f"Error enviando recordatorios de alarma: {e}")

            # Verificar cada 15 segundos (el interval real de 60s lo controla get_alarming_devices)
            await asyncio.sleep(15)

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

        logger.info("Servicio iniciado correctamente")
        logger.info(f"Broker MQTT: {config.mqtt.broker}:{config.mqtt.port}")
        logger.info(f"TLS: {'Habilitado' if config.mqtt.use_tls else 'Deshabilitado'}")
        logger.info(f"Device ID: {config.device_id or 'Auto-detectar'}")
        logger.info(f"Firebase: {'Conectado' if self.firebase_available else 'No disponible'}")
        logger.info(f"Bot Token: {config.telegram.bot_token[:20]}...")
        logger.info(f"Scheduler: {'Habilitado' if scheduler.is_enabled() else 'Deshabilitado'}")

        return True

    async def stop_async(self):
        """Detiene el servicio de forma asincrona"""
        logger.info("Deteniendo servicio...")
        self.running = False

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

        await scheduler.stop()
        await self.telegram.stop()
        self.mqtt.stop()

        logger.info("Servicio detenido")

    async def run_async(self):
        """Ejecuta el servicio principal"""
        if not await self.start_async():
            return

        try:
            # Mantener el servicio corriendo
            while self.running:
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
