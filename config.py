"""
Configuración del servicio Telegram-MQTT Bridge
"""
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class MqttConfig:
    broker: str = "9f6abf617b8b46d2a7ac1a975daceb9f.s1.eu.hivemq.cloud"
    port: int = 8883
    username: str = "prueba1"
    password: str = "pedroCandy1"
    keepalive: int = 60
    client_id: str = "alarma_telegram_bridge"
    use_tls: bool = True

@dataclass
class TelegramConfig:
    bot_token: str = "7334625340:AAEDp-wEDzIgDYVsbrO6M1eDuSkngQ6aYFs"
    #bot_token: str = "8409355289:AAHYYxjXrDqbRmmPfQzSXHN6jiKjv0dpsoc"
    # IDs de chat autorizados (se cargarán de la base de datos)
    admin_chat_id: str = ""

#@dataclass
#class FirebaseConfig:
#    credentials_path: str = "firebase_credentials.json"

# Obtiene la carpeta donde está este archivo de configuración
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@dataclass
class FirebaseConfig:
    # Une la carpeta del script con el nombre del archivo
    credentials_path: str = os.path.join(BASE_DIR, "firebase_credentials.json")

@dataclass
class Config:
    mqtt: MqttConfig
    telegram: TelegramConfig
    firebase: FirebaseConfig
    device_id: str = ""  # Se detectará automáticamente del primer mensaje
    debug: bool = True
    log_file: str = "alarm_service.log"

# Instancia global de configuración
config = Config(
    mqtt=MqttConfig(),
    telegram=TelegramConfig(),
    firebase=FirebaseConfig(),
)
