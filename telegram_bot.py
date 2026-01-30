"""
Bot de Telegram para el Sistema de Alarma
==========================================
Implementa la interfaz de usuario via Telegram.
Nueva arquitectura: Python maneja usuarios y notificaciones.
Usa Firebase para verificar permisos antes de enviar comandos.
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable, TYPE_CHECKING
from functools import wraps
import firebase_admin
import telegram
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

from config import config
from scheduler import scheduler
from mqtt_protocol import MqttEvent, EventType
from device_manager import DeviceManager

if TYPE_CHECKING: # ADD THIS BLOCK
    from firebase_manager import FirebaseManager

logger = logging.getLogger(__name__)


@dataclass
class BengalaConfirmation:
    """Estado de confirmación de bengala pendiente para un dispositivo."""
    device_id: str
    chat_ids: List[str]  # Lista de chats a los que se envió la pregunta
    sensor_name: str
    sensor_location: str
    timestamp: float
    reminder_count: int = 0
    reminder_task: Optional[asyncio.Task] = field(default=None, repr=False)

    def is_expired(self, timeout_seconds: int = 120) -> bool:
        """Verifica si la confirmación ha expirado (default 2 minutos)."""
        return (time.time() - self.timestamp) >= timeout_seconds


def require_auth(func):
    """Decorador que requiere autorizacion para ejecutar el comando.
    Bloquea comandos desde grupos (solo reciben notificaciones)."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        user = update.effective_user

        # Verificar si es un grupo (solo notificaciones, no comandos)
        if self.firebase_manager.is_group_chat(chat_id):
            logger.info(f"Comando ignorado desde grupo {chat_id} - solo notificaciones permitidas")
            await update.message.reply_text(
                "ℹ️ *Este grupo solo recibe notificaciones*\n\n"
                "Los comandos deben ejecutarse en el chat privado con el bot.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not self.firebase_manager.get_authorized_devices(chat_id):
            logger.warning(f"Acceso denegado a {user.first_name} ({chat_id}) - sin dispositivos autorizados.")
            await update.message.reply_text(
                "🚫 *Acceso no autorizado*\n\n"
                "No tienes permiso para usar este comando o no tienes dispositivos asignados.\n"
                "Contacta a un administrador para que te dé acceso.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        return await func(self, update, context)
    return wrapper


def require_admin(func):
    """Decorador que requiere ser administrador.
    Bloquea comandos desde grupos (solo reciben notificaciones)."""
    @wraps(func)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = str(update.effective_chat.id)
        user = update.effective_user

        # Verificar si es un grupo (solo notificaciones, no comandos)
        if self.firebase_manager.is_group_chat(chat_id):
            logger.info(f"Comando admin ignorado desde grupo {chat_id}")
            await update.message.reply_text(
                "ℹ️ *Este grupo solo recibe notificaciones*\n\n"
                "Los comandos deben ejecutarse en el chat privado con el bot.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if not self.firebase_manager.is_user_admin(chat_id):
            logger.warning(f"Acceso admin denegado a {user.first_name} ({chat_id})")
            await update.message.reply_text(
                "🚫 *Solo administradores*\n\n"
                "Este comando requiere permisos de administrador.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        return await func(self, update, context)
    return wrapper


def command_cooldown(cooldown_seconds: int = 5, use_lock: bool = False):
    """
    Decorador factory para añadir un cooldown a un comando.
    Evita que el mismo usuario ejecute el mismo comando repetidamente.

    Args:
        cooldown_seconds: Tiempo mínimo entre ejecuciones del mismo comando
        use_lock: Si True, usa un lock para evitar ejecuciones concurrentes
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            chat_id = str(update.effective_chat.id)
            command_name = func.__name__
            lock_key = f"{chat_id}:{command_name}"

            # Verificar cooldown ANTES de adquirir el lock
            last_used_time = self._command_cooldowns.get(lock_key)
            if last_used_time:
                elapsed = time.time() - last_used_time
                if elapsed < cooldown_seconds:
                    remaining = int(cooldown_seconds - elapsed) + 1
                    logger.warning(
                        f"Comando '{command_name}' de {chat_id} en cooldown. "
                        f"({int(elapsed)}s desde último uso). Ignorando."
                    )
                    if update.callback_query:
                        try:
                            await update.callback_query.answer(
                                f"Comando en cooldown. Intenta en {remaining}s.",
                                show_alert=False
                            )
                        except Exception as e:
                            logger.debug(f"Error al responder a callback query en cooldown: {e}")
                    elif update.message:
                        try:
                            await update.message.reply_text(
                                f"⏳ Comando en ejecución. Espera {remaining}s antes de volver a usarlo."
                            )
                        except Exception as e:
                            logger.debug(f"Error al responder mensaje en cooldown: {e}")
                    return None

            # Si use_lock está habilitado, usar un lock para evitar ejecuciones concurrentes
            if use_lock:
                # Crear lock si no existe
                if lock_key not in self._command_locks:
                    self._command_locks[lock_key] = asyncio.Lock()

                lock = self._command_locks[lock_key]

                # Verificar si el lock ya está tomado (comando en ejecución)
                if lock.locked():
                    logger.warning(
                        f"Comando '{command_name}' de {chat_id} ya en ejecución. Ignorando."
                    )
                    if update.message:
                        try:
                            await update.message.reply_text(
                                "⏳ Este comando ya está en ejecución. Espera a que termine."
                            )
                        except Exception as e:
                            logger.debug(f"Error al responder mensaje de lock: {e}")
                    return None

                async with lock:
                    self._command_cooldowns[lock_key] = time.time()
                    return await func(self, update, context, *args, **kwargs)
            else:
                self._command_cooldowns[lock_key] = time.time()
                return await func(self, update, context, *args, **kwargs)
        return wrapper
    return decorator




class TelegramBot:
    """Bot de Telegram para control del sistema de alarma"""

    # Teclado estandar
    STANDARD_KEYBOARD = [
        ["/on", "/off"],
        ["/disparo"],
        ["/status"],
        ["/bengala"]
    ]

    def __init__(self, device_manager: DeviceManager, firebase_manager: 'FirebaseManager'):
        self.device_manager = device_manager
        self.firebase_manager = firebase_manager # STORE INSTANCE
        self.application: Optional[Application] = None
        self.mqtt_handler = None  # Se inyectara desde main.py
        self._running = False
        self._sent_message_history: Dict[str, float] = {}
        self._command_cooldowns: Dict[str, float] = {}
        # Locks para evitar ejecuciones concurrentes del mismo comando por usuario
        self._command_locks: Dict[str, asyncio.Lock] = {}

        # Estado de confirmaciones de bengala pendientes (por device_id)
        self._bengala_confirmations: Dict[str, BengalaConfirmation] = {}

        # Estado de notificaciones de alarma activa (por device_id) - para modo auto/deshabilitado
        self._alarm_notifications: Dict[str, dict] = {}

        # Intervalo de recordatorios (segundos)
        self.REMINDER_INTERVAL_PRIVATE = 60   # 1 minuto para chat privado
        self.REMINDER_INTERVAL_GROUP = 300    # 5 minutos para grupos
        # Timeout de confirmación de bengala (segundos)
        self.BENGALA_CONFIRMATION_TIMEOUT = 120

        # Dispositivo seleccionado para horarios (por chat_id)
        self._horarios_selected_device: Dict[str, str] = {}  # chat_id -> device_id o "all"

    def _is_user_authorized(self, chat_id: str) -> bool:
        """
        Verifica si un usuario esta autorizado.
        """
        # Verificar si tiene dispositivos autorizados en Firebase
        devices = self.firebase_manager.get_authorized_devices(chat_id) # MODIFIED LINE
        return len(devices) > 0

    def _is_user_admin(self, chat_id: str) -> bool:
        """
        Verifica si un usuario es admin.
        """
        return self.firebase_manager.is_user_admin(chat_id) # MODIFIED LINE

    def _get_authorized_devices(self, chat_id: str) -> List[str]:
        """Obtiene la lista de dispositivos autorizados para un usuario"""
        if self.firebase_manager.is_available(): # MODIFIED LINE
            return self.firebase_manager.get_authorized_devices(chat_id) # MODIFIED LINE
        return []

    async def initialize(self):
        """Inicializa el bot de Telegram"""
        logger.info("Inicializando bot de Telegram...")

        self.application = (
            Application.builder()
            .token(config.telegram.bot_token)
            .build()
        )

        # Registrar handlers de comandos
        self._register_handlers()

        logger.info("Bot de Telegram inicializado")

    def _register_handlers(self):
        """Registra los handlers de comandos"""
        app = self.application

        # Comandos basicos
        app.add_handler(CommandHandler("start", self._cmd_start))
        app.add_handler(CommandHandler("help", self._cmd_help))
        app.add_handler(CommandHandler("status", self._cmd_status))

        # Comandos de seguridad
        app.add_handler(CommandHandler("on", self._cmd_on))
        app.add_handler(CommandHandler("off", self._cmd_off))
        app.add_handler(CommandHandler("disparo", self._cmd_disparo))

        # Bengala
        app.add_handler(CommandHandler("bengala", self._cmd_bengala))
        app.add_handler(CommandHandler("auto", self._cmd_auto))
        app.add_handler(CommandHandler("preguntar", self._cmd_preguntar))
        app.add_handler(CommandHandler("deshabilitar", self._cmd_deshabilitar))

        # Admin
        app.add_handler(CommandHandler("permisos", self._cmd_permisos))
        app.add_handler(CommandHandler("horarios", self._cmd_horarios))
        app.add_handler(CommandHandler("sensors", self._cmd_sensors))
        app.add_handler(CommandHandler("adduser", self._cmd_adduser))
        app.add_handler(CommandHandler("desvincular", self._cmd_desvincular))

        # Callbacks de botones inline
        app.add_handler(CallbackQueryHandler(self._handle_callback))

        # Handler para comandos join_XXX y approve_XXX
        app.add_handler(MessageHandler(
            filters.Regex(r'^/join_.*$'),
            self._cmd_join
        ))
        app.add_handler(MessageHandler(
            filters.Regex(r'^/approve_.*$'),
            self._cmd_approve
        ))

        # Handler para mensajes de texto generales (captura todo lo demas)
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_unknown_message
        ))

        # Handler para comandos no reconocidos
        app.add_handler(MessageHandler(
            filters.COMMAND,
            self._handle_unknown_command
        ))

        logger.debug("Handlers de comandos registrados")

    def set_mqtt_handler(self, mqtt_handler):
        """Inyecta el handler de MQTT"""
        self.mqtt_handler = mqtt_handler

    def _get_keyboard(self) -> ReplyKeyboardMarkup:
        """Retorna el teclado estandar"""
        return ReplyKeyboardMarkup(
            self.STANDARD_KEYBOARD,
            resize_keyboard=True,
            one_time_keyboard=False
        )

    # ========================================
    # Helpers de Control de Concurrencia
    # ========================================
    
    async def _acquire_command_lock(self, chat_id: str, command_name: str, cooldown_seconds: int = 5) -> Optional[asyncio.Lock]:
        """
        Intenta adquirir un lock para un comando y verifica el cooldown.
        Retorna el Lock adquirido si se puede proceder, o None si se debe ignorar.
        """
        key = f"{chat_id}:{command_name}"
        now = time.time()
        
        # 1. Verificar Cooldown (Tiempo)
        last_time = self._command_cooldowns.get(key, 0)
        if now - last_time < cooldown_seconds:
            # Ignorar silenciosamente si está en cooldown
            return None

        # 2. Verificar Lock (Ejecución en curso)
        if key not in self._command_locks:
            self._command_locks[key] = asyncio.Lock()
        
        lock = self._command_locks[key]
        
        if lock.locked():
            # Ignorar silenciosamente si ya se está ejecutando
            return None
            
        await lock.acquire()
        
        # Actualizar timestamp solo si logramos adquirir el lock
        self._command_cooldowns[key] = now
        return lock

    # ========================================
    # Handlers de comandos
    # ========================================

    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /start"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        logger.info(f"/start de {user.first_name} ({chat_id})")

        # --- MODIFIED LOGIC ---
        # Verificar si el usuario tiene dispositivos autorizados
        authorized_devices = self.firebase_manager.get_authorized_devices(chat_id)
        if authorized_devices:
            welcome = (
                f"👋 *¡Hola de nuevo, {user.first_name}!*\n\n"
                f"📱 Tienes acceso a {len(authorized_devices)} dispositivo(s).\n"
                "📋 Usa /help para ver tus comandos."
            )
            await update.message.reply_text(
                welcome,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self._get_keyboard()
            )
            return
        # --- END OF MODIFIED LOGIC ---

        # Verificar si es el primer usuario (no hay admins configurados)
        if not self.firebase_manager.has_any_admin():
            # Configurar como primer admin
            device_id = self.mqtt_handler.device_id if self.mqtt_handler else "ALARMA_DEFAULT"
            self.firebase_manager.setup_initial_admin(chat_id, user.first_name, device_id)

            welcome = (
                "🎉 *¡Bienvenido al Sistema de Seguridad!*\n\n"
                f"✅ Has sido registrado como *Administrador Principal*.\n\n"
                f"🆔 Tu ID: `{chat_id}`\n\n"
                "📋 Usa /help para ver los comandos."
            )
            await update.message.reply_text(
                welcome,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self._get_keyboard()
            )
            return

        # No autorizado
        deny_msg = (
            "🚫 *Usuario no registrado*\n\n"
            "No tienes autorizacion para usar este sistema.\n\n"
            f"🆔 Tu ID: `{chat_id}`\n\n"
            "📱 Para solicitar acceso, pidele al administrador "
            "que use /adduser y te envie el codigo de invitacion."
        )
        await update.message.reply_text(deny_msg, parse_mode=ParseMode.MARKDOWN)

    @require_auth
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /help"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        help_text = "📚 *GUÍA DE COMANDOS*\n\n"
        help_text += "🔐 *Seguridad:*\n"
        help_text += "`/on` - Armar sistema\n"
        help_text += "`/off` - Desarmar sistema\n"
        help_text += "`/status` - Ver estado\n"
        help_text += "`/disparo` - Activar alarma manual\n\n"
        help_text += "🔥 *Bengala:*\n"
        help_text += "`/bengala` - Menú de configuración\n"
        help_text += "`/auto` - Modo automático (sin pregunta)\n"
        help_text += "`/preguntar` - Modo con pregunta\n"
        help_text += "`/deshabilitar` - Desactivar bengala\n\n"
        help_text += "🔗 *Dispositivos:*\n"
        help_text += "`/desvincular` - Desvincular un dispositivo\n\n"
        help_text += "⏰ *Horarios:*\n"
        help_text += "`/horarios` - Ver/configurar programación por dispositivo\n"
        help_text += "`/horarios activar HH:MM` - Hora de armado\n"
        help_text += "`/horarios desactivar HH:MM` - Hora de desarmado\n"
        help_text += "`/horarios dias [L,M,X,J,V|todos|semana|finde]`\n"
        help_text += "`/horarios cambiar` - Cambiar dispositivo seleccionado\n\n"

        if self._is_user_admin(chat_id):
            help_text += "⚙️ *Admin:*\n"
            help_text += "`/permisos` - Gestionar usuarios\n"
            help_text += "`/sensors` - Ver sensores\n"
            help_text += "`/adduser` - Agregar usuario\n"

        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self._get_keyboard()
        )

    @require_auth
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /status. Silencioso en flood."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        
        # Intentar adquirir lock y verificar cooldown (5 segundos)
        lock = await self._acquire_command_lock(chat_id, "status", cooldown_seconds=5)
        if not lock:
            return # Ignorar silenciosamente

        try:
            logger.info(f"/status de {user.first_name}")

            if not self.mqtt_handler:
                await update.message.reply_text("❌ Error: El servicio no está conectado al sistema.")
                return

            devices = self.firebase_manager.get_authorized_devices(chat_id)
            if not devices:
                await update.message.reply_text("No tienes dispositivos autorizados.")
                return

            # Si solo hay 1 dispositivo, consultar directamente
            if len(devices) == 1:
                await self._get_device_status(update, devices)
                return

            # Si hay más de 1, mostrar menú de selección
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"📊 {location}", callback_data=f"status_{device_id}")])

            # Agregar opción para consultar todos
            buttons.append([InlineKeyboardButton("📊 Ver TODOS", callback_data="status_all")])

            keyboard = InlineKeyboardMarkup(buttons)

            await update.message.reply_text(
                "📊 *Selecciona el dispositivo a consultar:*\n\n"
                f"Tienes {len(devices)} dispositivo(s) disponibles.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        finally:
            lock.release()

    async def _get_device_status(self, update_or_query, devices: List[str]):
        """Consulta el estado de uno o varios dispositivos"""
        # Determinar si es un Update o CallbackQuery
        # CallbackQuery tiene 'data', Update tiene 'effective_chat'
        is_callback = hasattr(update_or_query, 'data')

        if is_callback:
            reply_func = update_or_query.edit_message_text
            chat_id = str(update_or_query.message.chat_id)
        else:
            reply_func = update_or_query.message.reply_text
            chat_id = str(update_or_query.effective_chat.id)

        device_count = len(devices)
        device_text = "1 dispositivo" if device_count == 1 else f"{device_count} dispositivos"

        await reply_func(
            f"⏳ Solicitando estado de {device_text}... Esperando respuestas (7s).",
            parse_mode=ParseMode.MARKDOWN
        )

        # Guardar el tiempo antes de enviar las solicitudes
        request_time = time.time()

        # Enviar solicitud de estado a los dispositivos
        for device_id in devices:
            self.mqtt_handler.send_get_status(device_id=device_id)

        # Esperar un tiempo para las respuestas
        await asyncio.sleep(5)

        # Revisar las respuestas - buscar telemetría por ID original o truncado
        response_count = 0
        for device_id in devices:
            device_location = self.firebase_manager.get_device_location(device_id) or device_id
            truncated_id = self.mqtt_handler.truncate_device_id(device_id)

            # Buscar telemetría por ID completo o truncado
            telemetry = self.mqtt_handler.get_device_telemetry(device_id)
            telemetry_time = self.mqtt_handler.last_telemetry_time.get(device_id, 0)

            if not telemetry and truncated_id != device_id:
                telemetry = self.mqtt_handler.get_device_telemetry(truncated_id)
                telemetry_time = self.mqtt_handler.last_telemetry_time.get(truncated_id, 0)

            # Verificar que la telemetría sea RECIENTE (posterior al request)
            is_fresh_telemetry = telemetry and telemetry_time > request_time

            if is_fresh_telemetry:
                # Usar bengala_enabled de DeviceManager que tiene el valor sincronizado
                # (el valor en telemetry puede ser el default False si ESP32 no lo envía)
                bengala_enabled = self.device_manager.is_bengala_enabled(truncated_id)
                bengala_mode = self.device_manager.get_bengala_mode(truncated_id)

                # Mostrar estado de bengala según modo
                if bengala_mode == 0:
                    bengala_status = "AUTOMÁTICA"
                elif bengala_enabled:
                    bengala_status = "HABILITADA (pregunta)"
                else:
                    bengala_status = "DESHABILITADA"

                status_text = (
                    f"✅ *{device_location}* - EN LÍNEA\n"
                    f"   - Sistema: {'ARMADO' if telemetry.armed else 'DESARMADO'}\n"
                    f"   - Bengala: {bengala_status}\n"
                    f"   - WiFi: {telemetry.wifi_rssi} dBm"
                )
                await self.send_message(chat_id, status_text, "Markdown")
                response_count += 1
            else:
                await self.send_message(chat_id, f"❌ *{device_location}* - Sin respuesta", "Markdown")

        if response_count == 0:
            await self.send_message(chat_id, "🤷‍♂️ Ningún dispositivo respondió a la solicitud de estado.")

    @require_auth
    async def _cmd_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /on - Armar sistema. Silencioso en flood."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        
        lock = await self._acquire_command_lock(chat_id, "on", cooldown_seconds=5)
        if not lock:
            return

        try:
            logger.info(f"/on de {user.first_name}")

            if not self.mqtt_handler:
                await update.message.reply_text("❌ Error: El servicio no está conectado al sistema.")
                return

            devices = self.firebase_manager.get_authorized_devices(chat_id)
            if not devices:
                await update.message.reply_text("No tienes dispositivos autorizados.")
                return

            # Si solo hay 1 dispositivo, armar directamente
            if len(devices) == 1:
                await self._arm_devices(update, devices)
                return

            # Si hay más de 1, mostrar menú de selección
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"🔒 {location}", callback_data=f"arm_{device_id}")])

            # Agregar opción para armar todos
            buttons.append([InlineKeyboardButton("🔒 Armar TODOS", callback_data="arm_all")])

            keyboard = InlineKeyboardMarkup(buttons)

            await update.message.reply_text(
                "🔒 *Selecciona el dispositivo a armar:*\n\n"
                f"Tienes {len(devices)} dispositivo(s) disponibles.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        finally:
            lock.release()

    async def _arm_devices(self, update_or_query, devices: List[str], single_device: bool = False):
        """Arma uno o varios dispositivos y espera confirmación"""
        # Determinar si es un Update o CallbackQuery
        # CallbackQuery tiene 'data', Update tiene 'effective_chat'
        is_callback = hasattr(update_or_query, 'data')

        if is_callback:
            reply_func = update_or_query.edit_message_text
            chat_id = str(update_or_query.message.chat_id)
        else:
            reply_func = update_or_query.message.reply_text
            chat_id = str(update_or_query.effective_chat.id)

        device_count = len(devices)
        device_text = "1 dispositivo" if device_count == 1 else f"{device_count} dispositivos"

        await reply_func(
            f"🔒 Enviando comando para *armar* {device_text}... Esperando confirmación (7s).",
            parse_mode=ParseMode.MARKDOWN
        )

        for device_id in devices:
            self.mqtt_handler.send_arm(device_id=device_id)

        await asyncio.sleep(5)

        # Verificar confirmación por ID original, truncado, o resuelto (completo)
        armed_count = 0
        for device_id in devices:
            truncated_id = self.mqtt_handler.truncate_device_id(device_id)
            resolved_id = self.mqtt_handler.resolve_full_device_id(device_id)
            if (self.device_manager.is_armed(device_id) or
                self.device_manager.is_armed(truncated_id) or
                self.device_manager.is_armed(resolved_id)):
                armed_count += 1

        if armed_count > 0:
            await self.send_message(chat_id, f"✅ {armed_count}/{device_count} dispositivo(s) armado(s) correctamente.", "Markdown")
        else:
            await self.send_message(chat_id, "❌ Ningún dispositivo confirmó el armado. Puede que estén offline.", "Markdown")

    async def _disarm_devices(self, update_or_query, devices: List[str], single_device: bool = False):
        """Desarma uno o varios dispositivos y espera confirmación"""
        # Determinar si es un Update o CallbackQuery
        is_callback = hasattr(update_or_query, 'data')

        if is_callback:
            reply_func = update_or_query.edit_message_text
            chat_id = str(update_or_query.message.chat_id)
        else:
            reply_func = update_or_query.message.reply_text
            chat_id = str(update_or_query.effective_chat.id)

        device_count = len(devices)
        device_text = "1 dispositivo" if device_count == 1 else f"{device_count} dispositivos"

        await reply_func(
            f"🔓 Enviando comando para *desarmar* {device_text}... Esperando confirmación (7s).",
            parse_mode=ParseMode.MARKDOWN
        )

        for device_id in devices:
            self.mqtt_handler.send_disarm(device_id=device_id)

        await asyncio.sleep(5)

        # Verificar confirmación por ID original, truncado, o resuelto (completo)
        disarmed_count = 0
        for device_id in devices:
            truncated_id = self.mqtt_handler.truncate_device_id(device_id)
            resolved_id = self.mqtt_handler.resolve_full_device_id(device_id)
            if (not self.device_manager.is_armed(device_id) and
                not self.device_manager.is_armed(truncated_id) and
                not self.device_manager.is_armed(resolved_id)):
                disarmed_count += 1

        if disarmed_count > 0:
            await self.send_message(chat_id, f"✅ {disarmed_count}/{device_count} dispositivo(s) desarmado(s) correctamente.", "Markdown")
        else:
            await self.send_message(chat_id, "❌ Ningún dispositivo confirmó el desarmado. Puede que estén offline.", "Markdown")

    @require_auth
    async def _cmd_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /off - Desarmar sistema. Silencioso en flood."""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        
        lock = await self._acquire_command_lock(chat_id, "off", cooldown_seconds=5)
        if not lock:
            return

        try:
            logger.info(f"/off de {user.first_name}")

            if not self.mqtt_handler:
                await update.message.reply_text("❌ Error: El servicio no está conectado al sistema.")
                return

            devices = self.firebase_manager.get_authorized_devices(chat_id)
            if not devices:
                await update.message.reply_text("No tienes dispositivos autorizados.")
                return

            # Si solo hay 1 dispositivo, desarmar directamente
            if len(devices) == 1:
                await self._disarm_devices(update, devices)
                return

            # Si hay más de 1, mostrar menú de selección
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"🔓 {location}", callback_data=f"disarm_{device_id}")])

            # Agregar opción para desarmar todos
            buttons.append([InlineKeyboardButton("🔓 Desarmar TODOS", callback_data="disarm_all")])

            keyboard = InlineKeyboardMarkup(buttons)

            await update.message.reply_text(
                "🔓 *Selecciona el dispositivo a desarmar:*\n\n"
                f"Tienes {len(devices)} dispositivo(s) disponibles.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        finally:
            lock.release()

    @require_auth
    @command_cooldown(cooldown_seconds=8, use_lock=True)
    async def _cmd_disparo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /disparo - Activar alarma manualmente"""
        user = update.effective_user
        logger.info(f"/disparo de {user.first_name}")

        # Mostrar confirmacion
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirmar", callback_data="trigger_confirm"),
                InlineKeyboardButton("❌ Cancelar", callback_data="trigger_cancel")
            ]
        ])

        await update.message.reply_text(
            "⚠️ *¿Activar alarma manualmente?*\n\n"
            "Esto activara la sirena inmediatamente.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    @require_auth
    async def _cmd_bengala(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /bengala - Menú de configuración de bengala"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/bengala de {user.first_name}")

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos autorizados.")
            return

        # Si hay múltiples dispositivos, mostrar selector primero
        if len(devices) > 1:
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                # Verificar primero si está habilitada, luego el modo
                is_enabled = self.device_manager.is_bengala_enabled(device_id) if self.device_manager else True
                if not is_enabled:
                    mode_icon = "❌"
                else:
                    current_mode = self.device_manager.get_bengala_mode(device_id) if self.device_manager else 1
                    mode_icon = "🤖" if current_mode == 0 else "❓"
                buttons.append([InlineKeyboardButton(f"🔥 {location} ({mode_icon})", callback_data=f"bengala_select_{device_id}")])

            # Opción para aplicar a todos
            buttons.append([InlineKeyboardButton("🔥 Configurar TODOS", callback_data="bengala_select_all")])

            keyboard = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(
                "🔥 *Configurar Bengala*\n\n"
                "Selecciona el dispositivo a configurar:\n"
                "(🤖 = Auto, ❓ = Pregunta, ❌ = Deshabilitado)",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            # Un solo dispositivo: mostrar opciones directamente
            await self._show_bengala_options(update.message, devices[0])

    async def _show_bengala_options(self, message_or_query, device_id: str, is_all: bool = False):
        """Muestra las opciones de modo bengala para un dispositivo o todos"""
        # Verificar primero si está habilitada
        is_enabled = self.device_manager.is_bengala_enabled(device_id) if self.device_manager else True
        if not is_enabled:
            mode_text = "❌ Deshabilitado"
        else:
            current_mode = self.device_manager.get_bengala_mode(device_id) if self.device_manager else 1
            mode_text = "🤖 Automático" if current_mode == 0 else "❓ Con pregunta"

        # Sufijo para el callback: device_id específico o "all"
        suffix = "all" if is_all else device_id
        location = "TODOS los dispositivos" if is_all else (self.firebase_manager.get_device_location(device_id) or device_id)

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🤖 Modo Auto", callback_data=f"bengala_mode_auto_{suffix}"),
                InlineKeyboardButton("❓ Modo Pregunta", callback_data=f"bengala_mode_ask_{suffix}")
            ],
            [
                InlineKeyboardButton("❌ Deshabilitar", callback_data=f"bengala_off_{suffix}")
            ]
        ])

        text = (
            f"🔥 *Configurar Bengala*\n"
            f"📍 {location}\n\n"
            f"Modo actual: {mode_text}\n\n"
            f"*Modos disponibles:*\n"
            f"• 🤖 *Automático*: Dispara bengala automáticamente\n"
            f"• ❓ *Con pregunta*: Pregunta antes de disparar\n"
            f"• ❌ *Deshabilitar*: No dispara bengala"
        )

        # Puede ser un Message (desde comando) o CallbackQuery (desde botón)
        if hasattr(message_or_query, 'reply_text'):
            await message_or_query.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        else:
            await message_or_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    @require_auth
    async def _cmd_auto(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /auto - Configurar bengala en modo automático"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/auto de {user.first_name}")

        if not self.mqtt_handler:
            await update.message.reply_text("❌ Error: Sistema no conectado")
            return

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos autorizados.")
            return

        # Si hay múltiples dispositivos, mostrar selector
        if len(devices) > 1:
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"🤖 {location}", callback_data=f"bengala_mode_auto_{device_id}")])
            buttons.append([InlineKeyboardButton("🤖 TODOS en modo Auto", callback_data="bengala_mode_auto_all")])

            keyboard = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(
                "🤖 *Modo Automático*\n\n"
                "Selecciona el dispositivo:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            # Un solo dispositivo: aplicar directamente
            device_id = devices[0]
            self.mqtt_handler.send_set_bengala_mode(mode=0, device_id=device_id)
            self.mqtt_handler.send_activate_bengala(device_id=device_id)  # Habilitar bengala
            self.device_manager.set_bengala_mode(device_id, 0)
            self.device_manager.set_bengala_enabled(device_id, True)  # Marcar como habilitada
            location = self.firebase_manager.get_device_location(device_id) or device_id

            await update.message.reply_text(
                f"🤖 *MODO AUTOMÁTICO ACTIVADO*\n"
                f"📍 {location}\n\n"
                "La bengala se disparará automáticamente cuando\n"
                "se active la alarma, sin preguntar.\n\n"
                "Usa `/preguntar` para volver al modo con confirmación.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self._get_keyboard()
            )

    @require_auth
    async def _cmd_preguntar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /preguntar - Configurar bengala en modo con pregunta"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/preguntar de {user.first_name}")

        if not self.mqtt_handler:
            await update.message.reply_text("❌ Error: Sistema no conectado")
            return

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos autorizados.")
            return

        # Si hay múltiples dispositivos, mostrar selector
        if len(devices) > 1:
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"❓ {location}", callback_data=f"bengala_mode_ask_{device_id}")])
            buttons.append([InlineKeyboardButton("❓ TODOS en modo Pregunta", callback_data="bengala_mode_ask_all")])

            keyboard = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(
                "❓ *Modo Con Pregunta*\n\n"
                "Selecciona el dispositivo:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            # Un solo dispositivo: aplicar directamente
            device_id = devices[0]
            self.mqtt_handler.send_set_bengala_mode(mode=1, device_id=device_id)
            self.mqtt_handler.send_activate_bengala(device_id=device_id)  # Habilitar bengala
            self.device_manager.set_bengala_mode(device_id, 1)
            self.device_manager.set_bengala_enabled(device_id, True)  # Marcar como habilitada
            location = self.firebase_manager.get_device_location(device_id) or device_id

            await update.message.reply_text(
                f"❓ *MODO CON PREGUNTA ACTIVADO*\n"
                f"📍 {location}\n\n"
                "Cuando se active la alarma, recibirás un mensaje\n"
                "con botones para confirmar o cancelar el disparo.\n\n"
                "Usa `/auto` para cambiar a modo automático.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self._get_keyboard()
            )

    @require_auth
    async def _cmd_deshabilitar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /deshabilitar - Deshabilitar bengala completamente"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/deshabilitar de {user.first_name}")

        if not self.mqtt_handler:
            await update.message.reply_text("❌ Error: Sistema no conectado")
            return

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos autorizados.")
            return

        # Si hay múltiples dispositivos, mostrar selector
        if len(devices) > 1:
            buttons = []
            for device_id in devices:
                location = self.firebase_manager.get_device_location(device_id) or device_id
                buttons.append([InlineKeyboardButton(f"❌ {location}", callback_data=f"bengala_off_{device_id}")])
            buttons.append([InlineKeyboardButton("❌ TODOS deshabilitados", callback_data="bengala_off_all")])

            keyboard = InlineKeyboardMarkup(buttons)
            await update.message.reply_text(
                "❌ *Deshabilitar Bengala*\n\n"
                "Selecciona el dispositivo:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
        else:
            # Un solo dispositivo: aplicar directamente
            device_id = devices[0]
            self.mqtt_handler.send_deactivate_bengala(device_id=device_id)
            self.device_manager.set_bengala_enabled(device_id, False)
            self.firebase_manager.set_bengala_enabled_in_firebase(device_id, False)  # Sync Firebase
            location = self.firebase_manager.get_device_location(device_id) or device_id

            await update.message.reply_text(
                f"❌ *BENGALA DESHABILITADA*\n"
                f"📍 {location}\n\n"
                "La bengala NO se disparará cuando se active la alarma.\n\n"
                "Usa `/auto` o `/preguntar` para habilitarla nuevamente.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=self._get_keyboard()
            )

    @require_auth
    async def _cmd_desvincular(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /desvincular - Desvincular dispositivos de tu cuenta"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/desvincular de {user.first_name}")

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos vinculados.")
            return

        if len(devices) == 1:
            # Si solo hay 1, preguntar confirmación directamente
            device_id = devices[0]
            location = self.firebase_manager.get_device_location(device_id) or device_id

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Sí, desvincular", callback_data=f"unlink_{device_id}"),
                    InlineKeyboardButton("❌ Cancelar", callback_data="unlink_cancel")
                ]
            ])

            await update.message.reply_text(
                f"⚠️ *¿Desvincular este dispositivo?*\n\n"
                f"📍 *{location}*\n"
                f"🔑 ID: `{device_id}`\n\n"
                f"Ya no podrás controlarlo desde Telegram.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard
            )
            return

        # Si hay más de 1, mostrar menú de selección
        buttons = []
        for device_id in devices:
            location = self.firebase_manager.get_device_location(device_id) or device_id
            buttons.append([InlineKeyboardButton(f"🔗 {location}", callback_data=f"unlink_select_{device_id}")])

        keyboard = InlineKeyboardMarkup(buttons)

        await update.message.reply_text(
            "🔗 *Desvincular dispositivo*\n\n"
            f"Tienes {len(devices)} dispositivo(s) vinculados.\n"
            "Selecciona el que deseas desvincular:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )

    @require_admin
    async def _cmd_permisos(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /permisos - Mostrar lista de usuarios"""
        user = update.effective_user
        logger.info(f"/permisos de {user.first_name}")

        # Obtener lista de usuarios de Firebase
        users_list = self.firebase_manager.get_all_users_formatted()
        if not users_list:
            users_list = "📋 *Lista de Usuarios*\n\nNo hay usuarios registrados."

        await update.message.reply_text(
            users_list,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self._get_keyboard()
        )

    @require_admin
    async def _cmd_horarios(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /horarios - Muestra y configura programacion"""
        user = update.effective_user
        args = context.args
        chat_id = str(update.effective_chat.id)

        logger.info(f"/horarios de {user.first_name} args={args}")

        # Obtener dispositivos del usuario
        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text("No tienes dispositivos autorizados.")
            return

        # Sin argumentos: mostrar selector de dispositivo o estado
        if not args:
            # Si hay múltiples dispositivos, mostrar selector
            if len(devices) > 1:
                buttons = []
                for device_id in devices:
                    location = self.firebase_manager.get_device_location(device_id) or device_id
                    buttons.append([InlineKeyboardButton(f"⏰ {location}", callback_data=f"horarios_select_{device_id}")])
                buttons.append([InlineKeyboardButton("⏰ TODOS los dispositivos", callback_data="horarios_select_all")])

                keyboard = InlineKeyboardMarkup(buttons)
                await update.message.reply_text(
                    "⏰ *PROGRAMACIÓN AUTOMÁTICA*\n\n"
                    "Selecciona el dispositivo a configurar:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
                return
            else:
                # Un solo dispositivo: seleccionar automáticamente
                self._horarios_selected_device[chat_id] = devices[0]

        # Mostrar menú de comandos si no hay subcomando
        if not args:
            selected = self._horarios_selected_device.get(chat_id)
            if selected:
                location = self.firebase_manager.get_device_location(selected) or selected if selected != "all" else "TODOS"
                status = f"📍 *Dispositivo:* {location}\n\n"
                status += scheduler.format_status()
                status += "\n\n📝 *Comandos:*\n"
                status += "`/horarios on` - Habilitar\n"
                status += "`/horarios off` - Deshabilitar\n"
                status += "`/horarios activar HH:MM` - Hora activacion\n"
                status += "`/horarios desactivar HH:MM` - Hora desactivacion\n"
                status += "`/horarios dias L,M,X,J,V` - Configurar dias\n"
                status += "`/horarios cambiar` - Cambiar dispositivo"

                await update.message.reply_text(
                    status,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=self._get_keyboard()
                )
            return

        subcommand = args[0].lower()

        # Comando para cambiar dispositivo seleccionado
        if subcommand == "cambiar":
            if len(devices) > 1:
                buttons = []
                for device_id in devices:
                    location = self.firebase_manager.get_device_location(device_id) or device_id
                    buttons.append([InlineKeyboardButton(f"⏰ {location}", callback_data=f"horarios_select_{device_id}")])
                buttons.append([InlineKeyboardButton("⏰ TODOS los dispositivos", callback_data="horarios_select_all")])

                keyboard = InlineKeyboardMarkup(buttons)
                await update.message.reply_text(
                    "⏰ *Selecciona el dispositivo:*",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await update.message.reply_text("Solo tienes un dispositivo.")
            return

        # Verificar que hay dispositivo seleccionado para los demás comandos
        selected = self._horarios_selected_device.get(chat_id)
        if not selected and len(devices) > 1:
            await update.message.reply_text(
                "⚠️ Primero selecciona un dispositivo.\n"
                "Usa `/horarios` para ver el selector.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        elif not selected:
            selected = devices[0]
            self._horarios_selected_device[chat_id] = selected

        # Determinar dispositivos objetivo
        target_devices = devices if selected == "all" else [selected]
        location_text = "TODOS los dispositivos" if selected == "all" else (self.firebase_manager.get_device_location(selected) or selected)

        # Habilitar/Deshabilitar
        if subcommand == "on":
            scheduler.set_enabled(True)
            await self._sync_schedule_to_devices(chat_id, target_devices)
            await update.message.reply_text(
                f"✅ *Programacion habilitada*\n"
                f"📍 {location_text}\n\n" + scheduler.format_status(),
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if subcommand == "off":
            scheduler.set_enabled(False)
            await self._sync_schedule_to_devices(chat_id, target_devices)
            await update.message.reply_text(
                f"🔴 *Programacion deshabilitada*\n"
                f"📍 {location_text}",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Configurar hora de activacion
        if subcommand == "activar" and len(args) >= 2:
            time_result = scheduler.parse_time_string(args[1])
            if time_result:
                hour, minute = time_result
                scheduler.set_on_time(hour, minute)
                await self._sync_schedule_to_devices(chat_id, target_devices)
                await update.message.reply_text(
                    f"✅ *Hora de activacion configurada*\n"
                    f"📍 {location_text}\n\n"
                    f"🔒 {scheduler.config.format_on_time()} ({scheduler.config.format_on_time_12h()})",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "❌ Formato invalido. Usa HH:MM (ej: 22:00)",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        # Configurar hora de desactivacion
        if subcommand == "desactivar" and len(args) >= 2:
            time_result = scheduler.parse_time_string(args[1])
            if time_result:
                hour, minute = time_result
                scheduler.set_off_time(hour, minute)
                await self._sync_schedule_to_devices(chat_id, target_devices)
                await update.message.reply_text(
                    f"✅ *Hora de desactivacion configurada*\n"
                    f"📍 {location_text}\n\n"
                    f"🔓 {scheduler.config.format_off_time()} ({scheduler.config.format_off_time_12h()})",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "❌ Formato invalido. Usa HH:MM (ej: 06:00)",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        # Configurar días de la semana
        if subcommand == "dias" and len(args) >= 2:
            dias_arg = args[1].lower()

            # Atajos especiales
            if dias_arg == "todos":
                days = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
            elif dias_arg == "semana":
                days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
            elif dias_arg == "finde" or dias_arg == "findesemana":
                days = ['Sábado', 'Domingo']
            else:
                # Parsear días separados por coma: L,M,X,J,V
                days = [d.strip() for d in args[1].split(',')]

            if scheduler.set_days(days):
                await self._sync_schedule_to_devices(chat_id, target_devices)
                await update.message.reply_text(
                    f"✅ *Días configurados*\n"
                    f"📍 {location_text}\n\n"
                    f"📅 {scheduler.format_days()}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    "❌ Días no válidos.\n"
                    "Usa: L,M,X,J,V,S,D o 'todos', 'semana', 'finde'",
                    parse_mode=ParseMode.MARKDOWN
                )
            return

        # Comando no reconocido
        await update.message.reply_text(
            "❓ Subcomando no reconocido.\n"
            "Usa `/horarios` para ver las opciones.",
            parse_mode=ParseMode.MARKDOWN
        )

    @require_auth
    async def _cmd_sensors(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /sensors - Muestra info técnica detallada y sensores LoRa"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        logger.info(f"/sensors de {user.first_name}")

        # Obtener dispositivos autorizados
        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await update.message.reply_text(
                "No tienes dispositivos autorizados.",
                reply_markup=self._get_keyboard()
            )
            return

        # Solicitar lista de sensores a todos los dispositivos
        await update.message.reply_text(
            f"📡 Solicitando información de {len(devices)} dispositivo(s)...",
            parse_mode=ParseMode.MARKDOWN
        )

        for device_id in devices:
            if self.mqtt_handler:
                self.mqtt_handler.send_get_sensors(device_id=device_id)

        # Esperar respuesta
        await asyncio.sleep(3)

        # Construir respuesta para cada dispositivo
        for device_id in devices:
            # Obtener nombre de Firebase (como hace /status)
            name = self.firebase_manager.get_device_location(device_id) or device_id

            # Obtener telemetría y estado
            telemetry = self.mqtt_handler.get_device_telemetry(device_id) if self.mqtt_handler else None
            device_info = self.device_manager.get_device_info(device_id) if self.device_manager else None
            sensors_list = self.mqtt_handler.get_sensors_list(device_id) if self.mqtt_handler else None

            # También buscar con ID truncado
            if not telemetry and self.mqtt_handler:
                truncated_id = self.mqtt_handler.truncate_device_id(device_id)
                telemetry = self.mqtt_handler.get_device_telemetry(truncated_id)
                if not sensors_list:
                    sensors_list = self.mqtt_handler.get_sensors_list(truncated_id)

            response = f"📡 *SENSORES - {name}*\n"
            response += "━" * 25 + "\n\n"

            # Estado online/offline
            is_online = device_info.get("is_online", False) if device_info else False

            if not is_online or not telemetry:
                response += "🔴 *Dispositivo desconectado*\n"
                response += f"🆔 `{device_id}`\n"
                await self.send_message(chat_id, response, "Markdown")
                continue

            # === SENSORES LORA ===
            lora_count = telemetry.lora_sensors_active if telemetry else 0

            if sensors_list and sensors_list.sensors:
                response += f"📻 *SENSORES LORA* ({sensors_list.active_sensors}/{sensors_list.total_sensors})\n"

                for i, sensor in enumerate(sensors_list.sensors):
                    is_last = (i == len(sensors_list.sensors) - 1)
                    prefix = "└─" if is_last else "├─"
                    status_icon = "🟢" if sensor.active else "🔴"

                    # Formatear tiempo desde última vez visto
                    if sensor.last_seen_sec < 60:
                        last_seen = f"{sensor.last_seen_sec}s"
                    elif sensor.last_seen_sec < 3600:
                        last_seen = f"{sensor.last_seen_sec // 60}m"
                    else:
                        last_seen = f"{sensor.last_seen_sec // 3600}h"

                    type_icon = sensor.get_type_icon()
                    response += f"{prefix} {status_icon} {type_icon} *{sensor.name}*\n"

                    detail_prefix = "    " if is_last else "│   "
                    response += f"{detail_prefix}RSSI: {sensor.rssi} dBm | Visto: hace {last_seen}\n"
            elif lora_count > 0:
                response += f"📻 *SENSORES LORA:* {lora_count} activos\n"
                response += "    _(usa /sensors de nuevo para ver detalles)_\n"
            else:
                response += "📻 *SENSORES LORA:* Sin sensores\n"

            response += "\n"

            # === DISPOSITIVO CENTRAL ===
            response += "📊 *DISPOSITIVO CENTRAL*\n"

            # WiFi
            rssi = telemetry.wifi_rssi
            if rssi >= -50:
                wifi_text = "Excelente"
            elif rssi >= -60:
                wifi_text = "Buena"
            elif rssi >= -70:
                wifi_text = "Regular"
            else:
                wifi_text = "Débil"
            response += f"├─ 📶 WiFi: {wifi_text} ({rssi} dBm)\n"

            # Memoria
            heap_kb = telemetry.heap_free / 1024
            heap_icon = "✅" if heap_kb > 50 else "⚠️"
            response += f"├─ {heap_icon} Memoria: {heap_kb:.1f} KB\n"

            # Uptime
            uptime_sec = telemetry.uptime_sec
            if uptime_sec >= 86400:
                uptime_text = f"{uptime_sec // 86400}d {(uptime_sec % 86400) // 3600}h"
            elif uptime_sec >= 3600:
                uptime_text = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m"
            else:
                uptime_text = f"{uptime_sec // 60}m"
            response += f"└─ ⏱ Uptime: {uptime_text}\n"

            response += "\n"

            # === CONFIGURACIÓN ===
            response += "🔒 *CONFIGURACIÓN*\n"

            # Estado del sistema
            if device_info:
                is_armed = device_info.get("is_armed", False)
                response += f"├─ Sistema: {'ARMADO' if is_armed else 'DESARMADO'}\n"

                # Bengala
                bengala_mode = device_info.get("bengala_mode", 1)
                bengala_enabled = device_info.get("bengala_enabled", True)
                if bengala_enabled:
                    mode_text = "Auto" if bengala_mode == 0 else "Pregunta"
                else:
                    mode_text = "Deshabilitada"
                response += f"├─ 🔥 Bengala: {mode_text}\n"

            # Tiempos
            tiempo_bomba = telemetry.tiempo_bomba if telemetry else 60
            response += f"├─ ⏰ Tiempo salida: {tiempo_bomba}s\n"

            # Horario
            if telemetry and telemetry.auto_schedule_enabled:
                schedule_info = scheduler.format_status() if scheduler.config.enabled else "Activo"
                response += f"└─ 📅 Horario: {schedule_info}\n"
            else:
                response += f"└─ 📅 Horario: Desactivado\n"

            response += f"\n🆔 `{device_id}`"

            await self.send_message(chat_id, response, "Markdown")

    async def _sync_schedule_to_devices(self, chat_id: str, target_devices: list = None):
        """Sincroniza los horarios del scheduler con ESP32 y Firebase

        Args:
            chat_id: ID del chat de Telegram
            target_devices: Lista de dispositivos específicos a sincronizar.
                           Si es None, sincroniza todos los dispositivos autorizados.
        """
        # Si no se especifican dispositivos, usar todos los autorizados
        if target_devices is None:
            devices = self.firebase_manager.get_authorized_devices(chat_id)
        else:
            devices = target_devices

        # Obtener índices de días para enviar al ESP32
        days_indices = scheduler.get_days_indices()

        for device_id in devices:
            # 1. Enviar al ESP32
            if self.mqtt_handler:
                self.mqtt_handler.send_set_schedule(
                    scheduler.config.enabled,
                    scheduler.config.on_hour,
                    scheduler.config.on_minute,
                    scheduler.config.off_hour,
                    scheduler.config.off_minute,
                    days=days_indices,
                    device_id=device_id
                )

            # 2. Actualizar Firebase (con nombres de días para la App)
            if self.firebase_manager.is_available():
                try:
                    schedule_path = f"Horarios/{chat_id}/devices/{device_id}"
                    schedule_data = {
                        "activationTime": scheduler.config.format_on_time(),
                        "deactivationTime": scheduler.config.format_off_time(),
                        "enabled": scheduler.config.enabled,
                        "days": scheduler.get_days(),  # Lista de nombres: ['Lunes', 'Martes', ...]
                        "lastUpdatedBy": "telegram"
                    }
                    self.firebase_manager.db.reference(schedule_path).set(schedule_data)
                    logger.info(f"Horario sincronizado a Firebase: {schedule_path} (días: {scheduler.format_days()})")
                except Exception as e:
                    logger.error(f"Error sincronizando horario a Firebase: {e}")

    @require_admin
    async def _cmd_adduser(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /adduser - Generar codigo de invitacion"""
        user = update.effective_user
        logger.info(f"/adduser de {user.first_name}")

        # Generar codigo de invitacion basado en device_id
        device_id = self.mqtt_handler.device_id if self.mqtt_handler else "ALARMA"
        device_id = device_id or "ALARMA"
        invite_code = f"/join_{device_id}"

        msg = (
            "📱 *AGREGAR NUEVO USUARIO*\n\n"
            "Envia este codigo al usuario que quieres agregar:\n\n"
            f"`{invite_code}`\n\n"
            "El usuario debe enviarlo al bot y luego tu "
            "recibiras una notificacion para aprobarlo."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    async def _handle_unknown_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para mensajes de texto que no son comandos"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        logger.info(f"Mensaje de texto de {user.first_name} ({chat_id}): {update.message.text[:50]}")

        # Verificar si el usuario esta autorizado
        if not self.firebase_manager.get_authorized_devices(chat_id):
            await update.message.reply_text(
                "🚫 *Usuario no autorizado*\n\n"
                "No estas registrado en el sistema.\n"
                "Usa /start para comenzar o contacta a un administrador.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Usuario autorizado pero envio texto en lugar de comando
        await update.message.reply_text(
            "ℹ️ Usa comandos para interactuar con el sistema.\n"
            "Escribe /help para ver los comandos disponibles.",
            reply_markup=self._get_keyboard()
        )

    async def _handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para comandos no reconocidos"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)

        logger.info(f"Comando no reconocido de {user.first_name}: {update.message.text}")

        # Verificar si el usuario esta autorizado
        if not self.firebase_manager.get_authorized_devices(chat_id):
            await update.message.reply_text(
                "🚫 *Usuario no autorizado*\n\n"
                "No estas registrado en el sistema.\n"
                "Usa /start para comenzar o contacta a un administrador.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        await update.message.reply_text(
            f"❓ Comando no reconocido: `{update.message.text}`\n\n"
            "Usa /help para ver los comandos disponibles.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=self._get_keyboard()
        )

    async def _cmd_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /join_XXXX - Solicitar acceso a un dispositivo específico"""
        user = update.effective_user
        chat_id = str(update.effective_chat.id)
        text = update.message.text

        logger.info(f"{text} de {user.first_name}")

        # Extraer device_id del comando
        device_id = text.replace("/join_", "")

        if not device_id:
            await update.message.reply_text(
                "❌ Formato incorrecto. Usa: `/join_ID_DEL_DISPOSITIVO`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Verificar si ya tiene acceso a ESTE dispositivo específico
        authorized_devices = self.firebase_manager.get_authorized_devices(chat_id)
        for auth_dev in authorized_devices:
            # Comparar considerando IDs truncados
            if auth_dev.startswith(device_id) or device_id.startswith(auth_dev):
                device_name = self.firebase_manager.get_device_location(auth_dev) or auth_dev
                await update.message.reply_text(
                    f"ℹ️ *Ya tienes acceso* a este dispositivo ({device_name}).",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

        # Agregar solicitud pendiente en Firebase
        self.firebase_manager.add_pending_request(chat_id, user.first_name, device_id)

        # Obtener nombre del dispositivo si existe
        device_name = self.firebase_manager.get_device_location(device_id) or device_id

        await update.message.reply_text(
            f"⏳ *Solicitud enviada* al administrador.\n"
            f"📱 Dispositivo: *{device_name}*\n\n"
            f"⏰ La solicitud expira en *5 minutos*.\n"
            f"Recibirás una notificación cuando seas autorizado.",
            parse_mode=ParseMode.MARKDOWN
        )

        # Notificar solo al dueño del dispositivo
        owner_id = self.firebase_manager.get_device_owner(device_id)
        if owner_id:
            admin_msg = (
                "🔔 *NUEVA SOLICITUD DE ACCESO*\n\n"
                f"👤 Usuario: *{user.first_name}*\n"
                f"🆔 Chat ID: `{chat_id}`\n"
                f"📱 Dispositivo: *{device_name}* (`{device_id}`)\n\n"
                f"⏰ Expira en 5 minutos\n\n"
                f"✅ Para aprobar, envía:\n`/approve_{chat_id}`"
            )
            await self.send_message(owner_id, admin_msg, "Markdown")
        else:
            logger.warning(f"No se encontró dueño para el dispositivo {device_id}")

    @require_admin
    async def _cmd_approve(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para /approve_XXXX - Aprobar solicitud de acceso"""
        user = update.effective_user
        text = update.message.text

        logger.info(f"{text} de {user.first_name}")

        # Extraer chat_id del comando
        target_chat_id = text.replace("/approve_", "")

        if not target_chat_id:
            await update.message.reply_text(
                "❌ Formato incorrecto. Usa: `/approve_CHAT_ID`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Buscar solicitud pendiente en Firebase
        pending = self.firebase_manager.get_pending_request(target_chat_id)

        if pending:
            approved_name = pending.get('name', 'Usuario')
            device_id = pending.get('device_id')

            if not device_id:
                await update.message.reply_text(
                    "❌ *Error:* La solicitud no tiene dispositivo asociado.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            # Agregar autorización en Firebase
            success = self.firebase_manager.add_authorized_chat(device_id, target_chat_id)

            # Eliminar solicitud pendiente
            self.firebase_manager.remove_pending_request(target_chat_id)

            if success:
                device_name = self.firebase_manager.get_device_location(device_id) or device_id

                await update.message.reply_text(
                    f"✅ *Usuario aprobado*\n\n"
                    f"👤 {approved_name} ahora tiene acceso a *{device_name}*.",
                    parse_mode=ParseMode.MARKDOWN
                )

                # Notificar al usuario aprobado
                await self.send_message(
                    target_chat_id,
                    f"🎉 *¡Acceso aprobado!*\n\n"
                    f"Ya tienes acceso a *{device_name}*.\n"
                    f"Usa /help para ver los comandos.",
                    "Markdown",
                    has_keyboard=True
                )
            else:
                await update.message.reply_text(
                    f"⚠️ *No se pudo agregar* el acceso.\n"
                    f"El dispositivo `{device_id}` puede que ya tenga usuarios asignados.\n"
                    f"Verifica en Firebase.",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                "❌ *No se encontró* la solicitud.\n\n"
                "Posibles causas:\n"
                "• La solicitud expiró (tiempo límite: 5 minutos)\n"
                "• Ya fue procesada anteriormente\n"
                "• El usuario no envió `/join_`",
                parse_mode=ParseMode.MARKDOWN
            )

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para callbacks de botones inline con confirmacion"""
        query = update.callback_query
        await query.answer()

        user = query.from_user
        chat_id = str(query.message.chat_id)
        data = query.data
        
        logger.info(f"Callback {data} de {user.first_name}")

        if not self.mqtt_handler:
            await query.edit_message_text("❌ Error: Sistema no conectado")
            return

        devices = self.firebase_manager.get_authorized_devices(chat_id)
        if not devices:
            await query.edit_message_text("No tienes dispositivos autorizados.")
            return

        request_time = time.time()
        
        # Procesar callbacks
        if data == "trigger_confirm":
            await query.edit_message_text(f"🚨 Enviando comando de disparo a {len(devices)} dispositivo(s)... Esperando confirmación (5s).", parse_mode=ParseMode.MARKDOWN)
            for device_id in devices:
                self.mqtt_handler.send_trigger_alarm(device_id=device_id)
            
            await asyncio.sleep(5)

            for device_id in devices:
                device_location = self.firebase_manager.get_device_location(device_id) or device_id
                if self.mqtt_handler.is_device_online(device_id):
                    await self.send_message(chat_id, f"✅ *{device_location}* - Comando de disparo enviado. El dispositivo está EN LÍNEA.", "Markdown")
                else:
                    await self.send_message(chat_id, f"❌ *{device_location}* - NO RESPONDIÓ. El comando de disparo no pudo ser confirmado.", "Markdown")


        elif data == "trigger_cancel":
            await query.edit_message_text("❌ Disparo cancelado.")

        # Callbacks para recordatorio de alarma activa
        elif data == "bengala_confirm":
            # Disparar bengala en dispositivos en alarma
            alarming_devices = [d for d in devices if self.device_manager.is_alarming(d)]
            if alarming_devices:
                await query.edit_message_text("🔥 Enviando comando para disparar bengala...")
                for device_id in alarming_devices:
                    self.mqtt_handler.send_trigger_bengala(device_id=device_id)
                    device_location = self.firebase_manager.get_device_location(device_id) or device_id
                    self._clear_bengala_confirmation(device_id)
                    self._clear_alarm_notification(device_id)

                    # Notificar a TODOS los chats autorizados (privados y grupos)
                    all_chats = self.firebase_manager.get_authorized_chats(device_id)
                    bengala_msg = f"🔥 *BENGALA ACTIVADA*\n📍 {device_location}"
                    for notify_chat_id in all_chats:
                        try:
                            await self.send_message(notify_chat_id, bengala_msg, "Markdown", has_keyboard=True)
                        except Exception as e:
                            logger.error(f"Error notificando bengala a {notify_chat_id}: {e}")
            else:
                await query.edit_message_text("ℹ️ No hay dispositivos en alarma activa.")

        elif data == "bengala_cancel":
            # Dejar armado - detener sirena pero mantener armado
            await query.edit_message_text("🔇 Deteniendo sirena...")

            # Detener la alarma (sirena/buzzer) en dispositivos que están alarmando
            stopped_devices = []
            for device_id in devices:
                if self.device_manager.is_alarming(device_id):
                    self.mqtt_handler.send_stop_alarm(device_id=device_id)
                    # Reset alarming state to stop reminders
                    self.device_manager.set_alarming_state(device_id, False)
                    device_location = self.firebase_manager.get_device_location(device_id) or device_id
                    stopped_devices.append(device_location)
                self._clear_bengala_confirmation(device_id)

            if stopped_devices:
                locations = ", ".join(stopped_devices)
                await self.send_message(
                    chat_id,
                    f"🔇 *Sirena detenida*\n"
                    f"📍 {locations}\n\n"
                    f"🔒 El sistema continúa *ARMADO*.\n"
                    f"Seguirá detectando intrusiones.",
                    "Markdown"
                )
            else:
                await self.send_message(
                    chat_id,
                    "🔒 *Sistema armado*\n\n"
                    "El sistema continúa armado y detectando intrusiones.",
                    "Markdown"
                )

        elif data == "bengala_on":
            # Enviar comando para activar bengala
            # El ESP32 enviará evento bengala_activated que se notificará por separado
            for device_id in devices:
                self.mqtt_handler.send_activate_bengala(device_id=device_id)

            await query.edit_message_text(
                f"🔥 *BENGALA ACTIVADA*\n\n"
                f"Comando enviado a {len(devices)} dispositivo(s).",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "bengala_off":
            # Enviar comando para desactivar bengala
            # El ESP32 enviará evento bengala_deactivated que se notificará por separado
            for device_id in devices:
                self.mqtt_handler.send_deactivate_bengala(device_id=device_id)

            await query.edit_message_text(
                f"🔥 *BENGALA DESACTIVADA*\n\n"
                f"Comando enviado a {len(devices)} dispositivo(s).",
                parse_mode=ParseMode.MARKDOWN
            )

        # Seleccionar dispositivo para configurar bengala
        elif data.startswith("bengala_select_"):
            target = data.replace("bengala_select_", "")
            if target == "all":
                # Mostrar opciones para todos los dispositivos (usar el primero como referencia)
                await self._show_bengala_options(query, devices[0], is_all=True)
            elif target in devices:
                await self._show_bengala_options(query, target, is_all=False)
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        elif data.startswith("bengala_mode_auto_"):
            # Cambiar a modo automático
            target = data.replace("bengala_mode_auto_", "")
            target_devices = devices if target == "all" else [target] if target in devices else []

            if not target_devices:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")
                return

            for device_id in target_devices:
                self.mqtt_handler.send_set_bengala_mode(mode=0, device_id=device_id)
                self.mqtt_handler.send_activate_bengala(device_id=device_id)  # Habilitar bengala
                # Usar ID truncado para device_manager (coincide con telemetría del ESP32)
                truncated_id = self.mqtt_handler.truncate_device_id(device_id)
                self.device_manager.set_bengala_mode(truncated_id, 0)
                self.device_manager.set_bengala_enabled(truncated_id, True)  # Marcar como habilitada

            location = "TODOS los dispositivos" if target == "all" else (self.firebase_manager.get_device_location(target) or target)
            await query.edit_message_text(
                f"🤖 *MODO AUTOMÁTICO ACTIVADO*\n"
                f"📍 {location}\n\n"
                "La bengala se disparará automáticamente\n"
                "cuando se active la alarma.",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data.startswith("bengala_mode_ask_"):
            # Cambiar a modo con pregunta
            target = data.replace("bengala_mode_ask_", "")
            target_devices = devices if target == "all" else [target] if target in devices else []

            if not target_devices:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")
                return

            for device_id in target_devices:
                self.mqtt_handler.send_set_bengala_mode(mode=1, device_id=device_id)
                self.mqtt_handler.send_activate_bengala(device_id=device_id)  # Habilitar bengala
                # Usar ID truncado para device_manager (coincide con telemetría del ESP32)
                truncated_id = self.mqtt_handler.truncate_device_id(device_id)
                self.device_manager.set_bengala_mode(truncated_id, 1)
                self.device_manager.set_bengala_enabled(truncated_id, True)  # Marcar como habilitada

            location = "TODOS los dispositivos" if target == "all" else (self.firebase_manager.get_device_location(target) or target)
            await query.edit_message_text(
                f"❓ *MODO CON PREGUNTA ACTIVADO*\n"
                f"📍 {location}\n\n"
                "Recibirás una pregunta antes de\n"
                "disparar la bengala.",
                parse_mode=ParseMode.MARKDOWN
            )

        elif data.startswith("bengala_off_"):
            # Deshabilitar bengala
            target = data.replace("bengala_off_", "")
            target_devices = devices if target == "all" else [target] if target in devices else []

            if not target_devices:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")
                return

            location = "TODOS los dispositivos" if target == "all" else (self.firebase_manager.get_device_location(target) or target)

            # Enviar comando y confirmar inmediatamente
            # El ESP32 enviará evento bengala_deactivated que se notificará por separado
            for device_id in target_devices:
                self.mqtt_handler.send_deactivate_bengala(device_id=device_id)
                # Marcar bengala deshabilitada en device_manager con ID truncado
                truncated_id = self.mqtt_handler.truncate_device_id(device_id)
                self.device_manager.set_bengala_enabled(truncated_id, False)
                self.firebase_manager.set_bengala_enabled_in_firebase(device_id, False)  # Sync Firebase

            await query.edit_message_text(
                f"✅ *BENGALA DESHABILITADA*\n"
                f"📍 {location}\n\n"
                "La bengala no se disparará cuando\n"
                "se active la alarma.",
                parse_mode=ParseMode.MARKDOWN
            )

        # === Callbacks para selección de dispositivos ===

        # Armar dispositivo específico
        elif data.startswith("arm_") and data != "arm_all":
            target_device = data.replace("arm_", "")
            if target_device in devices:
                await self._arm_devices(query, [target_device], single_device=True)
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Armar todos los dispositivos
        elif data == "arm_all":
            await self._arm_devices(query, devices)

        # Desarmar dispositivo específico
        elif data.startswith("disarm_") and data != "disarm_all":
            target_device = data.replace("disarm_", "")
            if target_device in devices:
                await self._disarm_devices(query, [target_device])
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Desarmar todos los dispositivos
        elif data == "disarm_all":
            await self._disarm_devices(query, devices)

        # Ver estado de dispositivo específico
        elif data.startswith("status_") and data != "status_all":
            target_device = data.replace("status_", "")
            if target_device in devices:
                await self._get_device_status(query, [target_device])
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Ver estado de todos los dispositivos
        elif data == "status_all":
            await self._get_device_status(query, devices)

        # === Callbacks para desvincular dispositivos ===

        # Seleccionar dispositivo para desvincular (muestra confirmación)
        elif data.startswith("unlink_select_"):
            target_device = data.replace("unlink_select_", "")
            if target_device in devices:
                location = self.firebase_manager.get_device_location(target_device) or target_device

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Sí, desvincular", callback_data=f"unlink_{target_device}"),
                        InlineKeyboardButton("❌ Cancelar", callback_data="unlink_cancel")
                    ]
                ])

                await query.edit_message_text(
                    f"⚠️ *¿Desvincular este dispositivo?*\n\n"
                    f"📍 *{location}*\n"
                    f"🔑 ID: `{target_device}`\n\n"
                    f"Ya no podrás controlarlo desde Telegram.",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard
                )
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Confirmar desvinculación
        elif data.startswith("unlink_") and data != "unlink_cancel":
            target_device = data.replace("unlink_", "")
            if target_device in devices:
                location = self.firebase_manager.get_device_location(target_device) or target_device

                # Desvincular el dispositivo
                success = self.firebase_manager.unlink_device_from_user(chat_id, target_device)

                if success:
                    await query.edit_message_text(
                        f"✅ *Dispositivo desvinculado*\n\n"
                        f"📍 *{location}* ha sido removido de tu cuenta.\n\n"
                        f"Para volver a vincularlo, pide al administrador\n"
                        f"que te envíe un nuevo código de invitación.",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    logger.info(f"Dispositivo {target_device} desvinculado de {chat_id}")
                else:
                    await query.edit_message_text(
                        f"❌ *Error al desvincular*\n\n"
                        f"No se pudo desvincular el dispositivo.\n"
                        f"Intenta nuevamente más tarde.",
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Cancelar desvinculación
        elif data == "unlink_cancel":
            await query.edit_message_text("❌ Desvinculación cancelada.")

        # === Callbacks para selección de dispositivo en horarios ===

        # Seleccionar dispositivo específico para horarios
        elif data.startswith("horarios_select_") and data != "horarios_select_all":
            target_device = data.replace("horarios_select_", "")
            if target_device in devices:
                self._horarios_selected_device[chat_id] = target_device
                location = self.firebase_manager.get_device_location(target_device) or target_device

                status = f"⏰ *PROGRAMACIÓN AUTOMÁTICA*\n\n"
                status += f"📍 *Dispositivo:* {location}\n\n"
                status += scheduler.format_status()
                status += "\n\n📝 *Comandos:*\n"
                status += "`/horarios on` - Habilitar\n"
                status += "`/horarios off` - Deshabilitar\n"
                status += "`/horarios activar HH:MM` - Hora activación\n"
                status += "`/horarios desactivar HH:MM` - Hora desactivación\n"
                status += "`/horarios dias L,M,X,J,V` - Configurar días\n"
                status += "`/horarios cambiar` - Cambiar dispositivo"

                await query.edit_message_text(
                    status,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text("❌ No tienes acceso a este dispositivo.")

        # Seleccionar TODOS los dispositivos para horarios
        elif data == "horarios_select_all":
            self._horarios_selected_device[chat_id] = "all"

            status = f"⏰ *PROGRAMACIÓN AUTOMÁTICA*\n\n"
            status += f"📍 *Dispositivo:* TODOS los dispositivos\n\n"
            status += scheduler.format_status()
            status += "\n\n📝 *Comandos:*\n"
            status += "`/horarios on` - Habilitar\n"
            status += "`/horarios off` - Deshabilitar\n"
            status += "`/horarios activar HH:MM` - Hora activación\n"
            status += "`/horarios desactivar HH:MM` - Hora desactivación\n"
            status += "`/horarios dias L,M,X,J,V` - Configurar días\n"
            status += "`/horarios cambiar` - Cambiar dispositivo"

            await query.edit_message_text(
                status,
                parse_mode=ParseMode.MARKDOWN
            )

        else:
            logger.warning(f"Callback no reconocido: {data}")

    # ========================================
    # Metodos para manejar eventos del ESP32
    # ========================================

    async def handle_mqtt_event(self, event: MqttEvent):
        """Procesa un evento MQTT y notifica a los usuarios"""
        from mqtt_protocol import EventType

        # Ignorar eventos de status_response (status diario automático del ESP32)
        if event.event_type == EventType.STATUS_RESPONSE:
            logger.debug(f"Ignorando evento status_response de {event.device_id} (status diario automático)")
            return

        device_id = event.device_id
        device_location = self.firebase_manager.get_device_location(device_id) or device_id

        # Obtener chats autorizados para este dispositivo
        chat_ids = self.firebase_manager.get_authorized_chats(device_id)
        if not chat_ids:
            logger.warning(f"Dispositivo {device_id} no tiene Telegram_ID ni Group_ID configurados - no se notificará")
            return

        # Manejar evento de alarma disparada con flujo de bengala
        if event.event_type == EventType.ALARM_TRIGGERED:
            logger.info(f"🚨 ALARM_TRIGGERED recibido de {device_id}")
            bengala_mode = self.device_manager.get_bengala_mode(device_id)
            bengala_enabled = self.device_manager.is_bengala_enabled(device_id)
            sensor_name = event.data.get("sensorName", "Sensor desconocido")
            sensor_location = event.data.get("location", device_location)

            logger.info(f"🚨 Configuración: bengala_mode={bengala_mode}, bengala_enabled={bengala_enabled}")
            logger.info(f"🚨 Sensor: {sensor_name}, Location: {sensor_location}")
            logger.info(f"🚨 Chats autorizados: {chat_ids}")

            if bengala_mode == 1 and bengala_enabled:  # Modo pregunta con bengala habilitada
                # Iniciar flujo de confirmación de bengala (con botón de disparar bengala)
                logger.info(f"🚨 Iniciando flujo de confirmación de bengala para {device_id}")
                await self._start_bengala_confirmation(
                    device_id=device_id,
                    chat_ids=chat_ids,
                    sensor_name=sensor_name,
                    sensor_location=sensor_location
                )
                return  # El mensaje de confirmación ya se envía en _start_bengala_confirmation
            else:
                # Modo automático o bengala deshabilitada: solo botón de desactivar
                logger.info(f"🚨 Iniciando notificación de alarma (modo auto) para {device_id}")
                await self._start_alarm_notification(
                    device_id=device_id,
                    chat_ids=chat_ids,
                    sensor_name=sensor_name,
                    sensor_location=sensor_location
                )
                return

        # Si el sistema se desarma o la alarma se detiene, limpiar notificaciones pendientes
        if event.event_type in [EventType.SYSTEM_DISARMED, EventType.ALARM_STOPPED]:
            if device_id in self._bengala_confirmations:
                self._clear_bengala_confirmation(device_id)
                logger.info(f"Confirmación de bengala cancelada para {device_id} (sistema desarmado/alarma detenida)")
            if device_id in self._alarm_notifications:
                self._clear_alarm_notification(device_id)
                logger.info(f"Notificación de alarma cancelada para {device_id} (sistema desarmado/alarma detenida)")

        # Formatear mensaje
        message = self.mqtt_handler.format_event_message(event) if self.mqtt_handler else str(event)

        # Enviar a todos los usuarios
        for chat_id in chat_ids:
            try:
                await self.send_message(chat_id, message, "Markdown", has_keyboard=True)
            except Exception as e:
                logger.error(f"Error enviando a {chat_id}: {e}")

    # ========================================
    # Metodos para flujo de confirmacion de bengala
    # ========================================

    async def _start_bengala_confirmation(
        self,
        device_id: str,
        chat_ids: List[str],
        sensor_name: str,
        sensor_location: str
    ):
        """Inicia el flujo de confirmación de bengala para un dispositivo."""
        device_location = self.firebase_manager.get_device_location(device_id) or device_id

        # Crear estado de confirmación
        confirmation = BengalaConfirmation(
            device_id=device_id,
            chat_ids=list(chat_ids),
            sensor_name=sensor_name,
            sensor_location=sensor_location,
            timestamp=time.time()
        )

        # Guardar en el diccionario de confirmaciones pendientes
        self._bengala_confirmations[device_id] = confirmation

        # Mensaje de alerta con botones (para chat privado)
        alert_msg_private = (
            f"🚨 *¡ALARMA ACTIVADA!*\n\n"
            f"📍 *{device_location}*\n"
            f"🔔 Sensor: {sensor_name}"
        )

        # Mensaje simple para grupos (sin botones de bengala)
        alert_msg_group = (
            f"🚨 *¡ALARMA ACTIVADA!*\n"
            f"📍 {device_location}\n"
            f"📡 Sensor: {sensor_name}"
        )

        # Teclado con botones para chat privado
        keyboard_private = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔥 Disparar bengala", callback_data="bengala_confirm")
            ],
            [
                InlineKeyboardButton("🔒 Dejar armado", callback_data="bengala_cancel"),
                InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")
            ]
        ])

        # Enviar a todos los chats autorizados
        for chat_id in chat_ids:
            try:
                # Determinar si es grupo o chat privado
                is_group = str(chat_id).startswith('-')
                if is_group:
                    # Grupo: mensaje simple sin botones de bengala
                    # skip_anti_spam=True porque alarmas son eventos críticos
                    await self.send_message(chat_id, alert_msg_group, "Markdown", has_keyboard=True, skip_anti_spam=True)
                    logger.info(f"🚨 Notificación de alarma enviada a GRUPO {chat_id}")
                else:
                    # Chat privado: mensaje con botones
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=alert_msg_private,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard_private
                    )
                    logger.info(f"🚨 Notificación de alarma enviada a PRIVADO {chat_id}")
            except Exception as e:
                logger.error(f"Error enviando confirmación de bengala a {chat_id}: {e}")

        logger.info(f"Flujo de confirmación de bengala iniciado para {device_id} (sensor: {sensor_name})")

    async def _start_alarm_notification(
        self,
        device_id: str,
        chat_ids: List[str],
        sensor_name: str,
        sensor_location: str
    ):
        """
        Inicia notificación de alarma para modo automático o bengala deshabilitada.
        Solo muestra botón de Desactivar sistema (sin opción de bengala).
        """
        device_location = self.firebase_manager.get_device_location(device_id) or device_id

        # Guardar estado para recordatorios
        self._alarm_notifications[device_id] = {
            "chat_ids": list(chat_ids),
            "sensor_name": sensor_name,
            "sensor_location": sensor_location,
            "timestamp": time.time(),
            "reminder_task": None,
            "last_reminder_time": {chat_id: 0 for chat_id in chat_ids}
        }

        # Mensaje de alerta
        alert_msg = (
            f"🚨 *¡ALARMA ACTIVADA!*\n\n"
            f"📍 *{device_location}*\n"
            f"🔔 Sensor: {sensor_name}"
        )

        # Teclado solo con botón de desactivar
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")]
        ])

        # Enviar a todos los chats autorizados
        for chat_id in chat_ids:
            try:
                is_group = str(chat_id).startswith('-')
                if is_group:
                    # Grupo: mensaje sin botones inline (usará teclado principal)
                    # skip_anti_spam=True porque alarmas son eventos críticos
                    await self.send_message(chat_id, alert_msg, "Markdown", has_keyboard=True, skip_anti_spam=True)
                    logger.info(f"🚨 Notificación de alarma (auto) enviada a GRUPO {chat_id}")
                else:
                    # Chat privado: mensaje con botón de desactivar
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=alert_msg,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=keyboard
                    )
                    logger.info(f"🚨 Notificación de alarma (auto) enviada a PRIVADO {chat_id}")
            except Exception as e:
                logger.error(f"Error enviando notificación de alarma a {chat_id}: {e}")

        # Iniciar tarea de recordatorios
        reminder_task = asyncio.create_task(self._alarm_reminder_task(device_id))
        self._alarm_notifications[device_id]["reminder_task"] = reminder_task

        logger.info(f"Notificación de alarma iniciada para {device_id} (sensor: {sensor_name}, modo auto/deshabilitado)")

    async def _alarm_reminder_task(self, device_id: str):
        """
        Tarea de recordatorios para alarma activa (modo auto/deshabilitado).
        Privado: cada 1 minuto, Grupos: cada 5 minutos.
        Solo envía si el dispositivo está online.
        """
        try:
            # Esperar un poco antes del primer recordatorio
            await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)

            while device_id in self._alarm_notifications:
                notification = self._alarm_notifications.get(device_id)
                if not notification:
                    break

                # Verificar si el dispositivo sigue en alarma
                if not self.device_manager.is_alarming(device_id):
                    break

                # Solo enviar recordatorios si el dispositivo está online
                if not self.mqtt_handler or not self.mqtt_handler.is_device_online(device_id):
                    await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)
                    continue

                device_location = self.firebase_manager.get_device_location(device_id) or device_id
                current_time = time.time()

                reminder_msg = (
                    f"⚠️ *RECORDATORIO - ALARMA ACTIVA*\n\n"
                    f"📍 *{device_location}*\n"
                    f"🔔 Sensor: {notification['sensor_name']}\n\n"
                    f"Usa /off para desactivar el sistema."
                )

                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔓 Desactivar sistema", callback_data="disarm_all")]
                ])

                for chat_id in notification["chat_ids"]:
                    try:
                        is_group = str(chat_id).startswith('-')

                        # Recordatorios solo para chats privados, no grupos
                        if is_group:
                            continue

                        last_reminder = notification["last_reminder_time"].get(chat_id, 0)

                        # Solo enviar si pasó el intervalo (1 minuto para privados)
                        if current_time - last_reminder >= self.REMINDER_INTERVAL_PRIVATE:
                            await self.application.bot.send_message(
                                chat_id=chat_id,
                                text=reminder_msg,
                                parse_mode=ParseMode.MARKDOWN,
                                reply_markup=keyboard
                            )
                            notification["last_reminder_time"][chat_id] = current_time
                            logger.debug(f"Recordatorio de alarma enviado a {chat_id}")
                    except Exception as e:
                        logger.error(f"Error enviando recordatorio a {chat_id}: {e}")

                # Esperar el intervalo mínimo antes de verificar de nuevo
                await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)

        except asyncio.CancelledError:
            logger.debug(f"Tarea de recordatorio de alarma cancelada para {device_id}")
        except Exception as e:
            logger.error(f"Error en tarea de recordatorio de alarma para {device_id}: {e}")

    def _clear_alarm_notification(self, device_id: str):
        """Limpia el estado de notificación de alarma para un dispositivo."""
        notification = self._alarm_notifications.pop(device_id, None)
        if notification and notification.get("reminder_task"):
            notification["reminder_task"].cancel()
            logger.debug(f"Notificación de alarma limpiada para {device_id}")

    async def _bengala_reminder_task(self, device_id: str):
        """
        Tarea de recordatorios para confirmación de bengala.
        Privado: cada 1 minuto, Grupos: cada 5 minutos.
        Solo envía si el dispositivo está online.
        """
        try:
            # Inicializar tiempos de último recordatorio por chat
            last_reminder_time: Dict[str, float] = {}

            # Esperar antes del primer recordatorio
            await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)

            while device_id in self._bengala_confirmations:
                confirmation = self._bengala_confirmations.get(device_id)
                if not confirmation:
                    break

                # Verificar si ha expirado
                if confirmation.is_expired(self.BENGALA_CONFIRMATION_TIMEOUT):
                    logger.info(f"Confirmación de bengala expirada para {device_id}")
                    await self._handle_bengala_timeout(device_id)
                    break

                # Solo enviar recordatorios si el dispositivo está online
                if not self.mqtt_handler or not self.mqtt_handler.is_device_online(device_id):
                    await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)
                    continue

                current_time = time.time()
                time_remaining = self.BENGALA_CONFIRMATION_TIMEOUT - (current_time - confirmation.timestamp)
                device_location = self.firebase_manager.get_device_location(device_id) or device_id

                reminder_msg = (
                    f"⚠️ *RECORDATORIO - ALARMA ACTIVA*\n\n"
                    f"📍 *{device_location}*\n"
                    f"🔔 Sensor: {confirmation.sensor_name}\n\n"
                    f"🔥 *¿Disparar bengala?*\n"
                    f"Usa los botones del mensaje anterior para responder.\n\n"
                    f"⏱️ _Tiempo restante: {int(time_remaining)}s_"
                )

                for chat_id in confirmation.chat_ids:
                    try:
                        is_group = str(chat_id).startswith('-')

                        # Recordatorios solo para chats privados, no grupos
                        if is_group:
                            continue

                        last_sent = last_reminder_time.get(chat_id, 0)

                        # Solo enviar si pasó el intervalo (1 minuto para privados)
                        if current_time - last_sent >= self.REMINDER_INTERVAL_PRIVATE:
                            # skip_anti_spam=True porque recordatorios de alarma son críticos
                            await self.send_message(chat_id, reminder_msg, "Markdown", has_keyboard=True, skip_anti_spam=True)
                            last_reminder_time[chat_id] = current_time
                            confirmation.reminder_count += 1
                            logger.info(f"⚠️ Recordatorio bengala enviado a {chat_id}")
                    except Exception as e:
                        logger.error(f"Error enviando recordatorio a {chat_id}: {e}")

                # Esperar el intervalo mínimo antes de verificar de nuevo
                await asyncio.sleep(self.REMINDER_INTERVAL_PRIVATE)

        except asyncio.CancelledError:
            logger.debug(f"Tarea de recordatorio cancelada para {device_id}")
        except Exception as e:
            logger.error(f"Error en tarea de recordatorio para {device_id}: {e}")

    async def _handle_bengala_timeout(self, device_id: str):
        """Maneja el timeout de confirmación de bengala."""
        confirmation = self._bengala_confirmations.get(device_id)
        if not confirmation:
            return

        device_location = self.firebase_manager.get_device_location(device_id) or device_id

        timeout_msg = (
            f"⏰ *TIEMPO AGOTADO*\n\n"
            f"📍 *{device_location}*\n\n"
            f"No se recibió confirmación para disparar bengala.\n"
            f"El sistema continúa armado (sin bengala).\n\n"
            f"Usa `/off` para desactivar el sistema."
        )

        for chat_id in confirmation.chat_ids:
            try:
                await self.send_message(chat_id, timeout_msg, "Markdown", has_keyboard=True)
            except Exception as e:
                logger.error(f"Error enviando mensaje de timeout a {chat_id}: {e}")

        # Limpiar estado
        self._clear_bengala_confirmation(device_id)

    def _clear_bengala_confirmation(self, device_id: str):
        """Limpia el estado de confirmación de bengala para un dispositivo."""
        confirmation = self._bengala_confirmations.pop(device_id, None)
        if confirmation and confirmation.reminder_task:
            confirmation.reminder_task.cancel()
            logger.debug(f"Confirmación de bengala limpiada para {device_id}")

    # ========================================
    # Metodos Anti-Spam
    # ========================================

    def _get_message_hash(self, text: str) -> str:
        """Crea un hash simple del contenido del mensaje para la comparación."""
        # Usar los primeros 256 caracteres para la comparación es suficiente
        return text[:256]

    def _was_recently_sent(self, chat_id: str, text: str, cooldown_seconds: int = 15) -> bool:
        """Verifica si un mensaje idéntico fue enviado recientemente al mismo chat."""
        message_hash = self._get_message_hash(text)
        history_key = f"{chat_id}:{message_hash}"
        
        last_sent_time = self._sent_message_history.get(history_key)
        
        if last_sent_time:
            elapsed = time.time() - last_sent_time
            if elapsed < cooldown_seconds:
                logger.warning(
                    f"Mensaje duplicado a {chat_id} bloqueado. "
                    f"({int(elapsed)}s desde el último envío)"
                )
                return True
        
        # Limpiar historial viejo para que no crezca indefinidamente
        # Esto es simple, una solución más robusta usaría un task periódico
        if len(self._sent_message_history) > 100:
            now = time.time()
            self._sent_message_history = {
                k: v for k, v in self._sent_message_history.items() 
                if now - v < (cooldown_seconds * 2)
            }
            
        self._sent_message_history[history_key] = time.time()
        return False

    # ========================================
    # Metodos Cooldown de Comandos
    # ========================================
    def _is_command_in_cooldown(self, command: str, chat_id: str, cooldown_seconds: int = 5) -> bool:
        """Verifica si un comando de un usuario está en cooldown."""
        cooldown_key = f"{chat_id}:{command}"
        last_used_time = self._command_cooldowns.get(cooldown_key)

        if last_used_time:
            elapsed = time.time() - last_used_time
            if elapsed < cooldown_seconds:
                logger.warning(
                    f"Comando '{command}' de {chat_id} en cooldown. "
                    f"({int(elapsed)}s desde el último uso)"
                )
                return True
        
        self._command_cooldowns[cooldown_key] = time.time()
        return False
        
    # ========================================
    # Metodos para enviar mensajes
    # ========================================

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "",
        keyboard: str = "",
        has_keyboard: bool = False,
        reply_markup: Optional[Any] = None,
        skip_anti_spam: bool = False
    ):
        """Envia un mensaje a un chat de Telegram

        Args:
            chat_id: ID del chat destino
            text: Texto del mensaje
            parse_mode: Modo de parseo ("Markdown" o "")
            keyboard: JSON string de un teclado personalizado
            has_keyboard: Si True, muestra el teclado estándar
            reply_markup: Markup directo (InlineKeyboardMarkup, ReplyKeyboardMarkup, etc.)
                         Si se proporciona, tiene prioridad sobre keyboard/has_keyboard
            skip_anti_spam: Si True, omite la verificación anti-spam (para eventos críticos como alarmas)
        """
        # --- Anti-Spam ---
        if not skip_anti_spam and self._was_recently_sent(chat_id, text):
            return  # Detener si es un mensaje duplicado
        # -----------------
        try:
            pm = ParseMode.MARKDOWN if parse_mode.lower() == "markdown" else None

            # Si se pasa reply_markup directamente, usarlo
            final_markup = reply_markup

            # Si no hay reply_markup, construir desde keyboard/has_keyboard
            if final_markup is None:
                if has_keyboard and keyboard:
                    try:
                        kb_data = json.loads(keyboard)
                        final_markup = ReplyKeyboardMarkup(
                            kb_data,
                            resize_keyboard=True,
                            one_time_keyboard=False
                        )
                    except:
                        final_markup = self._get_keyboard()
                elif has_keyboard:
                    final_markup = self._get_keyboard()

            await self.application.bot.send_message(
                chat_id=int(chat_id),
                text=text,
                parse_mode=pm,
                reply_markup=final_markup
            )
            logger.debug(f"Mensaje enviado a {chat_id}")

        except firebase_admin.exceptions.FirebaseError as e:
            logger.error(f"Error de Firebase al enviar a {chat_id}: {e}")
        except telegram.error.BadRequest as e:
            if 'Chat not found' in e.message:
                logger.warning(f"No se pudo enviar mensaje a {chat_id}: Chat no encontrado. El bot puede que no sea miembro.")
            else:
                logger.error(f"Error de Telegram (BadRequest) enviando a {chat_id}: {e}")
        except Exception as e:
            logger.error(f"Error desconocido enviando mensaje a {chat_id}: {e}")

    async def send_to_all(self, text: str, parse_mode: str = "Markdown"):
        """Envia un mensaje a todos los usuarios autorizados"""
        chat_ids = self.firebase_manager.get_all_chat_ids()
        for chat_id in chat_ids:
            await self.send_message(chat_id, text, parse_mode, has_keyboard=True)

    async def send_alert(self, chat_id: str, alert_text: str):
        """Envia una alerta a un chat"""
        await self.send_message(
            chat_id,
            alert_text,
            parse_mode="Markdown",
            has_keyboard=True
        )

    # ========================================
    # Control del bot
    # ========================================

    async def start(self):
        """Inicia el bot"""
        if not self.application:
            await self.initialize()

        logger.info("Iniciando bot de Telegram...")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        self._running = True
        logger.info("Bot de Telegram iniciado y escuchando")

    async def stop(self):
        """Detiene el bot"""
        if self._running and self.application:
            logger.info("Deteniendo bot de Telegram...")
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self._running = False
            logger.info("Bot de Telegram detenido")

    def is_running(self) -> bool:
        """Verifica si el bot esta corriendo"""
        return self._running
