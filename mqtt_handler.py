"""
Manejador de conexion MQTT para el servicio Telegram Bridge
============================================================
Nueva arquitectura: ESP32 publica eventos genericos, Python maneja usuarios.
Usa Firebase para buscar chats autorizados por dispositivo.
"""
import json
import logging
import os
import ssl
import threading
import time
from typing import Callable, Dict, Any, Optional, List, TYPE_CHECKING
import paho.mqtt.client as mqtt

from config import config
from mqtt_protocol import (
    Topics, MqttEvent, MqttTelemetry, MqttCommand, TelegramFormatter,
    EventType, Command, get_timestamp, SensorsList, normalizar_mac
)
# from firebase_manager import firebase_manager  <- Se elimina esta importación directa
from device_manager import DeviceManager

if TYPE_CHECKING:
    from firebase_manager import FirebaseManager

logger = logging.getLogger(__name__)

#: Donde sobrevive la cola de comandos pendientes a un reinicio del VPS. Antes
#: vivia solo en memoria: un reinicio con una central offline perdia el horario
#: que le tocaba recibir (y el "apaga tu horario" de una central borrada).
PENDING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pending_commands.json")

#: Configuracion que gana la ultima y que se puede repetir sin efectos: no
#: caduca. Una central que vuelve a los 3 dias tiene que recibir el horario
#: que se le cambio, no el que tenia. El resto sigue caducando a las 24 h.
COMANDOS_CONFIG = (Command.SET_SCHEDULE.value, Command.SET_BENGALA_MODE.value,
                   Command.SET_EXIT_TIME.value)


