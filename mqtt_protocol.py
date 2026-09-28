"""
PROTOCOLO MQTT - ALARMA MODULOS (NUEVA ARQUITECTURA)
=====================================================
El ESP32 publica eventos genericos, Python maneja usuarios y notificaciones.

Topics:
  ESP32 -> Python:
    - dispositivos/eventos (eventos del sistema)
    - dispositivos/estado_telemetria (telemetria periodica)

  Python -> ESP32:
    - dispositivos/comandos/{deviceId} (comandos)
    - dispositivos/configuracion/{deviceId} (configuracion)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
import json
import re
import time
import uuid

# ============================================
# TOPICS
# ============================================

class Topics:
    """Generador de topics MQTT"""

    # Base para todos los topics
    BASE_TOPIC = "dispositivos"

    # ESP32 -> Python (topics generales)
    EVENTOS = "dispositivos/eventos"
    TELEMETRIA = "dispositivos/estado_telemetria"

    # Python -> ESP32 (topics por dispositivo)
    @staticmethod
    def comandos(device_id: str) -> str:
        return f"dispositivos/comandos/{device_id}"

    @staticmethod
    def configuracion(device_id: str) -> str:
        return f"dispositivos/configuracion/{device_id}"

# ============================================
# TIPOS DE EVENTO
# ============================================

class EventType(str, Enum):
    SYSTEM_BOOT = "system_boot"
    SYSTEM_ARMED = "system_armed"
    SYSTEM_DISARMED = "system_disarmed"
    ALARM_TRIGGERED = "alarm_triggered"
    ALARM_STOPPED = "alarm_stopped"
    BENGALA_ACTIVATED = "bengala_activated"
    BENGALA_DEACTIVATED = "bengala_deactivated"
    MOVEMENT_DETECTED = "movement_detected"
    DOOR_OPEN = "door_open"
    SENSOR_ONLINE = "sensor_online"
    SENSOR_OFFLINE = "sensor_offline"
    WIFI_CONNECTED = "wifi_connected"
    WIFI_DISCONNECTED = "wifi_disconnected"
    KEYPAD_ARM = "keypad_arm"
    KEYPAD_DISARM = "keypad_disarm"
    STATUS_RESPONSE = "status_response"
    SENSORS_LIST = "sensors_list"

# ============================================
# COMANDOS
# ============================================

class Command(str, Enum):
    ARM = "arm"
    DISARM = "disarm"
    TRIGGER_ALARM = "trigger_alarm"
    STOP_ALARM = "stop_alarm"
    ACTIVATE_BENGALA = "activate_bengala"
    DEACTIVATE_BENGALA = "deactivate_bengala"
    SET_BENGALA_MODE = "set_bengala_mode"
    GET_STATUS = "get_status"
    GET_SENSORS = "get_sensors"
    SET_SCHEDULE = "set_schedule"
    SET_EXIT_TIME = "set_exit_time"
    BEEP = "beep"

# ============================================
# ESTRUCTURAS DE MENSAJES (ESP32 -> Python)
# ============================================

@dataclass
class MqttEvent:
    """Evento recibido del ESP32"""
    device_id: str
    event_type: str
    data: Dict[str, Any]
    timestamp: int = 0

    @classmethod
    def from_json(cls, payload: str) -> 'MqttEvent':
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Raw payload for MqttEvent: {payload}")
        d = json.loads(payload)
        logger.debug(f"Parsed dictionary for MqttEvent: {d}")
        return cls(
            device_id=d.get("deviceId", ""),
            event_type=d.get("eventType", ""),
            data=d.get("data", {}),
            timestamp=d.get("timestamp", 0)
        )

@dataclass
class MqttTelemetry:
    """Telemetria periodica del ESP32"""
    device_id: str
    timestamp: int
    armed: bool
    alarm_active: bool
    bengala_enabled: bool
    bengala_mode: int  # 0=automático, 1=con pregunta
    wifi_rssi: int
    heap_free: int
    uptime_sec: int
    lora_sensors_active: int
    auto_schedule_enabled: bool
    tiempo_bomba: int = 60  # Tiempo de salida en segundos (default 60)
    tiempo_pre: int = 60    # Tiempo de pre-alarma en segundos (default 60)
    #: Segundos desde la ultima vuelta de la tarea LoRa del ESP32.
    #:
    #: Es lo unico que distingue "viva" de "escuchando". La telemetria la
    #: publica la tarea MQTT y los sensores los atiende la tarea LoRa, en otro
    #: nucleo: con la de LoRa colgada la telemetria seguia saliendo cada 30 s y
    #: todo el sistema -VPS y app- daba la central por sana mientras la alarma
    #: estaba sorda.
    #:
    #: -1 = el firmware no lo manda (version anterior). No es lo mismo que 0.
    lora_task_age_sec: int = -1
    #: Si la radio LoRa llego a inicializar. `None` = el firmware no lo manda.
    #:
    #: La distincion importa y no es cosmetica: `None` significa "no lo se" y
    #: `False` significa "la radio esta muerta". Si se colapsan, las centrales
    #: con firmware anterior -que no publican el campo- se pintan averiadas sin
    #: estarlo. Por eso es Optional y por eso no se escribe cuando falta.
    lora_ok: Optional[bool] = None
    location: str = ""
    name: str = ""

    @classmethod
    def from_json(cls, payload: str) -> 'MqttTelemetry':
        d = json.loads(payload)
        return cls(
            device_id=d.get("deviceId", ""),
            timestamp=d.get("timestamp", 0),
            armed=d.get("armed", False),
            alarm_active=d.get("alarm_active", False),
            bengala_enabled=d.get("bengala_enabled", True),  # Default True - bengala habilitada por defecto
            bengala_mode=d.get("bengala_mode", 1),  # Default 1 = modo pregunta
            wifi_rssi=d.get("wifi_rssi", 0),
            heap_free=d.get("heap_free", 0),
            uptime_sec=d.get("uptime_sec", 0),
            lora_sensors_active=d.get("lora_sensors_active", 0),
            lora_task_age_sec=d.get("lora_task_age_sec", -1),
            lora_ok=d.get("lora_ok"),   # ausente -> None, "no lo se"
            auto_schedule_enabled=d.get("auto_schedule_enabled", False),
            tiempo_bomba=d.get("tiempo_bomba", 60),  # Tiempo de salida desde ESP32
            tiempo_pre=d.get("tiempo_pre", 60),      # Tiempo de pre-alarma desde ESP32
            location=d.get("location", ""),
            name=d.get("name", "")
        )

@dataclass
class SensorInfo:
    """Información de un sensor LoRa individual"""
    sensor_id: str
    name: str
    sensor_type: str  # SM=movimiento, DW=puerta/ventana, TEC=teclado
    active: bool
    rssi: int
    location: str
    last_seen_sec: int  # Segundos desde última comunicación

    @classmethod
    def from_dict(cls, d: dict) -> 'SensorInfo':
        return cls(
            sensor_id=d.get("id", ""),
            name=d.get("name", ""),
            sensor_type=d.get("type", ""),
            active=d.get("active", False),
            rssi=d.get("rssi", 0),
            location=d.get("location", ""),
            last_seen_sec=d.get("lastSeenSec", 0)
        )

    def get_type_icon(self) -> str:
        """Retorna icono según tipo de sensor"""
        icons = {
            "SM": "🚶",   # Sensor movimiento
            "DW": "🚪",   # Puerta/ventana
            "TEC": "⌨️",  # Teclado
            "SIR": "🔊",  # Sirena
            "BEN": "🔥",  # Bengala
        }
        return icons.get(self.sensor_type, "📡")

    def get_type_name(self) -> str:
        """Retorna nombre legible del tipo"""
        names = {
            "SM": "Movimiento",
            "DW": "Puerta/Ventana",
            "TEC": "Teclado",
            "SIR": "Sirena",
            "BEN": "Bengala",
        }
        return names.get(self.sensor_type, "Sensor")

@dataclass
class SensorsList:
    """Lista de sensores LoRa de un dispositivo"""
    device_id: str
    timestamp: int
    sensors: List[SensorInfo]
    total_sensors: int
    active_sensors: int

    @classmethod
    def from_json(cls, payload: str) -> 'SensorsList':
        d = json.loads(payload)
        sensors = [SensorInfo.from_dict(s) for s in d.get("sensors", [])]
        return cls(
            device_id=d.get("deviceId", ""),
            timestamp=d.get("timestamp", 0),
            sensors=sensors,
            total_sensors=d.get("totalSensors", len(sensors)),
            active_sensors=d.get("activeSensors", sum(1 for s in sensors if s.active))
        )

# ============================================
# ESTRUCTURAS DE MENSAJES (Python -> ESP32)
# ============================================

@dataclass
class MqttCommand:
    """Comando enviado al ESP32"""
    command: str
    args: Dict[str, Any] = field(default_factory=dict)
    timestamp: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time())

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "command": self.command,
            "args": self.args
        })

@dataclass
class MqttConfig:
    """Configuracion enviada al ESP32"""
    config_key: str
    config_value: Any
    timestamp: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = int(time.time())

    def to_json(self) -> str:
        return json.dumps({
            "timestamp": self.timestamp,
            "configKey": self.config_key,
            "configValue": self.config_value
        })

# ============================================
# FORMATEADOR DE MENSAJES TELEGRAM
# ============================================

#: Lo que le interesa al usuario. Todo lo demas (system_boot, watchdog_*,
#: config_mode_started, wifi_*...) es tecnico y va solo al administrador:
#: tras un reinicio llegaban 3-4 mensajes que el usuario no sabia leer, tambien
#: a los grupos.
EVENTOS_USUARIO = {
    EventType.SYSTEM_ARMED, EventType.SYSTEM_DISARMED,
    EventType.ALARM_TRIGGERED, EventType.ALARM_STOPPED,
    EventType.BENGALA_ACTIVATED, EventType.BENGALA_DEACTIVATED,
    EventType.MOVEMENT_DETECTED, EventType.DOOR_OPEN,
    EventType.SENSOR_ONLINE, EventType.SENSOR_OFFLINE,
    EventType.KEYPAD_ARM, EventType.KEYPAD_DISARM,
    EventType.STATUS_RESPONSE,
}


def es_evento_tecnico(event_type) -> bool:
    return getattr(event_type, "value", event_type) not in {e.value for e in EVENTOS_USUARIO}


def normalizar_mac(mac: str) -> str:
    """`AA:BB:CC:DD:EE:FF` o `AA_BB_CC_DD_EE_FF` -> `AA_BB_CC_DD_EE`, como formatMac() de la app."""
    mac = str(mac or "").strip().replace(":", "_").upper()
    if len(mac) == 17 and mac[14] == "_":
        return mac[:14]
    return mac


def escape_md(texto: Any) -> str:
    """
    Escapa texto dinamico para el Markdown legacy de Telegram.

    Un `_` suelto (nombre del equipo, `device_id`, tipo de evento) hacia que
    Telegram rechazara el mensaje entero y el aviso se perdia; con dos, salia
    deformado (`watchdog*lora*reboot`).
    """
    return re.sub(r"([_*`\[])", r"\\\1", str(texto))


class TelegramFormatter:
    """Formatea eventos en mensajes para Telegram"""

    SOURCES = {
        "schedule": "Horario",
        "remote": "Remoto",
        "local": "Local",
        "keypad": "Teclado",
        "alexa": "Alexa"
    }

    @staticmethod
    def format_event(event: MqttEvent, location: str = "") -> str:
        """Convierte un evento MQTT en mensaje de Telegram. Todo lo dinamico va escapado."""
        event_type = event.event_type
        data = event.data
        lugar = escape_md(location or event.device_id)

        def via(default: str) -> str:
            source = data.get("source", default)
            return escape_md(TelegramFormatter.SOURCES.get(source, source))

        if event_type == EventType.SYSTEM_BOOT:
            return f"🔄 *Sistema reiniciado*\n📍 {lugar}"

        elif event_type in (EventType.SYSTEM_ARMED, EventType.SYSTEM_DISARMED) and data.get("source") == "boot":
            # El unico mensaje de un reinicio que ve el usuario. Lo tecnico
            # (system_boot, watchdog...) va al administrador.
            estado = "ARMADA" if event_type == EventType.SYSTEM_ARMED else "DESARMADA"
            return f"🔄 *Tu central se reinició*\n📍 {lugar}\nSigue *{estado}*."

        elif event_type == EventType.SYSTEM_ARMED:
            source = data.get("source", "remoto")
            # Cada armado publica dos: al empezar el tiempo de salida
            # (remote/schedule) y al vencer (local, `handleLocalArming`). Con el
            # mismo texto parecia que se habia armado dos veces.
            if source in ("remote", "schedule"):
                return (
                    f"⏳ *Armando…*\n📍 {lugar}\n⚙️ Via: {via('remoto')}\n"
                    f"La protección se activa al terminar el tiempo de salida."
                )
            if source == "local":
                return f"🛡️ *Protección activa*\n📍 {lugar}"
            return f"🔒 *Sistema ARMADO*\n📍 {lugar}\n⚙️ Via: {via('remoto')}"

        elif event_type == EventType.SYSTEM_DISARMED:
            return f"🔓 *Sistema DESARMADO*\n📍 {lugar}\n⚙️ Via: {via('remoto')}"

        elif event_type == EventType.ALARM_TRIGGERED:
            sensor_name = escape_md(data.get("sensorName", "Manual"))
            return (
                f"🚨 *¡ALARMA ACTIVADA!*\n"
                f"📍 {lugar}\n"
                f"📡 Sensor: {sensor_name}"
            )

        elif event_type == EventType.ALARM_STOPPED:
            return f"✅ *Alarma detenida*\n📍 {lugar}"

        elif event_type == EventType.BENGALA_ACTIVATED:
            return f"🔥 *Bengala ACTIVADA*\n📍 {lugar}"

        elif event_type == EventType.BENGALA_DEACTIVATED:
            return f"🔥 *Bengala desactivada*\n📍 {lugar}"

        elif event_type == EventType.MOVEMENT_DETECTED:
            sensor_name = escape_md(data.get("sensorName", "Desconocido"))
            sensor_location = escape_md(data.get("location", "")) or lugar
            return (
                f"🚶 *Movimiento detectado*\n"
                f"📡 {sensor_name}\n"
                f"📍 {sensor_location}"
            )

        elif event_type == EventType.DOOR_OPEN:
            sensor_name = escape_md(data.get("sensorName", "Desconocido"))
            sensor_location = escape_md(data.get("location", "")) or lugar
            return (
                f"🚪 *Puerta/ventana abierta*\n"
                f"📡 {sensor_name}\n"
                f"📍 {sensor_location}"
            )

        elif event_type == EventType.SENSOR_ONLINE:
            sensor_name = escape_md(data.get("sensorName", "Desconocido"))
            return f"📡 Sensor conectado: {sensor_name}"

        elif event_type == EventType.SENSOR_OFFLINE:
            sensor_name = escape_md(data.get("sensorName", "Desconocido"))
            return f"⚠️ Sensor desconectado: {sensor_name}"

        elif event_type == EventType.STATUS_RESPONSE:
            armed = "ARMADO" if data.get("armed", False) else "DESARMADO"
            bengala = "Si" if data.get("bengala_enabled", False) else "No"
            sensors = escape_md(data.get("sensors_count", 0))
            schedule = "Si" if data.get("auto_schedule_enabled", False) else "No"
            return (
                f"📊 *Estado del Sistema*\n"
                f"📍 {lugar}\n\n"
                f"🔒 Sistema: *{armed}*\n"
                f"🔥 Bengala: {bengala}\n"
                f"📡 Sensores: {sensors}\n"
                f"⏰ Horario auto: {schedule}"
            )

        else:
            tipo = getattr(event_type, "value", event_type)
            return f"📢 Evento: {escape_md(tipo)}\n📍 {lugar}"

# ============================================
# UTILIDADES
# ============================================

def get_timestamp() -> int:
    """Retorna timestamp Unix actual"""
    return int(time.time())
