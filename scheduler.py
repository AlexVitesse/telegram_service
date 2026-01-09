"""
Programador automático para el Sistema de Alarma
================================================
Maneja la activación/desactivación automática por horarios.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

SCHEDULE_FILE = "schedule_config.json"


@dataclass
class ScheduleConfig:
    """Configuración de programación automática"""
    enabled: bool = False
    on_hour: int = 22      # Hora de activación (22:00)
    on_minute: int = 0
    off_hour: int = 6      # Hora de desactivación (06:00)
    off_minute: int = 0
    notify_before_minutes: int = 5  # Notificar X minutos antes
    last_on_executed: str = ""      # Fecha de última ejecución on
    last_off_executed: str = ""     # Fecha de última ejecución off

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ScheduleConfig':
        return cls(
            enabled=data.get('enabled', False),
            on_hour=data.get('on_hour', 22),
            on_minute=data.get('on_minute', 0),
            off_hour=data.get('off_hour', 6),
            off_minute=data.get('off_minute', 0),
            notify_before_minutes=data.get('notify_before_minutes', 5),
            last_on_executed=data.get('last_on_executed', ''),
            last_off_executed=data.get('last_off_executed', '')
        )

    def get_on_time(self) -> time:
        return time(self.on_hour, self.on_minute)

    def get_off_time(self) -> time:
        return time(self.off_hour, self.off_minute)

    def format_on_time(self) -> str:
        return f"{self.on_hour:02d}:{self.on_minute:02d}"

    def format_off_time(self) -> str:
        return f"{self.off_hour:02d}:{self.off_minute:02d}"

    def format_on_time_12h(self) -> str:
        hour = self.on_hour
        period = "AM" if hour < 12 else "PM"
        if hour == 0:
            hour = 12
        elif hour > 12:
            hour -= 12
        return f"{hour}:{self.on_minute:02d} {period}"

    def format_off_time_12h(self) -> str:
        hour = self.off_hour
        period = "AM" if hour < 12 else "PM"
        if hour == 0:
            hour = 12
        elif hour > 12:
            hour -= 12
        return f"{hour}:{self.off_minute:02d} {period}"


class Scheduler:
    """Programador automático de activación/desactivación"""

    def __init__(self, data_dir: str = "."):
        self.config_file = Path(data_dir) / SCHEDULE_FILE
        self.config = ScheduleConfig()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Callbacks
        self._on_arm_callback: Optional[Callable[[], Awaitable[None]]] = None
        self._on_disarm_callback: Optional[Callable[[], Awaitable[None]]] = None
        self._on_reminder_callback: Optional[Callable[[str, int], Awaitable[None]]] = None

        # Cargar configuración
        self._load_config()

    def _load_config(self):
        """Carga la configuración desde archivo"""
        if not self.config_file.exists():
            logger.info("No existe archivo de schedule, usando valores por defecto")
            self._save_config()
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.config = ScheduleConfig.from_dict(data)
            logger.info(
                f"Schedule cargado: enabled={self.config.enabled}, "
                f"on={self.config.format_on_time()}, off={self.config.format_off_time()}"
            )
        except Exception as e:
            logger.error(f"Error cargando schedule: {e}")

    def _save_config(self):
        """Guarda la configuración a archivo"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config.to_dict(), f, indent=2)
            logger.debug("Configuración de schedule guardada")
        except Exception as e:
            logger.error(f"Error guardando schedule: {e}")

    # ========================================
    # Configuración
    # ========================================

    def set_enabled(self, enabled: bool):
        """Habilita o deshabilita la programación"""
        self.config.enabled = enabled
        self._save_config()
        logger.info(f"Schedule {'habilitado' if enabled else 'deshabilitado'}")

    def set_on_time(self, hour: int, minute: int) -> bool:
        """Establece la hora de activación"""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return False
        self.config.on_hour = hour
        self.config.on_minute = minute
        self._save_config()
        logger.info(f"Hora de activación: {self.config.format_on_time()}")
        return True

    def set_off_time(self, hour: int, minute: int) -> bool:
        """Establece la hora de desactivación"""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return False
        self.config.off_hour = hour
        self.config.off_minute = minute
        self._save_config()
        logger.info(f"Hora de desactivación: {self.config.format_off_time()}")
        return True

    def is_enabled(self) -> bool:
        """Verifica si la programación está habilitada"""
        return self.config.enabled

    def get_config(self) -> ScheduleConfig:
        """Obtiene la configuración actual"""
        return self.config

    # ========================================
    # Callbacks
    # ========================================

    def on_arm(self, callback: Callable[[], Awaitable[None]]):
        """Registra callback para activación automática"""
        self._on_arm_callback = callback

    def on_disarm(self, callback: Callable[[], Awaitable[None]]):
        """Registra callback para desactivación automática"""
        self._on_disarm_callback = callback

    def on_reminder(self, callback: Callable[[str, int], Awaitable[None]]):
        """Registra callback para recordatorio (action, minutes)"""
        self._on_reminder_callback = callback

    # ========================================
    # Verificación de horarios
    # ========================================

    def _get_today_key(self) -> str:
        """Obtiene la clave del día actual"""
        return datetime.now().strftime("%Y-%m-%d")

    def _should_execute_on(self) -> bool:
        """Verifica si debe ejecutar activación"""
        if not self.config.enabled:
            return False

        now = datetime.now()
        current_time = now.time()
        target_time = self.config.get_on_time()
        today_key = self._get_today_key()

        # Ya se ejecutó hoy
        if self.config.last_on_executed == today_key:
            return False

        # Verificar si es la hora exacta (con margen de 1 minuto)
        current_minutes = current_time.hour * 60 + current_time.minute
        target_minutes = target_time.hour * 60 + target_time.minute

        return current_minutes == target_minutes

    def _should_execute_off(self) -> bool:
        """Verifica si debe ejecutar desactivación"""
        if not self.config.enabled:
            return False

        now = datetime.now()
        current_time = now.time()
        target_time = self.config.get_off_time()
        today_key = self._get_today_key()

        # Ya se ejecutó hoy
        if self.config.last_off_executed == today_key:
            return False

        # Verificar si es la hora exacta
        current_minutes = current_time.hour * 60 + current_time.minute
        target_minutes = target_time.hour * 60 + target_time.minute

        return current_minutes == target_minutes

    def _should_send_on_reminder(self) -> bool:
        """Verifica si debe enviar recordatorio de activación"""
        if not self.config.enabled or self.config.notify_before_minutes <= 0:
            return False

        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        target_minutes = self.config.on_hour * 60 + self.config.on_minute
        reminder_minutes = target_minutes - self.config.notify_before_minutes

        return current_minutes == reminder_minutes

    def _should_send_off_reminder(self) -> bool:
        """Verifica si debe enviar recordatorio de desactivación"""
        if not self.config.enabled or self.config.notify_before_minutes <= 0:
            return False

        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        target_minutes = self.config.off_hour * 60 + self.config.off_minute
        reminder_minutes = target_minutes - self.config.notify_before_minutes

        return current_minutes == reminder_minutes

    # ========================================
    # Loop principal
    # ========================================

    async def _check_schedule(self):
        """Verifica y ejecuta las acciones programadas"""
        # Recordatorios
        if self._should_send_on_reminder() and self._on_reminder_callback:
            await self._on_reminder_callback("on", self.config.notify_before_minutes)

        if self._should_send_off_reminder() and self._on_reminder_callback:
            await self._on_reminder_callback("off", self.config.notify_before_minutes)

        # Activación
        if self._should_execute_on():
            logger.info("⏰ Ejecutando activación automática")
            self.config.last_on_executed = self._get_today_key()
            self._save_config()
            if self._on_arm_callback:
                await self._on_arm_callback()

        # Desactivación
        if self._should_execute_off():
            logger.info("⏰ Ejecutando desactivación automática")
            self.config.last_off_executed = self._get_today_key()
            self._save_config()
            if self._on_disarm_callback:
                await self._on_disarm_callback()

    async def _scheduler_loop(self):
        """Loop principal del scheduler"""
        logger.info("Scheduler iniciado")

        while self._running:
            try:
                await self._check_schedule()
            except Exception as e:
                logger.error(f"Error en scheduler: {e}")

            # Esperar hasta el próximo minuto
            now = datetime.now()
            seconds_to_next_minute = 60 - now.second
            await asyncio.sleep(seconds_to_next_minute)

        logger.info("Scheduler detenido")

    # ========================================
    # Control
    # ========================================

    async def start(self):
        """Inicia el scheduler"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler iniciado")

    async def stop(self):
        """Detiene el scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler detenido")

    # ========================================
    # Utilidades
    # ========================================

    def format_status(self) -> str:
        """Formatea el estado del scheduler para mostrar"""
        lines = ["⏰ *PROGRAMACIÓN AUTOMÁTICA*\n"]

        if self.config.enabled:
            lines.append("🟢 Estado: *HABILITADA*\n")
            lines.append(f"🔒 Activación: {self.config.format_on_time()} ({self.config.format_on_time_12h()})")
            lines.append(f"🔓 Desactivación: {self.config.format_off_time()} ({self.config.format_off_time_12h()})")

            if self.config.notify_before_minutes > 0:
                lines.append(f"\n📢 Recordatorio: {self.config.notify_before_minutes} min antes")
        else:
            lines.append("🔴 Estado: *DESHABILITADA*")

        return "\n".join(lines)

    def parse_time_string(self, time_str: str) -> Optional[tuple]:
        """Parsea una cadena de tiempo HH:MM y retorna (hour, minute)"""
        try:
            if ':' not in time_str:
                return None

            parts = time_str.split(':')
            if len(parts) != 2:
                return None

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None

            return (hour, minute)
        except ValueError:
            return None


# Instancia global
scheduler = Scheduler()
