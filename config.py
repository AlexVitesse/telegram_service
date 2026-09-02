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
    admin_bot_token: str = _get_env("ADMIN_BOT_TOKEN", "")
    # Auto-corregir IDs de supergrupo guardados sin '-' (default true).
    # La app Ionic a veces los guarda mal; este flag aplica un fix defensivo.
    # Setear a "false" si alguna vez sospechas un falso positivo.
    auto_fix_group_id: bool = _get_env_bool("TELEGRAM_AUTO_FIX_GROUP_ID", True)


@dataclass
class FirebaseConfig:
    credentials_path: str = os.path.join(
        BASE_DIR,
        _get_env("FIREBASE_CREDENTIALS", "firebase_credentials.json")
    )


@dataclass
class AIConfig:
    enabled: bool = _get_env_bool("AI_ENABLED", True)
    # LLM Backend: "ollama" (default, local) o "groq" (remoto, fallback)
    llm_backend: str = _get_env("LLM_BACKEND", "ollama")
    # Ollama (principal)
    ollama_base_url: str = _get_env("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = _get_env("OLLAMA_MODEL", "gpt-oss:20b")
    # Modelo para intent parsing (JSON estricto) y para el RAG.
    #
    # Vacio a proposito: `AIHandler` usa el modelo del backend configurado.
    # Antes el default era "llama-3.1-8b-instant", un modelo concreto de Groq
    # que **dejo de existir**: Groq devolvia 404 model_not_found en CADA
    # clasificacion y se caia a la reserva de Ollama sin que nadie lo notara.
    # Alli el modelo local es de razonamiento y deja `content` vacio -su salida
    # va en `thinking`- o se queda sin tokens a mitad del JSON, asi que
    # `parse_intent` devolvia None y las ordenes se iban al RAG: "arma la
    # alarma" contestada con documentacion. Se vieron cuatro veces en
    # produccion antes de encontrarlo.
    #
    # Clavar aqui el nombre de un modelo de un proveedor es apostar a que ese
    # nombre siga vivo. Seguir al backend no: si el backend contesta, este
    # modelo existe. Declaralos en el .env solo si quieres uno distinto para
    # cada tarea, y entonces te toca a ti mantenerlos vivos.
    intent_model: str = _get_env("INTENT_MODEL", "")
    chat_model: str = _get_env("CHAT_MODEL", "")
    # Groq (fallback opcional)
    groq_api_key: str = _get_env("GROQ_API_KEY", "")
    groq_model: str = _get_env("GROQ_MODEL", "llama-3.1-8b-instant")
    # Cuanto se espera a UNA llamada al LLM. 60 s era el default de httpx y solo
    # cubria Ollama; Groq iba sin techo. Para un chat, 20 s ya es mucho: por
    # encima de eso el usuario asume que se rompio. Subelo si vuestro Ollama va
    # justo con la carga real.
    llm_timeout_sec: float = float(_get_env("LLM_TIMEOUT_SEC", "20"))
    # La pila: cuantas llamadas al LLM pueden estar en vuelo a la vez, y
    # cuantas pueden estar esperando turno antes de que la siguiente rebote con
    # "estoy ocupado" en vez de hacer cola hasta que se le acabe el techo.
    # Con Ollama local bajalo a 1: Ollama las serializa igualmente, y encolar
    # aqui al menos permite contestar rapido a quien no cabe.
    llm_max_concurrent: int = _get_env_int("LLM_MAX_CONCURRENT", 2)
    llm_max_cola: int = _get_env_int("LLM_MAX_QUEUE", 8)
    # RAG
    rag_enabled: bool = _get_env_bool("RAG_ENABLED", True)
    rag_max_chunks: int = _get_env_int("RAG_MAX_CHUNKS", 4)
    rag_min_score: float = float(_get_env("RAG_MIN_SCORE", "0.08"))
    # Embeddings (Ollama) para búsqueda semántica
    ollama_embed_model: str = _get_env("OLLAMA_EMBED_MODEL", "nomic-embed-text")
    use_embeddings: bool = _get_env_bool("USE_EMBEDDINGS", True)


@dataclass
class SupportConfig:
    """Datos de contacto humano y enlaces que se muestran al usuario cuando
    el bot no puede resolver una consulta, detecta una queja, o entra
    en modo vendedor. Todos los campos se leen de .env; si quedan
    vacios, no se incluyen en el mensaje."""
    email: str = _get_env("SUPPORT_EMAIL", "")
    phone: str = _get_env("SUPPORT_PHONE", "")
    hours: str = _get_env("SUPPORT_HOURS", "")
    # URLs comerciales: usadas en modo vendedor (usuarios no registrados)
    app_store_url: str = _get_env("SUPPORT_APP_STORE_URL", "")
    landing_url: str = _get_env("SUPPORT_LANDING_URL", "")


@dataclass
class ApiConfig:
    """Endpoint HTTP para que la app pregunte a Senti sin pasar por Telegram."""

    enabled: bool = _get_env_bool("API_ENABLED", False)
    # 127.0.0.1 a proposito: quien lo publica es ngrok o un proxy inverso, no
    # este proceso. Escuchar en 0.0.0.0 lo dejaria abierto a la red del VPS.
    host: str = _get_env("API_HOST", "127.0.0.1")
    port: int = _get_env_int("API_PORT", 8765)
    # Como se identifica quien pregunta:
    #   "firebase"  el ID token de la app. Lo correcto en produccion.
    #   "clave"     una clave compartida en API_CLAVE. Para demos: no hace
    #               falta sesion, pero tampoco queda abierto al primero que
    #               encuentre la URL de ngrok.
    #   "abierto"   sin autenticacion. SOLO en local, nunca detras de ngrok:
    #               cada pregunta gasta LLM y la factura es tuya.
    auth: str = _get_env("API_AUTH", "firebase")
    clave: str = _get_env("API_CLAVE", "")
    # Preguntas por hora y por usuario. Cada una gasta LLM: sin tope, un token
    # valido basta para vaciar la cuota.
    max_por_hora: int = _get_env_int("API_MAX_POR_HORA", 20)
    # Segundos minimos entre dos preguntas del mismo usuario.
    espera_min_seg: float = float(_get_env("API_ESPERA_MIN_SEG", "3"))
    # Techo para TODA la peticion, clasificador y RAG repartiendoselo, en vez de
    # que cada tramo pida el suyo desde LLM_TIMEOUT_SEC como si fuera el unico
    # (asi salian 10 + 45 = 55 s que a nadie le constaban).
    #
    # Tiene que ser ESTRICTAMENTE MENOR que el timeout del cliente, que hoy son
    # 45 s en la app (AbortController en AsistenteChatService.preguntar). Si no,
    # el cliente corta primero y el VPS se queda generando una respuesta que ya
    # nadie va a leer: se paga el modelo y el usuario ve un error igual. Si la
    # app sube o baja su corte, este numero va detras.
    budget_sec: float = float(_get_env("API_BUDGET_SEC", "40"))
    # Origenes que pueden llamar al endpoint desde un navegador (CORS).
    # La app de Capacitor es https://localhost en Android y capacitor://localhost
    # en iOS. "*" vale porque aqui CORS no es la barrera de seguridad -lo es el
    # token, y no se usan cookies-, pero se deja ajustable para poder cerrarlo.
    cors: str = _get_env("API_CORS", "*")
    # La API local del agente de ngrok, para publicar la URL publica en RTDB.
    # Vacio = no se publica.
    ngrok_api: str = _get_env("NGROK_API", "http://127.0.0.1:4040/api/tunnels")
    # Donde se publica esa URL para que la app la lea.
    ruta_url: str = _get_env("API_RUTA_URL", "Config/ai_endpoint")


@dataclass
class Config:
    mqtt: MqttConfig
    telegram: TelegramConfig
    firebase: FirebaseConfig
    ai: AIConfig
    support: SupportConfig
    api: ApiConfig
    device_id: str = _get_env("DEVICE_ID", "")
    debug: bool = _get_env_bool("DEBUG", True)
    log_file: str = _get_env("LOG_FILE", "alarm_service.log")
    # Log JSONL separado con las interacciones Q&A para analisis posterior
    interactions_log_file: str = _get_env(
        "INTERACTIONS_LOG_FILE",
        os.path.join(BASE_DIR, "logs", "ai_interactions.jsonl"),
    )


# Instancia global de configuración
config = Config(
    mqtt=MqttConfig(),
    telegram=TelegramConfig(),
    firebase=FirebaseConfig(),
    ai=AIConfig(),
    support=SupportConfig(),
    api=ApiConfig(),
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
