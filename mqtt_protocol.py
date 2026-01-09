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
    wifi_rssi: int
    heap_free: int
    uptime_sec: int
    lora_sensors_active: int
    auto_schedule_enabled: bool
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
            bengala_enabled=d.get("bengala_enabled", False),
            wifi_rssi=d.get("wifi_rssi", 0),
            heap_free=d.get("heap_free", 0),
            uptime_sec=d.get("uptime_sec", 0),
            lora_sensors_active=d.get("lora_sensors_active", 0),
            auto_schedule_enabled=d.get("auto_schedule_enabled", False),
            location=d.get("location", ""),
            name=d.get("name", "")
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

class TelegramFormatter:
    """Formatea eventos en mensajes para Telegram"""

    @staticmethod
    def format_event(event: MqttEvent, location: str = "") -> str:
        """Convierte un evento MQTT en mensaje de Telegram"""
        event_type = event.event_type
        data = event.data

        if event_type == EventType.SYSTEM_BOOT:
            return f"🔄 *Sistema reiniciado*\n📍 {location or event.device_id}"

        elif event_type == EventType.SYSTEM_ARMED:
            source = data.get("source", "remoto")
            return f"🔒 *Sistema ARMADO*\n📍 {location or event.device_id}\n⚙️ Via: {source}"

        elif event_type == EventType.SYSTEM_DISARMED:
            source = data.get("source", "remoto")
            return f"🔓 *Sistema DESARMADO*\n📍 {location or event.device_id}\n⚙️ Via: {source}"

        elif event_type == EventType.ALARM_TRIGGERED:
            sensor_name = data.get("sensorName", "Manual")
            return (
                f"🚨 *¡ALARMA ACTIVADA!*\n"
                f"📍 {location or event.device_id}\n"
                f"📡 Sensor: {sensor_name}"
            )

        elif event_type == EventType.ALARM_STOPPED:
            return f"✅ *Alarma detenida*\n📍 {location or event.device_id}"

        elif event_type == EventType.BENGALA_ACTIVATED:
            return f"🔥 *Bengala ACTIVADA*\n📍 {location or event.device_id}"

        elif event_type == EventType.BENGALA_DEACTIVATED:
            return f"🔥 *Bengala desactivada*\n📍 {location or event.device_id}"

        elif event_type == EventType.MOVEMENT_DETECTED:
            sensor_name = data.get("sensorName", "Desconocido")
            sensor_location = data.get("location", "")
            return (
                f"🚶 *Movimiento detectado*\n"
                f"📡 {sensor_name}\n"
                f"📍 {sensor_location or location or event.device_id}"
            )

        elif event_type == EventType.DOOR_OPEN:
            sensor_name = data.get("sensorName", "Desconocido")
            sensor_location = data.get("location", "")
            return (
                f"🚪 *Puerta/ventana abierta*\n"
                f"📡 {sensor_name}\n"
                f"📍 {sensor_location or location or event.device_id}"
            )

        elif event_type == EventType.SENSOR_ONLINE:
            sensor_name = data.get("sensorName", "Desconocido")
            return f"📡 Sensor conectado: {sensor_name}"

        elif event_type == EventType.SENSOR_OFFLINE:
            sensor_name = data.get("sensorName", "Desconocido")
            return f"⚠️ Sensor desconectado: {sensor_name}"

        elif event_type == EventType.STATUS_RESPONSE:
            armed = "ARMADO" if data.get("armed", False) else "DESARMADO"
            bengala = "Si" if data.get("bengala_enabled", False) else "No"
            sensors = data.get("sensors_count", 0)
            schedule = "Si" if data.get("auto_schedule_enabled", False) else "No"
            return (
                f"📊 *Estado del Sistema*\n"
                f"📍 {location or event.device_id}\n\n"
                f"🔒 Sistema: *{armed}*\n"
                f"🔥 Bengala: {bengala}\n"
                f"📡 Sensores: {sensors}\n"
                f"⏰ Horario auto: {schedule}"
            )

        else:
            return f"📢 Evento: {event_type}\n📍 {location or event.device_id}"

# ============================================
# UTILIDADES
# ============================================

def get_timestamp() -> int:
    """Retorna timestamp Unix actual"""
    return int(time.time())