class MqttHandler:
    """Manejador de conexion MQTT con el ESP32"""

    #: La cola la tocan el hilo de red de paho (telemetria, arranques) y el
    #: bucle de asyncio y los to_thread de la API (send_command). Reentrante:
    #: vaciar la cola publica, y publicar configuracion descarta pendientes.
    _cola_lock = threading.RLock()

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
        #: A partir de cuantos segundos de silencio de la tarea LoRa se
        #: considera sospechoso. El firmware reinicia a los 60; 30 deja ver el
        #: problema ANTES del reinicio, que es cuando sirve de algo.
        self.LORA_EDAD_SOSPECHOSA = 30

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
        self.pending_file = PENDING_FILE
        self._load_pending()
        # MAC normalizada -> cuando se vio por ultima vez un boton largo o un
        # arranque (ver _handle_event y api_server /equipos/reclamar).
        self.prueba_fisica: Dict[str, float] = {}

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
                logger.info(f"🚨 MQTT: ALARM_TRIGGERED recibido de {event.device_id}")
                logger.info(f"🚨 MQTT: Datos del evento: {event.data}")
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

            # Prueba de que alguien tiene la central en la mano: el boton largo
            # (config_mode_started) o un arranque recien configurado. La usa
            # POST /equipos/reclamar para no dar una central a quien solo
            # conoce su MAC.
            tipo = getattr(event.event_type, "value", event.event_type)
            if tipo in ("config_mode_started", "system_boot"):
                self.prueba_fisica[normalizar_mac(event.device_id)] = time.time()

            # La central arranca con el horario que tenia en NVS; si cambio
            # mientras estaba apagada, se quedaba con el viejo.
            if tipo == "system_boot" and self.firebase_manager.is_available():
                self.firebase_manager.enviar_horario(event.device_id)
                self.firebase_manager.enviar_tiempo_salida(event.device_id)
            if tipo == "system_boot":
                # Esta suscrita (se suscribe antes de anunciar el arranque) aunque
                # aun no haya mandado telemetria: es el primer momento util.
                self.process_pending_commands(event.device_id)

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

            # La central dice que esta viva, pero puede tener la tarea de los
            # sensores colgada. Sin esto no habia forma de enterarse: la
            # telemetria llegaba igual de puntual y todo el mundo la daba por
            # sana. El firmware reinicia solo a los 60 s; esto es para que
            # quede constancia de que paso, y para verlo si el reinicio falla.
            edad = getattr(telemetry, "lora_task_age_sec", -1)
            if edad >= self.LORA_EDAD_SOSPECHOSA:
                logger.error(
                    f"[{telemetry.device_id}] La tarea LoRa lleva {edad} s sin "
                    f"dar senales: la central responde pero puede no estar "
                    f"escuchando a los sensores"
                )

            # Actualizar tiempo de telemetría y verificar reconexión
            reconnected = self.device_manager.update_telemetry_time(telemetry.device_id)
            # Con CUALQUIER telemetria, no solo al "reconectar": la cola empieza
            # a llenarse a los 60 s sin telemetria y la reconexion no se marca
            # hasta los 90 s, asi que un corte de 60-90 s dejaba la cola sin
            # enviar. Tras un reinicio del VPS ni siquiera hay reconexion.
            # Si la cola esta vacia, sale enseguida.
            self.process_pending_commands(telemetry.device_id)
            if reconnected:
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

    def resolve_full_device_id(self, device_id: str) -> str:
        """
        Resuelve un device_id potencialmente truncado al ID completo del dispositivo MQTT real.
        Busca en los dispositivos conocidos del device_manager uno que empiece con el ID dado.
        Ejemplo: '6C_C8_40_4F' -> '6C_C8_40_4F_C7' (si existe)
        Retorna el ID original si no se encuentra coincidencia.
        """
        if not self.device_manager:
            return device_id

        all_ids = self.device_manager.get_all_device_ids()
        for known_id in all_ids:
            # Si un ID conocido empieza con el ID dado y es más largo, es la versión completa
            if known_id != device_id and known_id.startswith(device_id):
                logger.info(f"🔗 ID resuelto: {device_id} -> {known_id} (dispositivo MQTT real)")
                return known_id

        return device_id

    def send_command(self, cmd: str, args: Dict[str, Any] = None,
                     device_id: str = None, queue_if_offline: bool = False) -> bool:
        """
        Envia un comando al ESP32 (tanto al ID completo como al truncado).
        Resuelve IDs truncados al ID real del dispositivo MQTT.
        Si queue_if_offline=True y el dispositivo está offline, encola el comando.
        """
        target_device = device_id or self.device_id
        if not target_device:
            logger.error("No hay device_id configurado")
            return False

        # Resolver ID truncado al ID real del dispositivo MQTT
        resolved_device = self.resolve_full_device_id(target_device)
        if resolved_device != target_device:
            logger.info(f"🔗 Comando {cmd}: resolviendo {target_device} -> {resolved_device}")
            target_device = resolved_device

        # Si se debe encolar cuando está offline, verificar estado
        if queue_if_offline and not self.is_device_online(target_device):
            self._queue_pending_command(target_device, cmd, args or {})
            logger.info(f"Dispositivo {target_device} offline. Comando {cmd} encolado para envío posterior.")
            return True  # Retornamos True porque se encoló exitosamente

        # Se envia directo: un pendiente del mismo tipo es mas viejo y, si se
        # mandase despues al vaciar la cola, pisaria a este.
        if cmd in COMANDOS_CONFIG:
            self._descartar_pendiente(target_device, cmd)

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
        with self._cola_lock:
            cola = self._pending_commands.setdefault(device_id, [])
            # Solo el ultimo de cada configuracion: dos horarios encolados se
            # aplicarian en orden y el primero ya no vale.
            if cmd in COMANDOS_CONFIG:
                cola[:] = [(c, a, t) for c, a, t in cola if c != cmd]
            cola.append((cmd, args, time.time()))
            total = len(cola)
            self._save_pending()
        logger.info(f"Comando {cmd} encolado para {device_id}. Total pendientes: {total}")

    def _claves_cola(self, device_id: str) -> List[str]:
        """Claves de la cola que son la misma central. Por MAC normalizada y no
        por prefijo: con `startswith` una central podia llevarse la cola de otra."""
        mac = normalizar_mac(device_id)
        return [k for k in self._pending_commands if normalizar_mac(k) == mac]

    def _descartar_pendiente(self, device_id: str, cmd: str):
        with self._cola_lock:
            cambio = False
            for clave in self._claves_cola(device_id):
                cola = self._pending_commands[clave]
                quedan = [(c, a, t) for c, a, t in cola if c != cmd]
                if len(quedan) != len(cola):
                    cambio = True
                    if quedan:
                        self._pending_commands[clave] = quedan
                    else:
                        del self._pending_commands[clave]
            if cambio:
                self._save_pending()

    def _load_pending(self):
        try:
            with open(self.pending_file, encoding="utf-8") as f:
                datos = json.load(f).get("devices", {})
            self._pending_commands = {
                d: [(c, a, t) for c, a, t in cmds] for d, cmds in datos.items()
            }
            if self._pending_commands:
                logger.info(f"Cola de comandos pendientes cargada: {self._pending_commands_resumen()}")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"No se pudo leer {self.pending_file}: {e}")

    def _save_pending(self):
        """Se llama con `_cola_lock` tomado: una sola escritura a la vez."""
        # Escribir aparte y renombrar: un corte a mitad no deja el archivo roto.
        tmp = self.pending_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"devices": {d: [list(x) for x in cmds]
                                       for d, cmds in self._pending_commands.items()}}, f)
            os.replace(tmp, self.pending_file)
        except Exception as e:
            logger.error(f"No se pudo guardar {self.pending_file}: {e}")

    def _pending_commands_resumen(self) -> str:
        return ", ".join(f"{d}: {[c for c, _, _ in cmds]}" for d, cmds in self._pending_commands.items())

    def process_pending_commands(self, device_id: str):
        """
        Envia los comandos pendientes de una central (todas las formas de su
        id: 14 o 17 caracteres). De cada configuracion se manda la MAS RECIENTE
        entre todas las variantes. Lo demas caduca a las 24 h.

        Lo que MQTT no acepta se queda en la cola: antes se sacaba antes de
        publicar y, si la publicacion fallaba, el horario se perdia para siempre.
        """
        with self._cola_lock:
            claves = self._claves_cola(device_id)
            if not claves:
                return
            todos = sorted(
                (x for k in claves for x in self._pending_commands.pop(k)),
                key=lambda x: x[2],
            )
            now = time.time()
            max_age = 24 * 60 * 60  # 24 horas (no aplica a COMANDOS_CONFIG)
            ultimo = {}  # cmd de configuracion -> el mas reciente
            enviar = []
            for cmd, args, ts in todos:
                if cmd in COMANDOS_CONFIG:
                    ultimo[cmd] = (cmd, args, ts)
                elif now - ts < max_age:
                    enviar.append((cmd, args, ts))
                else:
                    logger.info(f"Descartado comando expirado para {device_id}: {cmd}")
            enviar = sorted(enviar + list(ultimo.values()), key=lambda x: x[2])

            fallidos = []
            for cmd, args, ts in enviar:
                logger.info(f"Enviando comando pendiente a {device_id}: {cmd}")
                if not self.send_command(cmd, args, device_id, queue_if_offline=False):
                    fallidos.append((cmd, args, ts))
            if fallidos:
                logger.warning(f"{len(fallidos)} comando(s) para {device_id} no se publicaron: siguen en cola")
                self._pending_commands.setdefault(device_id, []).extend(fallidos)
            self._save_pending()

        enviados = len(enviar) - len(fallidos)
        if enviados:
            logger.info(f"Cola de comandos pendientes para {device_id} procesada. Enviados: {enviados}")

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
                          device_id: str = None, queue_if_offline: bool = False) -> bool:
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
        return self.send_command(Command.SET_SCHEDULE.value, args, device_id=device_id,
                                 queue_if_offline=queue_if_offline)

    def send_set_exit_time(self, seconds: int, device_id: str = None) -> bool:
        """
        Configura el tiempo de salida (countdown antes de armar).

        Encolado si la central esta offline: antes se publicaba y ya, el broker
        lo tiraba (sesion limpia) y la central se quedaba con el anterior; el
        7-oct se perdio asi un "10 s" guardado desde la app.
        """
        return self.send_command(Command.SET_EXIT_TIME.value, {"seconds": seconds},
                                 device_id=device_id, queue_if_offline=True)

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

            # Un equipo borrado sigue mandando telemetria cada 30 s, y el
            # `update` le volvia a crear el nodo: el "fantasma" que otra cuenta
            # seguia controlando. Misma guarda que Estado/Alarming.
            if device_id not in (self.firebase_manager._get_all_devices() or {}):
                logger.debug(f"[{device_id}] Telemetria ignorada: el equipo no existe en Firebase")
                return

            # Esto es una lista blanca: lo que no este aqui NO llega a la app,
            # aunque el firmware lo publique. `lora_ok` viajaba en el MQTT desde
            # 65a250d y se quedaba en el camino, asi que la app no tenia forma
            # de saber que una radio estaba muerta.
            telemetry_data = {
                "wifi_rssi": telemetry.wifi_rssi,
                "heap_free": telemetry.heap_free,
                "lora_sensors_active": telemetry.lora_sensors_active,
                "lora_task_age_sec": telemetry.lora_task_age_sec,
                "uptime_sec": telemetry.uptime_sec,
                "armed": telemetry.armed,
                "bengala_enabled": telemetry.bengala_enabled,
                "bengala_mode": telemetry.bengala_mode,
                "auto_schedule_enabled": telemetry.auto_schedule_enabled,
                "tiempo_bomba": telemetry.tiempo_bomba,
                "tiempo_pre": telemetry.tiempo_pre,
                "timestamp": int(time.time()),
            }

            # Solo si el firmware lo manda. Escribir `False` cuando el campo
            # falta convertiria a las centrales con firmware anterior en
            # averiadas a ojos de la app: ausente es "no lo se", no "esta mal".
            if telemetry.lora_ok is not None:
                telemetry_data["lora_ok"] = telemetry.lora_ok

            path = f"ESP32/{device_id}/Telemetry"
            self.firebase_manager.update_data(path, telemetry_data)
            logger.debug(f"Telemetría guardada en Firebase para {device_id}")

        except Exception as e:
            logger.error(f"Error guardando telemetría en Firebase: {e}")

    def format_event_message(self, event: MqttEvent) -> str:
        """Formatea un evento para enviar por Telegram"""
        return TelegramFormatter.format_event(event, self.device_location)
