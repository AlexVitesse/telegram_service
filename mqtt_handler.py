"""
Manejador de conexion MQTT para el servicio Telegram Bridge
============================================================
Nueva arquitectura: ESP32 publica eventos genericos, Python maneja usuarios.
Usa Firebase para buscar chats autorizados por dispositivo.
"""
import json
import logging
import ssl
import time
from typing import Callable, Dict, Any, Optional, List, TYPE_CHECKING
import paho.mqtt.client as mqtt

from config import config
from mqtt_protocol import (
    Topics, MqttEvent, MqttTelemetry, MqttCommand, TelegramFormatter,
    EventType, Command, get_timestamp, SensorsList
)
# from firebase_manager import firebase_manager  <- Se elimina esta importación directa
from device_manager import DeviceManager

if TYPE_CHECKING:
    from firebase_manager import FirebaseManager

logger = logging.getLogger(__name__)


class MqttHandler:
    """Manejador de conexion MQTT con el ESP32"""

    def __init__(self, device_manager: DeviceManager, firebase_manager: 'FirebaseManager'):
        self.device_manager = device_manager
        self.firebase_manager = firebase_manager
        self.client = mqtt.Client(
            client_id=config.mqtt.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=False  # Sesión persistente: el broker guarda mensajes mientras estamos offline
        )
        self.connected = False
        self.device_id: Optional[str] = config.device_id or None
        self.device_location: str = ""
        self.last_telemetry: Dict[str, MqttTelemetry] = {}
        self.last_telemetry_time: Dict[str, float] = {}

        # Timestamp del último evento de armado/desarmado por dispositivo
        # Usado para evitar que telemetría vieja sobrescriba el estado
        self.last_arm_event_time: Dict[str, float] = {}

        # Tiempo de salida (bomba) por dispositivo - usado para calcular gracia
        # Se actualiza desde telemetría del ESP32
        self.device_exit_time: Dict[str, int] = {}  # Default 60 segundos

        # Callbacks para eventos
        self._on_event_callback: Optional[Callable] = None
        self._on_telemetry_callback: Optional[Callable] = None
        self._on_reconnect_callback: Optional[Callable] = None
        self._on_sensors_list_callback: Optional[Callable] = None

        # Almacén de lista de sensores por dispositivo
        self.sensors_list: Dict[str, SensorsList] = {}
        self.sensors_list_time: Dict[str, float] = {}

        # Cola de comandos pendientes para dispositivos offline
        # Estructura: {device_id: [(command, args, timestamp), ...]}
        self._pending_commands: Dict[str, List[tuple]] = {}

        # Configurar cliente MQTT
        self._setup_client()

    def _setup_client(self):
        """Configura el cliente MQTT"""
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        if config.mqtt.username:
            self.client.username_pw_set(
                config.mqtt.username,
                config.mqtt.password
            )

        # Configurar TLS si esta habilitado
        if config.mqtt.use_tls:
            self.client.tls_set(tls_version=ssl.PROTOCOL_TLS)
            logger.info("TLS habilitado para conexion MQTT")

    def _on_connect(self, client, userdata, flags, rc):
        """Callback cuando se conecta al broker"""
        if rc == 0:
            logger.info("Conectado al broker MQTT")
            self.connected = True
            self._subscribe_to_topics()
        else:
            logger.error(f"Error conectando a MQTT, codigo: {rc}")
            self.connected = False

    def _on_disconnect(self, client, userdata, rc):
        """Callback cuando se desconecta del broker"""
        logger.warning(f"Desconectado de MQTT (rc={rc})")
        self.connected = False

    def _subscribe_to_topics(self):
        """Suscribe a todos los topics necesarios"""
        # QoS 1 + clean_session=False = el broker guarda mensajes mientras estamos offline
        topics = [
            # ESP32 -> Python
            (Topics.EVENTOS, 1),
            (Topics.TELEMETRIA, 1),
        ]

        for topic, qos in topics:
            self.client.subscribe(topic, qos)
            logger.debug(f"Suscrito a: {topic}")

        logger.info(f"Suscrito a {len(topics)} topics")

    def _on_message(self, client, userdata, msg):
        """Callback para mensajes recibidos"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')

            logger.debug(f"Mensaje recibido: {topic}")

            # Determinar tipo de mensaje y procesar
            if topic == Topics.EVENTOS or topic.startswith(Topics.EVENTOS):
                self._handle_event(payload)
            elif topic == Topics.TELEMETRIA or topic.startswith(Topics.TELEMETRIA):
                self._handle_telemetry(payload)
            else:
                logger.debug(f"Topic no manejado: {topic}")

        except Exception as e:
            logger.error(f"Error procesando mensaje MQTT: {e}")

    def _handle_event(self, payload: str):
        """Procesa mensaje de evento del ESP32"""
        try:
            # Verificar si es una lista de sensores (tiene estructura diferente)
            try:
                d = json.loads(payload)
                if d.get("eventType") == EventType.SENSORS_LIST:
                    self._handle_sensors_list(payload)
                    return
            except:
                pass

            event = MqttEvent.from_json(payload)

            # Actualizar device_id si no estaba configurado
            if not self.device_id and event.device_id:
                self.device_id = event.device_id
                logger.info(f"Device ID detectado: {event.device_id}")

            # Actualizar location desde Firebase o desde el evento
            if event.data.get("location"):
                self.device_location = event.data.get("location")
            elif self.firebase_manager.is_available():
                location = self.firebase_manager.get_device_location(event.device_id)
                if location:
                    self.device_location = location

            # Update device state in DeviceManager
            if event.event_type == EventType.ALARM_TRIGGERED:
                self.device_manager.set_alarming_state(event.device_id, True)
            elif event.event_type == EventType.ALARM_STOPPED or event.event_type == EventType.SYSTEM_DISARMED:
                self.device_manager.set_alarming_state(event.device_id, False)

            if event.event_type == EventType.SYSTEM_ARMED:
                self.device_manager.set_armed_state(event.device_id, True)
                self.last_arm_event_time[event.device_id] = time.time()
            elif event.event_type == EventType.SYSTEM_DISARMED:
                self.device_manager.set_armed_state(event.device_id, False)
                self.last_arm_event_time[event.device_id] = time.time()

            logger.info(f"Evento de {event.device_id}: {event.event_type}")

            if self._on_event_callback:
                self._on_event_callback(event)

        except Exception as e:
            logger.error(f"Error procesando evento: {e}")

    def _handle_telemetry(self, payload: str):
        """Procesa mensaje de telemetria del ESP32"""
        try:
            telemetry = MqttTelemetry.from_json(payload)

            # Actualizar device_id si no estaba configurado
            if not self.device_id and telemetry.device_id:
                self.device_id = telemetry.device_id
                logger.info(f"Device ID detectado: {telemetry.device_id}")

            # Guardar telemetria
            self.last_telemetry[telemetry.device_id] = telemetry
            self.last_telemetry_time[telemetry.device_id] = time.time()

            # Actualizar tiempo de telemetría y verificar reconexión
            reconnected = self.device_manager.update_telemetry_time(telemetry.device_id)
            if reconnected:
                # Procesar comandos pendientes que se encolaron mientras estaba offline
                self.process_pending_commands(telemetry.device_id)

                # Notificar reconexión via callback
                if hasattr(self, '_on_reconnect_callback') and self._on_reconnect_callback:
                    self._on_reconnect_callback(telemetry.device_id)

            # Actualizar tiempo de salida desde telemetría del ESP32
            if telemetry.tiempo_bomba > 0:
                self.device_exit_time[telemetry.device_id] = telemetry.tiempo_bomba

            # Verificar si hubo un evento de armado/desarmado reciente
            # Si lo hubo, no sobrescribir el estado de armado con telemetría vieja
            # Usar el tiempo_bomba del dispositivo + 5 segundos de margen
            last_event_time = self.last_arm_event_time.get(telemetry.device_id, 0)
            exit_time = self.device_exit_time.get(telemetry.device_id, 60)  # Default 60s
            grace_period = exit_time + 5  # tiempo_bomba + 5 segundos de margen
            time_since_event = time.time() - last_event_time
            should_update_armed_state = time_since_event > grace_period

            # Informar al DeviceManager sobre el estado de armado y otra info de telemetria
            if should_update_armed_state:
                self.device_manager.set_armed_state(telemetry.device_id, telemetry.armed)
            else:
                logger.debug(f"Ignorando estado de armado de telemetría (evento reciente hace {time_since_event:.1f}s, gracia={grace_period}s)")

            # Actualizar otros datos de telemetría (excepto is_armed si hay evento reciente)
            device_info = {
                "wifi_rssi": telemetry.wifi_rssi,
                "heap_free": telemetry.heap_free,
                "uptime_sec": telemetry.uptime_sec,
                "lora_sensors_active": telemetry.lora_sensors_active,
                "auto_schedule_enabled": telemetry.auto_schedule_enabled,
                "location": telemetry.location,
                "name": telemetry.name,
            }
            if should_update_armed_state:
                device_info["is_armed"] = telemetry.armed

            # Solo actualizar bengala_enabled si no hay período de gracia activo
            # Nota: 5 min de gracia porque ESP32 actual no envía bengala_enabled correctamente
            device_state = self.device_manager.devices_state.get(telemetry.device_id, {})
            bengala_enabled_set_time = device_state.get("bengala_enabled_set_time", 0)
            if time.time() - bengala_enabled_set_time > 300:  # 5 minutos de gracia
                device_info["bengala_enabled"] = telemetry.bengala_enabled

            self.device_manager.update_device_info(telemetry.device_id, device_info)

            # Sincronizar modo bengala desde telemetría (el ESP32 tiene el valor real)
            self.device_manager.sync_bengala_mode_from_telemetry(
                telemetry.device_id,
                telemetry.bengala_mode
            )

            # ✅ NUEVO: Guardar telemetría en Firebase para que la App pueda leerla
            if self.firebase_manager.is_available():
                self._save_telemetry_to_firebase(telemetry)

            logger.debug(f"Telemetria de {telemetry.device_id}: armed={telemetry.armed}")

            if self._on_telemetry_callback:
                self._on_telemetry_callback(telemetry)

        except Exception as e:
            logger.error(f"Error procesando telemetria: {e}")

    def _handle_sensors_list(self, payload: str):
        """Procesa respuesta de lista de sensores LoRa del ESP32"""
        try:
            sensors_list = SensorsList.from_json(payload)

            # Almacenar la lista de sensores
            self.sensors_list[sensors_list.device_id] = sensors_list
            self.sensors_list_time[sensors_list.device_id] = time.time()

            logger.info(
                f"Lista de sensores de {sensors_list.device_id}: "
                f"{sensors_list.active_sensors}/{sensors_list.total_sensors} activos"
            )

            # Notificar via callback si está registrado
            if self._on_sensors_list_callback:
                self._on_sensors_list_callback(sensors_list)

        except Exception as e:
            logger.error(f"Error procesando lista de sensores: {e}")

    # ========================================
    # Metodos para buscar chats autorizados
    # ========================================

    def get_authorized_chats_for_device(self, device_id: str) -> List[str]:
        """
        Obtiene la lista de chat_ids autorizados para un dispositivo.
        """
        if self.firebase_manager.is_available():
            return self.firebase_manager.get_authorized_chats(device_id)
        
        logger.warning("Firebase no disponible. No se pueden obtener los chats autorizados.")
        return []


    # ========================================
    # Metodos para enviar comandos al ESP32
    # ========================================

    @staticmethod
    def truncate_device_id(device_id: str) -> str:
        """
        Trunca el device_id eliminando los últimos 3 caracteres (_XX).
        Esto es necesario porque el ESP32 trunca su MAC para consistencia con la app.
        Ejemplo: '6C_C8_40_4F_C7_B2' -> '6C_C8_40_4F_C7'
        """
        if device_id and len(device_id) > 3 and device_id[-3] == '_':
            return device_id[:-3]
        return device_id

    def send_command(self, cmd: str, args: Dict[str, Any] = None,
                     device_id: str = None, queue_if_offline: bool = False) -> bool:
        """
        Envia un comando al ESP32 (tanto al ID completo como al truncado).
        Si queue_if_offline=True y el dispositivo está offline, encola el comando.
        """
        target_device = device_id or self.device_id
        if not target_device:
            logger.error("No hay device_id configurado")
            return False

        # Si se debe encolar cuando está offline, verificar estado
        if queue_if_offline and not self.is_device_online(target_device):
            self._queue_pending_command(target_device, cmd, args or {})
            logger.info(f"Dispositivo {target_device} offline. Comando {cmd} encolado para envío posterior.")
            return True  # Retornamos True porque se encoló exitosamente

        command = MqttCommand(
            command=cmd,
            args=args or {}
        )
        payload = command.to_json()

        # Enviar al ID original (completo)
        topic = Topics.comandos(target_device)
        logger.debug(f"Publicando en topic: '{topic}' con payload: {payload}")
        result = self.client.publish(topic, payload, qos=1)
        logger.info(f"Comando enviado: {cmd} -> {target_device}")

        # También enviar al ID truncado si es diferente (fallback para ESP32 con MAC truncada)
        truncated_id = self.truncate_device_id(target_device)
        if truncated_id != target_device:
            topic_truncated = Topics.comandos(truncated_id)
            logger.debug(f"Fallback: Publicando también en topic truncado: '{topic_truncated}'")
            self.client.publish(topic_truncated, payload, qos=1)
            logger.info(f"Comando enviado (truncado): {cmd} -> {truncated_id}")

        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def _queue_pending_command(self, device_id: str, cmd: str, args: Dict[str, Any]):
        """Encola un comando para enviar cuando el dispositivo vuelva online."""
        if device_id not in self._pending_commands:
            self._pending_commands[device_id] = []

        # Solo guardar comandos de configuración (evitar duplicados para set_bengala_mode)
        if cmd == Command.SET_BENGALA_MODE.value:
            # Remover comandos anteriores del mismo tipo
            self._pending_commands[device_id] = [
                (c, a, t) for c, a, t in self._pending_commands[device_id]
                if c != cmd
            ]

        self._pending_commands[device_id].append((cmd, args, time.time()))
        logger.info(f"Comando {cmd} encolado para {device_id}. Total pendientes: {len(self._pending_commands[device_id])}")

    def process_pending_commands(self, device_id: str):
        """
        Procesa y envía comandos pendientes cuando un dispositivo vuelve online.
        Busca también comandos encolados con ID alternativo (completo/truncado).
        Elimina comandos más antiguos que 24 horas.
        """
        # Buscar comandos pendientes tanto por ID exacto como por variantes
        ids_to_check = [device_id]
        truncated = self.truncate_device_id(device_id)
        if truncated != device_id:
            ids_to_check.append(truncated)

        # Buscar IDs completos que empiecen con este ID truncado
        for pending_id in list(self._pending_commands.keys()):
            if pending_id.startswith(device_id) or device_id.startswith(pending_id):
                if pending_id not in ids_to_check:
                    ids_to_check.append(pending_id)

        now = time.time()
        max_age = 24 * 60 * 60  # 24 horas
        total_sent = 0

        for check_id in ids_to_check:
            if check_id not in self._pending_commands:
                continue

            pending = self._pending_commands[check_id]
            if not pending:
                continue

            # Filtrar comandos viejos
            valid_commands = [(cmd, args, ts) for cmd, args, ts in pending if now - ts < max_age]
            expired_count = len(pending) - len(valid_commands)
            if expired_count > 0:
                logger.info(f"Descartados {expired_count} comandos expirados para {check_id}")

            # Enviar comandos válidos (usar device_id truncado para el envío)
            for cmd, args, ts in valid_commands:
                logger.info(f"Enviando comando pendiente a {device_id}: {cmd} (encolado para {check_id})")
                self.send_command(cmd, args, device_id, queue_if_offline=False)
                total_sent += 1

            # Limpiar la cola
            del self._pending_commands[check_id]

        if total_sent > 0:
            logger.info(f"Cola de comandos pendientes para {device_id} procesada. Enviados: {total_sent}")

    def get_pending_commands_count(self, device_id: str = None) -> int:
        """Obtiene el número de comandos pendientes para un dispositivo o todos."""
        if device_id:
            return len(self._pending_commands.get(device_id, []))
        return sum(len(cmds) for cmds in self._pending_commands.values())

    def send_arm(self, device_id: str = None) -> bool:
        """Envia comando para armar el sistema"""
        return self.send_command(Command.ARM.value, device_id=device_id)

    def send_disarm(self, device_id: str = None) -> bool:
        """Envia comando para desarmar el sistema"""
        return self.send_command(Command.DISARM.value, device_id=device_id)

    def send_trigger_alarm(self, device_id: str = None) -> bool:
        """Envia comando para activar alarma"""
        return self.send_command(Command.TRIGGER_ALARM.value, device_id=device_id)

    def send_stop_alarm(self, device_id: str = None) -> bool:
        """Envia comando para detener alarma"""
        return self.send_command(Command.STOP_ALARM.value, device_id=device_id)

    def send_activate_bengala(self, device_id: str = None) -> bool:
        """Envia comando para activar bengala"""
        return self.send_command(Command.ACTIVATE_BENGALA.value, device_id=device_id)

    def send_deactivate_bengala(self, device_id: str = None) -> bool:
        """Envia comando para desactivar bengala"""
        return self.send_command(Command.DEACTIVATE_BENGALA.value, device_id=device_id)

    def send_get_status(self, device_id: str = None) -> bool:
        """Solicita estado del sistema"""
        return self.send_command(Command.GET_STATUS.value, device_id=device_id)

    def send_get_sensors(self, device_id: str = None) -> bool:
        """Solicita lista de sensores LoRa del dispositivo"""
        return self.send_command(Command.GET_SENSORS.value, device_id=device_id)

    def send_beep(self, count: int = 1, device_id: str = None) -> bool:
        """Envia comando para beep"""
        return self.send_command(Command.BEEP.value, {"count": count}, device_id=device_id)

    def send_set_schedule(self, enabled: bool, on_hour: int, on_minute: int,
                          off_hour: int, off_minute: int, days: list = None,
                          device_id: str = None) -> bool:
        """
        Configura horarios automaticos.
        days: Lista de índices de días [0-6] donde 0=Domingo, 1=Lunes, etc.
              Si es None, se envían todos los días.
        """
        # Si no se especifican días, usar todos
        if days is None:
            days = [0, 1, 2, 3, 4, 5, 6]

        args = {
            "enabled": enabled,
            "on_hour": on_hour,
            "on_minute": on_minute,
            "off_hour": off_hour,
            "off_minute": off_minute,
            "days": days
        }
        return self.send_command(Command.SET_SCHEDULE.value, args, device_id=device_id)

    def send_set_exit_time(self, seconds: int, device_id: str = None) -> bool:
        """Configura el tiempo de salida (countdown antes de armar)"""
        return self.send_command(Command.SET_EXIT_TIME.value, {"seconds": seconds}, device_id=device_id)

    def send_set_bengala_mode(self, mode: int, device_id: str = None) -> bool:
        """
        Configura el modo de bengala.
        mode: 0=automático (dispara sin preguntar), 1=con pregunta
        Si el dispositivo está offline, el comando se encola para envío posterior.
        """
        return self.send_command(Command.SET_BENGALA_MODE.value, {"mode": mode}, device_id=device_id, queue_if_offline=True)

    def send_trigger_bengala(self, device_id: str = None) -> bool:
        """
        Dispara la bengala (usado cuando usuario confirma con /si).
        Activa la bengala Y la sirena.
        """
        # Primero activar bengala
        self.send_command(Command.ACTIVATE_BENGALA.value, device_id=device_id)
        # Luego disparar alarma
        return self.send_command(Command.TRIGGER_ALARM.value, device_id=device_id)

    # ========================================
    # Metodos de conexion
    # ========================================

    def connect(self) -> bool:
        """Conecta al broker MQTT"""
        try:
            logger.info(f"Conectando a {config.mqtt.broker}:{config.mqtt.port}")
            self.client.connect(
                config.mqtt.broker,
                config.mqtt.port,
                config.mqtt.keepalive
            )
            return True
        except Exception as e:
            logger.error(f"Error conectando a MQTT: {e}")
            return False

    def start(self):
        """Inicia el loop de MQTT en segundo plano"""
        self.client.loop_start()
        logger.info("Loop MQTT iniciado")

    def stop(self):
        """Detiene el cliente MQTT"""
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("Cliente MQTT detenido")

    def loop_forever(self):
        """Ejecuta el loop de MQTT bloqueante"""
        self.client.loop_forever()

    # ========================================
    # Registro de callbacks
    # ========================================

    def on_event(self, callback: Callable[[MqttEvent], None]):
        """Registra callback para eventos del ESP32"""
        self._on_event_callback = callback

    def on_telemetry(self, callback: Callable[[MqttTelemetry], None]):
        """Registra callback para telemetria"""
        self._on_telemetry_callback = callback

    def on_reconnect(self, callback: Callable[[str], None]):
        """Registra callback para reconexión de dispositivos"""
        self._on_reconnect_callback = callback

    def on_sensors_list(self, callback: Callable[[SensorsList], None]):
        """Registra callback para lista de sensores"""
        self._on_sensors_list_callback = callback

    def get_sensors_list(self, device_id: str = None) -> Optional[SensorsList]:
        """Obtiene la última lista de sensores conocida del dispositivo"""
        target = device_id or self.device_id
        return self.sensors_list.get(target)

    # ========================================
    # Utilidades
    # ========================================

    def is_device_online(self, device_id: str = None, timeout_sec: int = 60) -> bool:
        """Verifica si el dispositivo esta online (busca por ID completo y truncado)"""
        target = device_id or self.device_id
        if not target:
            return False

        # Buscar por ID completo
        if target in self.last_telemetry_time:
            elapsed = time.time() - self.last_telemetry_time[target]
            if elapsed < timeout_sec:
                return True

        # Buscar por ID truncado (fallback)
        truncated = self.truncate_device_id(target)
        if truncated != target and truncated in self.last_telemetry_time:
            elapsed = time.time() - self.last_telemetry_time[truncated]
            if elapsed < timeout_sec:
                return True

        return False

    def get_online_devices(self, timeout_sec: int = 90) -> List[str]:
        """
        Obtiene lista de todos los device_ids que han enviado telemetría recientemente.
        Útil como fallback cuando los dispositivos en Firebase no coinciden con los reales.
        """
        online = []
        now = time.time()
        for device_id, last_time in self.last_telemetry_time.items():
            if now - last_time < timeout_sec:
                online.append(device_id)
        return online

    def get_device_telemetry(self, device_id: str = None) -> Optional[MqttTelemetry]:
        """Obtiene la ultima telemetria conocida del dispositivo"""
        target = device_id or self.device_id
        return self.last_telemetry.get(target)

    def get_device_location(self) -> str:
        """Obtiene la ubicacion del dispositivo"""
        return self.device_location

    def _save_telemetry_to_firebase(self, telemetry: MqttTelemetry):
        """
        Guarda la telemetría del dispositivo en Firebase para que la App pueda leerla.
        Ruta: ESP32/{device_id}/Telemetry/
        """
        try:
            # El ESP32 ya envía el ID truncado, usar directamente sin truncar de nuevo
            device_id = telemetry.device_id

            telemetry_data = {
                "wifi_rssi": telemetry.wifi_rssi,
                "heap_free": telemetry.heap_free,
                "lora_sensors_active": telemetry.lora_sensors_active,
                "uptime_sec": telemetry.uptime_sec,
                "armed": telemetry.armed,
                "bengala_enabled": telemetry.bengala_enabled,
                "bengala_mode": telemetry.bengala_mode,
                "auto_schedule_enabled": telemetry.auto_schedule_enabled,
                "tiempo_bomba": telemetry.tiempo_bomba,
                "tiempo_pre": telemetry.tiempo_pre,
                "timestamp": int(time.time()),
            }

            path = f"ESP32/{device_id}/Telemetry"
            self.firebase_manager.update_data(path, telemetry_data)
            logger.debug(f"Telemetría guardada en Firebase para {device_id}")

        except Exception as e:
            logger.error(f"Error guardando telemetría en Firebase: {e}")

    def format_event_message(self, event: MqttEvent) -> str:
        """Formatea un evento para enviar por Telegram"""
        return TelegramFormatter.format_event(event, self.device_location)
