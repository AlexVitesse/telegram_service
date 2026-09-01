"""
Programador automático para el Sistema de Alarma
================================================
Maneja la activación/desactivación automática por horarios.

Un horario POR DISPOSITIVO: cada device_id tiene su propia ScheduleConfig.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, time
from pathlib import Path
from typing import Optional, Callable, Awaitable, Dict

logger = logging.getLogger(__name__)

SCHEDULE_FILE = "schedule_config.json"


# Mapeo de días: índice -> nombre (compatible con App Ionic)
# 0=Domingo, 1=Lunes, 2=Martes, 3=Miércoles, 4=Jueves, 5=Viernes, 6=Sábado
DAY_NAMES = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
DAY_ABBREV = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']

# Mapeo de abreviaturas a nombres completos (entrada de `/horarios dias`)
DAY_ABBREV_MAP = {
    'D': 'Domingo', 'DOM': 'Domingo',
    'L': 'Lunes', 'LUN': 'Lunes',
    'M': 'Martes', 'MAR': 'Martes',
    'X': 'Miércoles', 'MIE': 'Miércoles', 'MIÉ': 'Miércoles',
    'J': 'Jueves', 'JUE': 'Jueves',
    'V': 'Viernes', 'VIE': 'Viernes',
    'S': 'Sábado', 'SAB': 'Sábado', 'SÁB': 'Sábado',
}


def elegir_por_dispositivo(todos: dict, dispositivos_de) -> Dict[str, dict]:
    """
    De todo /Horarios, qué horario le toca a cada equipo.

    Un mismo equipo puede aparecer bajo varias claves: dos usuarios que lo
    reclaman, o un "system" de su dueño además de una entrada propia.
    Aplicándolos según se iteraba ganaba el último, y ese orden lo decide
    Firebase: el mismo dato podía dejar el equipo armándose un día y quieto al
    siguiente, sin que nadie hubiera tocado nada.

    Criterio, de más a menos peso:

    1. Lo específico gana a "system". Quien nombró el equipo fue más explícito
       que quien configuró "todos los míos".
    2. Habilitado gana a deshabilitado. Si dos personas configuraron el mismo
       equipo, querer que se arme dice más que no querer nada, y evita que una
       entrada vieja de otro deje una alarma sin armar.
    3. El `lastUpdated` más reciente. Falta en bastantes registros, por eso no
       puede ser el primer criterio.
    4. La clave mayor. Arbitrario, pero siempre el mismo: es lo que hace que el
       resultado no dependa del orden en que llegue el diccionario.

    `dispositivos_de(clave)` resuelve a qué equipos alcanza un "system".
    """
    mejor: Dict[str, tuple] = {}

    for clave, datos in (todos or {}).items():
        if not isinstance(datos, dict):
            continue
        devices = datos.get('devices')
        if not isinstance(devices, dict):
            continue

        for device_id, horario in devices.items():
            if not isinstance(horario, dict):
                continue
            if 'activationTime' not in horario or 'deactivationTime' not in horario:
                continue

            es_system = device_id == "system"
            peso = (
                0 if es_system else 1,
                1 if horario.get('enabled') else 0,
                str(horario.get('lastUpdated') or ''),
                str(clave),
            )
            destinos = dispositivos_de(clave) if es_system else [device_id]
            for dev_id in destinos:
                if dev_id not in mejor or peso > mejor[dev_id][0]:
                    mejor[dev_id] = (peso, horario)

    return {dev_id: horario for dev_id, (_, horario) in mejor.items()}


@dataclass
class ScheduleConfig:
    """Configuración de programación automática de UN dispositivo"""
    enabled: bool = False
    on_hour: int = 22      # Hora de activación (22:00)
    on_minute: int = 0
    off_hour: int = 6      # Hora de desactivación (06:00)
    off_minute: int = 0
    days: list = None      # Días activos: ['Domingo', 'Lunes', ...] - None = todos
    notify_before_minutes: int = 5  # Notificar X minutos antes
    last_on_executed: str = ""      # Fecha de última ejecución on
    last_off_executed: str = ""     # Fecha de última ejecución off
    last_on_reminder_sent: str = ""   # Fecha de último recordatorio de activación
    last_off_reminder_sent: str = ""  # Fecha de último recordatorio de desactivación

    def __post_init__(self):
        # Si days es None, activar todos los días por defecto
        if self.days is None:
            self.days = DAY_NAMES.copy()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'ScheduleConfig':
        # Cargar días, si no existe usar todos los días
        days = data.get('days', None)
        if days is None or len(days) == 0:
            days = DAY_NAMES.copy()

        return cls(
            enabled=data.get('enabled', False),
            on_hour=data.get('on_hour', 22),
            on_minute=data.get('on_minute', 0),
            off_hour=data.get('off_hour', 6),
            off_minute=data.get('off_minute', 0),
            days=days,
            notify_before_minutes=data.get('notify_before_minutes', 5),
            last_on_executed=data.get('last_on_executed', ''),
            last_off_executed=data.get('last_off_executed', ''),
            last_on_reminder_sent=data.get('last_on_reminder_sent', ''),
            last_off_reminder_sent=data.get('last_off_reminder_sent', '')
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

    def days_indices(self) -> list:
        """Índices de los días activos (para enviar al ESP32)"""
        return sorted(DAY_NAMES.index(d) for d in self.days if d in DAY_NAMES)

    def format_days(self) -> str:
        """Formatea los días para mostrar (abreviado)"""
        if len(self.days) == 7:
            return "Todos los días"
        if len(self.days) == 0:
            return "Ningún día"

        # Verificar si es L-V (entre semana)
        weekdays = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']
        if sorted(self.days) == sorted(weekdays):
            return "Lun-Vie"

        # Verificar si es fin de semana
        weekend = ['Sábado', 'Domingo']
        if sorted(self.days) == sorted(weekend):
            return "Fin de semana"

        # Lista de abreviaturas, en orden Dom-Sáb
        return ", ".join(DAY_ABBREV[i] for i in self.days_indices())

    def format_status(self) -> str:
        """Formatea el estado del horario para mostrar"""
        lines = ["⏰ *PROGRAMACIÓN AUTOMÁTICA*\n"]

        if self.enabled:
            lines.append("🟢 Estado: *HABILITADA*\n")
            lines.append(f"🔒 Activación: {self.format_on_time()} ({self.format_on_time_12h()})")
            lines.append(f"🔓 Desactivación: {self.format_off_time()} ({self.format_off_time_12h()})")
            lines.append(f"📅 Días: {self.format_days()}")

            if self.notify_before_minutes > 0:
                lines.append(f"\n📢 Recordatorio: {self.notify_before_minutes} min antes")
        else:
            lines.append("🔴 Estado: *DESHABILITADA*")

        return "\n".join(lines)


class Scheduler:
    """Programador automático de activación/desactivación, por dispositivo"""

    def __init__(self, data_dir: str = "."):
        self.config_file = Path(data_dir) / SCHEDULE_FILE
        self.configs: Dict[str, ScheduleConfig] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Callbacks (todos reciben device_id)
        self._on_arm_callback: Optional[Callable[[str], Awaitable[None]]] = None
        self._on_disarm_callback: Optional[Callable[[str], Awaitable[None]]] = None
        self._on_reminder_callback: Optional[Callable[[str, str, int], Awaitable[None]]] = None

        self._load_configs()

    # ========================================
    # Persistencia
    # ========================================

    def _load_configs(self):
        """Carga los horarios desde archivo: {"devices": {device_id: {...}}}"""
        if not self.config_file.exists():
            logger.info("No existe archivo de schedule, se creará al configurar el primer horario")
            return

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            devices = data.get('devices') if isinstance(data, dict) else None
            if devices is None:
                # Formato antiguo: un unico horario global compartido por todos los
                # dispositivos. No sabemos de que dispositivo era, asi que se descarta;
                # el listener de Firebase resincroniza por dispositivo al arrancar.
                logger.warning(
                    "schedule_config.json en formato global antiguo: descartado, "
                    "se resincroniza desde Firebase por dispositivo"
                )
                return

            self.configs = {
                dev_id: ScheduleConfig.from_dict(cfg)
                for dev_id, cfg in devices.items() if isinstance(cfg, dict)
            }
            for dev_id, cfg in self.configs.items():
                logger.info(
                    f"Schedule cargado [{dev_id}]: enabled={cfg.enabled}, "
                    f"on={cfg.format_on_time()}, off={cfg.format_off_time()}"
                )
        except Exception as e:
            logger.error(f"Error cargando schedule: {e}")

    def _save_configs(self):
        """Guarda los horarios a archivo"""
        try:
            payload = {"devices": {d: c.to_dict() for d, c in self.configs.items()}}
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            logger.debug("Configuración de schedule guardada")
        except Exception as e:
            logger.error(f"Error guardando schedule: {e}")

    # ========================================
    # Configuración
    # ========================================

    def cfg(self, device_id: str) -> ScheduleConfig:
        """Horario de un dispositivo (crea uno deshabilitado si no existe)"""
        if device_id not in self.configs:
            self.configs[device_id] = ScheduleConfig()
        return self.configs[device_id]

    def set_enabled(self, device_id: str, enabled: bool):
        """Habilita o deshabilita la programación de un dispositivo"""
        cfg = self.cfg(device_id)
        cfg.enabled = enabled
        # Limpiar flags de recordatorio para permitir nuevos envíos
        cfg.last_on_reminder_sent = ""
        cfg.last_off_reminder_sent = ""
        self._save_configs()
        logger.info(f"Schedule [{device_id}] {'habilitado' if enabled else 'deshabilitado'}")

    def set_on_time(self, device_id: str, hour: int, minute: int) -> bool:
        """Establece la hora de activación"""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return False
        cfg = self.cfg(device_id)
        cfg.on_hour = hour
        cfg.on_minute = minute
        cfg.last_on_reminder_sent = ""
        self._save_configs()
        logger.info(f"Hora de activación [{device_id}]: {cfg.format_on_time()}")
        return True

    def set_off_time(self, device_id: str, hour: int, minute: int) -> bool:
        """Establece la hora de desactivación"""
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return False
        cfg = self.cfg(device_id)
        cfg.off_hour = hour
        cfg.off_minute = minute
        cfg.last_off_reminder_sent = ""
        self._save_configs()
        logger.info(f"Hora de desactivación [{device_id}]: {cfg.format_off_time()}")
        return True

    def set_days(self, device_id: str, days: list) -> bool:
        """
        Establece los días activos.
        Acepta lista de nombres: ['Lunes', 'Martes', ...] o ['L', 'M', ...]
        """
        if not days:
            return False

        normalized_days = []
        for day in days:
            day_upper = day.upper().strip()
            if day_upper in DAY_ABBREV_MAP:
                normalized_days.append(DAY_ABBREV_MAP[day_upper])
            elif day in DAY_NAMES:
                normalized_days.append(day)
            else:
                logger.warning(f"Día no reconocido: {day}")

        if not normalized_days:
            return False

        cfg = self.cfg(device_id)
        cfg.days = normalized_days
        self._save_configs()
        logger.info(f"Días configurados [{device_id}]: {cfg.format_days()}")
        return True

    def set_days_from_indices(self, device_id: str, indices: list) -> bool:
        """
        Establece los días activos desde índices.
        indices: [0, 1, 2, ...] donde 0=Domingo, 1=Lunes, etc.
        """
        days = [DAY_NAMES[i] for i in indices if 0 <= i <= 6]
        if not days:
            return False

        cfg = self.cfg(device_id)
        cfg.days = days
        self._save_configs()
        logger.info(f"Días configurados [{device_id}]: {cfg.format_days()}")
        return True

    def remove(self, device_id: str):
        """Elimina el horario de un dispositivo"""
        if self.configs.pop(device_id, None) is not None:
            self._save_configs()
            logger.info(f"Schedule [{device_id}] eliminado")

    # ========================================
    # Callbacks
    # ========================================

    def on_arm(self, callback: Callable[[str], Awaitable[None]]):
        """Registra callback para activación automática: cb(device_id)"""
        self._on_arm_callback = callback

    def on_disarm(self, callback: Callable[[str], Awaitable[None]]):
        """Registra callback para desactivación automática: cb(device_id)"""
        self._on_disarm_callback = callback

    def on_reminder(self, callback: Callable[[str, str, int], Awaitable[None]]):
        """Registra callback para recordatorio: cb(device_id, action, minutes)"""
        self._on_reminder_callback = callback

    # ========================================
    # Verificación de horarios
    # ========================================

    def _get_today_key(self) -> str:
        """Obtiene la clave del día actual"""
        return datetime.now().strftime("%Y-%m-%d")

    def _is_today_active(self, cfg: ScheduleConfig) -> bool:
        """Verifica si hoy es un día activo para el horario"""
        # weekday() retorna 0=Lunes, pero necesitamos 0=Domingo
        our_day_index = (datetime.now().weekday() + 1) % 7
        return DAY_NAMES[our_day_index] in cfg.days

    def _is_due(self, cfg: ScheduleConfig, kind: str, reminder: bool) -> bool:
        """¿Toca disparar ahora? kind='on'|'off', reminder=True para el aviso previo."""
        if not cfg.enabled:
            return False
        if reminder and cfg.notify_before_minutes <= 0:
            return False
        if not self._is_today_active(cfg):
            return False

        # Ya se disparó hoy
        field_name = f"last_{kind}_{'reminder_sent' if reminder else 'executed'}"
        if getattr(cfg, field_name) == self._get_today_key():
            return False

        if kind == "on":
            target = cfg.on_hour * 60 + cfg.on_minute
        else:
            target = cfg.off_hour * 60 + cfg.off_minute
        if reminder:
            # % 1440: el aviso de un horario a las 00:02 cae en el dia anterior
            target = (target - cfg.notify_before_minutes) % (24 * 60)

        now = datetime.now()
        return now.hour * 60 + now.minute == target

    # ========================================
    # Loop principal
    # ========================================

    async def _check_schedule(self):
        """Verifica y ejecuta las acciones programadas de cada dispositivo"""
        for device_id, cfg in list(self.configs.items()):
            for kind in ("on", "off"):
                # Recordatorio
                if self._is_due(cfg, kind, reminder=True):
                    # Marcar como enviado ANTES de enviar para evitar duplicados
                    setattr(cfg, f"last_{kind}_reminder_sent", self._get_today_key())
                    self._save_configs()
                    if self._on_reminder_callback:
                        logger.info(
                            f"⏰ [{device_id}] recordatorio de {kind.upper()} "
                            f"({cfg.notify_before_minutes} min antes)"
                        )
                        await self._on_reminder_callback(device_id, kind, cfg.notify_before_minutes)
                    else:
                        logger.warning("⏰ Recordatorio pendiente pero no hay callback registrado")

                # Ejecución
                if self._is_due(cfg, kind, reminder=False):
                    accion = "activación" if kind == "on" else "desactivación"
                    logger.info(f"⏰ [{device_id}] ejecutando {accion} automática")
                    setattr(cfg, f"last_{kind}_executed", self._get_today_key())
                    self._save_configs()
                    callback = self._on_arm_callback if kind == "on" else self._on_disarm_callback
                    if callback:
                        await callback(device_id)

    async def _scheduler_loop(self):
        """Loop principal del scheduler"""
        while self._running:
            try:
                await self._check_schedule()
            except Exception as e:
                logger.error(f"Error en scheduler: {e}")

            # Esperar hasta el próximo minuto
            await asyncio.sleep(60 - datetime.now().second)

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

    def parse_time_string(self, time_str: str) -> Optional[tuple]:
        """Parsea una cadena de tiempo HH:MM y retorna (hour, minute)"""
        try:
            hour, minute = (int(p) for p in time_str.split(':'))
        except ValueError:
            return None

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return (hour, minute)


# Instancia global
scheduler = Scheduler()
