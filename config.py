"""
Configuración del servicio Telegram-MQTT Bridge
Carga las credenciales desde variables de entorno (.env)
"""
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

# Obtiene la carpeta donde está este archivo de configuración
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Cargar variables de entorno desde .env
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _get_env(key: str, default: str = "") -> str:
    """Obtiene una variable de entorno o retorna el valor por defecto."""
    return os.getenv(key, default)


def _get_env_bool(key: str, default: bool = False) -> bool:
    """Obtiene una variable de entorno como booleano."""
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def _get_env_int(key: str, default: int = 0) -> int:
    """Obtiene una variable de entorno como entero."""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


@dataclass
class MqttConfig:
    broker: str = _get_env("MQTT_BROKER", "")
    port: int = _get_env_int("MQTT_PORT", 8883)
    username: str = _get_env("MQTT_USER", "")
    password: str = _get_env("MQTT_PASS", "")
    keepalive: int = _get_env_int("MQTT_KEEPALIVE", 60)
    client_id: str = _get_env("MQTT_CLIENT_ID", "alarma_telegram_bridge")
    use_tls: bool = _get_env_bool("MQTT_USE_TLS", True)


@dataclass
class TelegramConfig:
    bot_token: str = _get_env("TELEGRAM_BOT_TOKEN", "")
    admin_chat_id: str = _get_env("TELEGRAM_ADMIN_CHAT_ID", "")


@dataclass
class FirebaseConfig:
    credentials_path: str = os.path.join(
        BASE_DIR,
        _get_env("FIREBASE_CREDENTIALS", "firebase_credentials.json")
    )


@dataclass
class Config:
    mqtt: MqttConfig
    telegram: TelegramConfig
    firebase: FirebaseConfig
    device_id: str = _get_env("DEVICE_ID", "")
    debug: bool = _get_env_bool("DEBUG", True)
    log_file: str = _get_env("LOG_FILE", "alarm_service.log")


# Instancia global de configuración
config = Config(
    mqtt=MqttConfig(),
    telegram=TelegramConfig(),
    firebase=FirebaseConfig(),
)

# Validar que las credenciales críticas estén configuradas
def validate_config() -> list:
    """Valida que las credenciales críticas estén configuradas. Retorna lista de errores."""
    errors = []
    if not config.mqtt.broker:
        errors.append("MQTT_BROKER no está configurado en .env")
    if not config.mqtt.username:
        errors.append("MQTT_USER no está configurado en .env")
    if not config.mqtt.password:
        errors.append("MQTT_PASS no está configurado en .env")
    if not config.telegram.bot_token:
        errors.append("TELEGRAM_BOT_TOKEN no está configurado en .env")
    return errors
