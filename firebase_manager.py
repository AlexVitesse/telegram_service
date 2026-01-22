"""
Gestor de Firebase para el Sistema de Alarma (Version para Realtime Database)
==============================================================================
Maneja la conexion con Firebase Realtime Database (RTDB) para:
- Buscar dispositivos autorizados por chat_id
- Obtener la informacion de un dispositivo
"""
import logging
import time
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from mqtt_protocol import Command # Importar el Enum de Comandos
from scheduler import scheduler  # Para sincronizar horarios

from config import config # Asegurarse que config tenga la databaseURL

if TYPE_CHECKING:
    from mqtt_handler import MqttHandler

logger = logging.getLogger(__name__)

# Intentar importar firebase_admin
try:
    import firebase_admin
    from firebase_admin import credentials, db
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("firebase_admin no instalado. Ejecuta: pip install firebase-admin")

# --- Estructuras de Datos (similares a antes para compatibilidad interna) ---

class DeviceInfo:
    """Informacion de un dispositivo (adaptado de RTDB)"""
    def __init__(self, device_id: str, location: str, authorized_chats: List[str]):
        self.device_id = device_id
        self.location = location
        self.authorized_chats = authorized_chats

class UserInfo:
    """Informacion de un usuario (adaptado de RTDB)"""
    def __init__(self, chat_id: str, name: str, is_admin: bool, authorized_devices: List[str]):
        self.chat_id = chat_id
        self.name = name
        self.is_admin = is_admin
        self.authorized_devices = authorized_devices

class FirebaseManager:
    """Gestor de conexion con Firebase Realtime Database"""

    # TTL del caché en segundos (60 segundos)
    CACHE_TTL_SECONDS = 60
    # Timeout para detectar listener desconectado (5 minutos)
    LISTENER_TIMEOUT_SECONDS = 300

    def __init__(self):
        self.db = None
        self.initialized = False
        self._credentials_path = config.firebase.credentials_path
        self._database_url = "https://sentinel-c028f-default-rtdb.firebaseio.com/"

        # Cache local con TTL
        self._device_cache: Dict[str, DeviceInfo] = {}
        self._all_devices_cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0  # Timestamp de cuando se cacheó

        self.mqtt_handler: Optional['MqttHandler'] = None

        # Listener monitoring
        self._last_listener_event_time: float = 0
        self._listener_active: bool = False
        self._devices_listener = None
        self._schedules_listener = None

        # Cache de últimos valores para detectar cambios reales (evitar comandos duplicados)
        self._last_known_values: Dict[str, Dict[str, Any]] = {}

    def initialize(self) -> bool:
        """Inicializa la conexion con Firebase RTDB"""
        if not FIREBASE_AVAILABLE:
            logger.error("firebase_admin no esta disponible")
            return False

        if self.initialized:
            return True

        try:
            cred = credentials.Certificate(self._credentials_path)
            firebase_admin.initialize_app(cred, {
                'databaseURL': self._database_url
            })
            self.db = db
            self.initialized = True
            logger.info("Firebase Realtime Database inicializado correctamente")
            return True

        except Exception as e:
            if "already exists" in str(e):
                logger.warning("La app de Firebase ya estaba inicializada. Reutilizando la conexión existente.")
                self.db = db
                self.initialized = True
                return True
            logger.error(f"Error inicializando Firebase Realtime Database: {e}")
            return False

    def is_available(self) -> bool:
        """Verifica si Firebase esta disponible y conectado"""
        return self.initialized and self.db is not None

    def update_data(self, path: str, data: Dict[str, Any]) -> bool:
        """
        Actualiza datos en Firebase en la ruta especificada.
        Usa update() para no sobrescribir otros campos existentes.

        Args:
            path: Ruta en Firebase (ej: "ESP32/device_id/Telemetry")
            data: Diccionario con los datos a actualizar

        Returns:
            True si se actualizó correctamente, False en caso contrario
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para update_data")
            return False

        try:
            ref = self.db.reference(path)
            ref.update(data)
            return True
        except Exception as e:
            logger.error(f"Error en update_data({path}): {e}")
            return False

    def start_app_command_listener(self, mqtt_handler_instance: 'MqttHandler') -> None:
        """
        Inicia un listener en el nodo /ESP32 para capturar comandos
        y actualizaciones de datos desde la app Ionic.
        """
        if not self.is_available():
            logger.error("Firebase no está disponible para iniciar el listener de comandos.")
            return

        self.mqtt_handler = mqtt_handler_instance
        self._start_listeners()

    def _start_listeners(self) -> None:
        """Inicia los listeners de Firebase (interno)."""
        # Cerrar listeners existentes si los hay
        if self._devices_listener:
            try:
                self._devices_listener.close()
            except:
                pass
        if self._schedules_listener:
            try:
                self._schedules_listener.close()
            except:
                pass

        # Listener para comandos de dispositivos (ESP32)
        devices_ref = self.db.reference('ESP32')
        logger.info("Iniciando listener de comandos de la App en Firebase Realtime Database...")
        self._devices_listener = devices_ref.listen(self._app_command_listener)
        logger.info("Listener de comandos de la App iniciado.")

        # Listener para horarios programados
        schedules_ref = self.db.reference('Horarios')
        logger.info("Iniciando listener de horarios en Firebase...")
        self._schedules_listener = schedules_ref.listen(self._schedule_listener)
        logger.info("Listener de horarios iniciado.")

        # Marcar como activo
        self._listener_active = True
        self._last_listener_event_time = time.time()

    def check_listener_health(self) -> bool:
        """
        Verifica si los listeners de Firebase están activos.
        Retorna True si están saludables, False si necesitan reconexión.
        """
        if not self._listener_active:
            return False

        # Si no se ha recibido ningún evento en LISTENER_TIMEOUT_SECONDS, reconectar
        time_since_last_event = time.time() - self._last_listener_event_time
        if time_since_last_event > self.LISTENER_TIMEOUT_SECONDS:
            logger.warning(f"Firebase listener sin eventos por {time_since_last_event:.0f}s - reconectando...")
            return False

        return True

    def reconnect_listeners(self) -> bool:
        """
        Reconecta los listeners de Firebase.
        Retorna True si la reconexión fue exitosa.
        """
        if not self.is_available() or not self.mqtt_handler:
            logger.error("No se puede reconectar: Firebase o MQTT Handler no disponible")
            return False

        try:
            logger.info("Reconectando listeners de Firebase...")
            self._listener_active = False
            self._start_listeners()
            return True
        except Exception as e:
            logger.error(f"Error reconectando listeners de Firebase: {e}")
            return False

    def _update_cache_from_event(self, event) -> None:
        """
        Actualiza el cache local desde un evento del listener de Firebase.
        Esto evita consultas .get() innecesarias ya que el listener mantiene
        el cache actualizado en tiempo real.
        """
        try:
            if event.path == "/" and isinstance(event.data, dict):
                # Evento inicial o reset completo - reemplazar todo el cache
                self._all_devices_cache = event.data
                self._cache_timestamp = time.time()
                logger.debug(f"Cache actualizado desde listener (snapshot completo): {len(event.data)} dispositivos")

            elif event.path == "/" and event.data is None:
                # Todos los datos fueron eliminados
                self._all_devices_cache = {}
                self._cache_timestamp = time.time()
                logger.debug("Cache vaciado desde listener (datos eliminados)")

            elif self._all_devices_cache is not None:
                # Actualización parcial - modificar el cache existente
                parts = event.path.split('/')
                if len(parts) >= 2 and parts[1]:
                    device_id = parts[1]

                    if event.data is None:
                        # Dispositivo o campo eliminado
                        if len(parts) == 2:
                            # Dispositivo completo eliminado
                            if device_id in self._all_devices_cache:
                                del self._all_devices_cache[device_id]
                                logger.debug(f"Cache: dispositivo {device_id} eliminado")
                        elif len(parts) >= 3:
                            # Campo específico eliminado
                            field = parts[2]
                            if device_id in self._all_devices_cache and isinstance(self._all_devices_cache[device_id], dict):
                                if field in self._all_devices_cache[device_id]:
                                    del self._all_devices_cache[device_id][field]
                                    logger.debug(f"Cache: campo {field} eliminado de {device_id}")

                    elif len(parts) == 2:
                        # Actualización de dispositivo (puede ser completa o parcial/patch)
                        if isinstance(event.data, dict):
                            if device_id in self._all_devices_cache and isinstance(self._all_devices_cache[device_id], dict):
                                # MERGE: Mezclar datos existentes con los nuevos (para patches parciales)
                                self._all_devices_cache[device_id].update(event.data)
                                logger.debug(f"Cache: dispositivo {device_id} actualizado (merge)")
                            else:
                                # Dispositivo nuevo, guardar completo
                                self._all_devices_cache[device_id] = event.data
                                logger.debug(f"Cache: dispositivo {device_id} creado")

                    elif len(parts) >= 3:
                        # Actualización de campo específico
                        field = parts[2]
                        if device_id not in self._all_devices_cache:
                            self._all_devices_cache[device_id] = {}
                        if isinstance(self._all_devices_cache[device_id], dict):
                            self._all_devices_cache[device_id][field] = event.data
                            logger.debug(f"Cache: {device_id}.{field} = {event.data}")

                    self._cache_timestamp = time.time()

            else:
                # No hay cache, se cargará en la próxima consulta
                logger.debug("Cache no inicializado, se cargará en próxima consulta")

        except Exception as e:
            logger.error(f"Error actualizando cache desde evento: {e}")
            # En caso de error, invalidar cache para forzar recarga
            self._all_devices_cache = None
            self._cache_timestamp = 0

    def _app_command_listener(self, event) -> None:
        """
        Callback para procesar eventos de Firebase (comandos desde la app).
        Maneja tanto eventos 'put' con path específico como eventos 'patch' con diccionario.
        Actualiza el cache local en lugar de invalidarlo para evitar consultas innecesarias.
        """
        # Actualizar timestamp del último evento recibido
        self._last_listener_event_time = time.time()

        # Actualizar cache desde el listener en lugar de invalidar
        self._update_cache_from_event(event)

        if not self.mqtt_handler:
            logger.warning("MQTT Handler no está disponible para procesar comandos de la App.")
            return

        logger.debug(f"Evento de Firebase recibido: Event Type: {event.event_type}, Path: {event.path}, Data: {event.data}")

        parts = event.path.split('/')
        if len(parts) < 2:
            return

        device_id = parts[1]
        command_key = parts[2] if len(parts) > 2 else ""

        if not device_id:
            logger.warning(f"No se pudo extraer el device_id del path: {event.path}")
            return

        if event.event_type in ['put', 'patch']:
            # Caso 1: Path específico (ej: /device_id/Answer)
            if command_key == 'Answer':
                if event.data is True:
                    logger.info(f"Comando de App: ARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.ARM.value, device_id=device_id)
                elif event.data is False:
                    logger.info(f"Comando de App: DESARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.DISARM.value, device_id=device_id)

            elif command_key == 'DisparoApp' and event.data is not None:
                logger.info(f"Comando de App: DISPARO para {device_id}")
                self.mqtt_handler.send_command(cmd=Command.TRIGGER_ALARM.value, device_id=device_id)

            elif command_key == 'BengalaHab':
                if event.data is True:
                    logger.info(f"Comando de App: HABILITAR BENGALA para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.ACTIVATE_BENGALA.value, device_id=device_id)
                elif event.data is False:
                    logger.info(f"Comando de App: DESHABILITAR BENGALA para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.DEACTIVATE_BENGALA.value, device_id=device_id)

            elif command_key == 'ModoBengala':
                if event.data == 0:
                    logger.info(f"Comando de App: MODO BENGALA AUTOMATICO para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.SET_BENGALA_MODE.value, args={"mode": 0}, device_id=device_id)
                elif event.data == 1:
                    logger.info(f"Comando de App: MODO BENGALA PREGUNTA para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.SET_BENGALA_MODE.value, args={"mode": 1}, device_id=device_id)

            elif command_key == 'Tiempo_Bomba':
                if isinstance(event.data, (int, float)) and event.data >= 10:
                    seconds = int(event.data)
                    logger.info(f"Comando de App: TIEMPO DE SALIDA {seconds}s para {device_id}")
                    self.mqtt_handler.send_set_exit_time(seconds=seconds, device_id=device_id)

            # Caso 2: Patch a nivel dispositivo (ej: path=/device_id, data={'Tiempo_Bomba': 180, ...})
            elif command_key == "" and isinstance(event.data, dict):
                # Inicializar cache de valores para este dispositivo si no existe
                if device_id not in self._last_known_values:
                    self._last_known_values[device_id] = {}

                # Procesar Tiempo_Bomba si viene en el diccionario Y cambió
                if 'Tiempo_Bomba' in event.data:
                    tiempo_bomba = event.data['Tiempo_Bomba']
                    last_tiempo = self._last_known_values[device_id].get('Tiempo_Bomba')
                    if isinstance(tiempo_bomba, (int, float)) and tiempo_bomba >= 10:
                        if last_tiempo != tiempo_bomba:
                            seconds = int(tiempo_bomba)
                            logger.info(f"Comando de App (patch): TIEMPO DE SALIDA {seconds}s para {device_id} (anterior: {last_tiempo})")
                            self.mqtt_handler.send_set_exit_time(seconds=seconds, device_id=device_id)
                            self._last_known_values[device_id]['Tiempo_Bomba'] = tiempo_bomba
                        else:
                            logger.debug(f"Tiempo_Bomba sin cambio para {device_id}: {tiempo_bomba}")

                # Procesar ModoBengala si viene en el diccionario Y cambió
                if 'ModoBengala' in event.data:
                    modo = event.data['ModoBengala']
                    last_modo = self._last_known_values[device_id].get('ModoBengala')
                    if last_modo != modo:
                        if modo == 0:
                            logger.info(f"Comando de App (patch): MODO BENGALA AUTOMATICO para {device_id} (anterior: {last_modo})")
                            self.mqtt_handler.send_command(cmd=Command.SET_BENGALA_MODE.value, args={"mode": 0}, device_id=device_id)
                        elif modo == 1:
                            logger.info(f"Comando de App (patch): MODO BENGALA PREGUNTA para {device_id} (anterior: {last_modo})")
                            self.mqtt_handler.send_command(cmd=Command.SET_BENGALA_MODE.value, args={"mode": 1}, device_id=device_id)
                        self._last_known_values[device_id]['ModoBengala'] = modo
                    else:
                        logger.debug(f"ModoBengala sin cambio para {device_id}: {modo}")

                # Procesar BengalaHab si viene en el diccionario Y cambió
                if 'BengalaHab' in event.data:
                    habilitada = event.data['BengalaHab']
                    last_hab = self._last_known_values[device_id].get('BengalaHab')
                    if last_hab != habilitada:
                        if habilitada is True:
                            logger.info(f"Comando de App (patch): HABILITAR BENGALA para {device_id} (anterior: {last_hab})")
                            self.mqtt_handler.send_command(cmd=Command.ACTIVATE_BENGALA.value, device_id=device_id)
                        elif habilitada is False:
                            logger.info(f"Comando de App (patch): DESHABILITAR BENGALA para {device_id} (anterior: {last_hab})")
                            self.mqtt_handler.send_command(cmd=Command.DEACTIVATE_BENGALA.value, device_id=device_id)
                        self._last_known_values[device_id]['BengalaHab'] = habilitada
                    else:
                        logger.debug(f"BengalaHab sin cambio para {device_id}: {habilitada}")

    def _schedule_listener(self, event) -> None:
        """
        Callback para procesar cambios de horarios programados.
        Path: /Horarios/{userTelegramId}/devices/{deviceMac}
        Data: {activationTime: "22:00", deactivationTime: "07:00", enabled: true, days: [...]}
        """
        # Actualizar timestamp del último evento recibido
        self._last_listener_event_time = time.time()

        if not self.mqtt_handler:
            return

        logger.debug(f"Evento de Horarios: Type={event.event_type}, Path={event.path}, Data={event.data}")

        # Ignorar evento inicial con todos los datos
        if event.path == '/':
            return

        parts = event.path.split('/')
        # Path esperado: /{userTelegramId}/devices/{deviceMac} o /{userTelegramId}/devices/{deviceMac}/{field}
        # parts[0] = '', parts[1] = userTelegramId, parts[2] = 'devices', parts[3] = deviceMac

        if len(parts) < 4 or parts[2] != 'devices':
            return

        device_id = parts[3]
        user_telegram_id = parts[1]  # El ID de Telegram del usuario
        if not device_id:
            return

        # Si es "system", obtener todos los dispositivos del usuario
        if device_id == "system":
            device_ids = self.get_authorized_devices(user_telegram_id)
            if not device_ids:
                logger.warning(f"No se encontraron dispositivos para el usuario {user_telegram_id}")
                return
        else:
            device_ids = [device_id]

        # Caso especial: horario eliminado (Data=None)
        if event.data is None:
            logger.info(f"Horario eliminado para {device_ids}")
            for dev_id in device_ids:
                self.mqtt_handler.send_set_schedule(
                    enabled=False,
                    on_hour=0,
                    on_minute=0,
                    off_hour=0,
                    off_minute=0,
                    device_id=dev_id
                )
            # Deshabilitar scheduler local
            scheduler.config.enabled = False
            scheduler._save_config()
            logger.info("Scheduler local deshabilitado (horario eliminado)")
            return

        # Determinar si es un cambio completo o parcial
        schedule_data = None

        if len(parts) == 4 and isinstance(event.data, dict):
            # Cambio completo del schedule
            schedule_data = event.data
        elif len(parts) == 4 and event.event_type == 'patch' and isinstance(event.data, dict):
            # Patch con múltiples campos
            schedule_data = event.data
        elif len(parts) > 4:
            # Cambio de un campo específico - necesitamos cargar el schedule completo
            # Por ahora solo procesamos cambios completos
            return

        if schedule_data and 'activationTime' in schedule_data and 'deactivationTime' in schedule_data:
            try:
                enabled = schedule_data.get('enabled', False)
                activation_time = schedule_data.get('activationTime', '')
                deactivation_time = schedule_data.get('deactivationTime', '')
                days = schedule_data.get('days', [])  # Lista de días: ['Lunes', 'Martes', ...]
                updated_by = schedule_data.get('lastUpdatedBy', '')

                # Parsear horas (formato "HH:MM")
                on_hour, on_minute = 0, 0
                off_hour, off_minute = 0, 0

                if activation_time and ':' in activation_time:
                    parts_time = activation_time.split(':')
                    on_hour = int(parts_time[0])
                    on_minute = int(parts_time[1])

                if deactivation_time and ':' in deactivation_time:
                    parts_time = deactivation_time.split(':')
                    off_hour = int(parts_time[0])
                    off_minute = int(parts_time[1])

                # Convertir nombres de días a índices (0=Domingo, 1=Lunes, ...)
                day_name_to_index = {
                    'Domingo': 0, 'Lunes': 1, 'Martes': 2, 'Miércoles': 3,
                    'Jueves': 4, 'Viernes': 5, 'Sábado': 6
                }
                days_indices = []
                for day_name in days:
                    if day_name in day_name_to_index:
                        days_indices.append(day_name_to_index[day_name])
                days_indices.sort()

                # Si no hay días configurados, usar todos
                if not days_indices:
                    days_indices = [0, 1, 2, 3, 4, 5, 6]

                # Enviar al ESP32 (a cada dispositivo)
                for dev_id in device_ids:
                    logger.info(f"Comando de App: HORARIO para {dev_id} - Enabled={enabled}, On={on_hour:02d}:{on_minute:02d}, Off={off_hour:02d}:{off_minute:02d}, Days={days_indices}")
                    self.mqtt_handler.send_set_schedule(
                        enabled=enabled,
                        on_hour=on_hour,
                        on_minute=on_minute,
                        off_hour=off_hour,
                        off_minute=off_minute,
                        days=days_indices,
                        device_id=dev_id
                    )

                # Sincronizar con scheduler local de Python (solo si no viene de Telegram)
                if updated_by != "telegram":
                    scheduler.config.enabled = enabled
                    scheduler.config.on_hour = on_hour
                    scheduler.config.on_minute = on_minute
                    scheduler.config.off_hour = off_hour
                    scheduler.config.off_minute = off_minute
                    # Sincronizar días
                    if days:
                        scheduler.config.days = days
                    else:
                        scheduler.config.days = ['Domingo', 'Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado']
                    scheduler._save_config()
                    logger.info(f"Scheduler local sincronizado desde App (días: {scheduler.format_days()})")

            except Exception as e:
                logger.error(f"Error procesando horario: {e}")

    def update_device_state_in_firebase(self, device_id: str, state_payload: Dict[str, Any]):
        """
        Actualiza el estado de un dispositivo en Firebase.
        - is_armed -> /ESP32/{device_id}/Estado (boolean directo para compatibilidad con App)
        - is_alarming -> /ESP32/{device_id}/Alarming (boolean)

        Busca el dispositivo tanto por ID exacto como por variantes (truncado/completo).
        Actualiza TODAS las variantes encontradas para mantener sincronización con la App.
        Solo actualiza si al menos una variante tiene Telegram_ID configurado.
        Usa solo el cache (el listener lo mantiene actualizado).
        """
        if not self.is_available():
            logger.error("Firebase no está disponible para actualizar el estado del dispositivo.")
            return

        try:
            # Función auxiliar para buscar variantes y verificar Telegram_ID
            def find_device_variants(devices: dict) -> tuple:
                device_ids = []
                has_tid = False
                for dev_id, dev_data in devices.items():
                    if not isinstance(dev_data, dict):
                        continue
                    if dev_id.startswith(device_id) or device_id.startswith(dev_id):
                        device_ids.append(dev_id)
                        if dev_data.get('Telegram_ID'):
                            has_tid = True
                return device_ids, has_tid

            # Usar solo el cache (el listener lo mantiene actualizado)
            all_devices = self._get_all_devices()
            device_ids_to_update = []
            has_telegram_id = False

            if all_devices:
                device_ids_to_update, has_telegram_id = find_device_variants(all_devices)

            if not device_ids_to_update:
                logger.warning(f"[{device_id}] Dispositivo no encontrado en Firebase")
                return

            if not has_telegram_id:
                logger.warning(f"[{device_id}] Ninguna variante tiene Telegram_ID - ignorando actualización")
                return

            # Actualizar todas las variantes encontradas
            for dev_id in device_ids_to_update:
                device_ref = self.db.reference(f'ESP32/{dev_id}')

                # Escribir Estado como boolean directo (compatibilidad con App Ionic)
                if "is_armed" in state_payload:
                    device_ref.child('Estado').set(state_payload["is_armed"])
                    logger.info(f"[{dev_id}] Estado actualizado en Firebase: {state_payload['is_armed']}")

                # Escribir Alarming como boolean
                if "is_alarming" in state_payload:
                    device_ref.child('Alarming').set(state_payload["is_alarming"])
                    logger.info(f"[{dev_id}] Alarming actualizado en Firebase: {state_payload['is_alarming']}")

        except Exception as e:
            logger.error(f"Error al actualizar el estado de {device_id} en Firebase: {e}")

    def _is_cache_valid(self) -> bool:
        """
        Verifica si el caché sigue siendo válido.
        Si el listener está activo, el cache siempre es válido (se actualiza por push).
        Si el listener no está activo, usa TTL como fallback.
        """
        if not self._all_devices_cache:
            return False
        # Si el listener está activo, el cache siempre es válido
        if self._listener_active:
            return True
        # Fallback a TTL si el listener no está activo
        elapsed = time.time() - self._cache_timestamp
        return elapsed < self.CACHE_TTL_SECONDS

    def invalidate_cache(self):
        """Invalida el caché de dispositivos (fuerza recarga en próxima consulta)"""
        self._all_devices_cache = None
        self._cache_timestamp = 0
        logger.debug("Caché de dispositivos invalidado manualmente")

    def _get_all_devices(self) -> Optional[Dict[str, Any]]:
        """
        Obtiene todos los dispositivos del nodo /ESP32.
        Usa cache actualizado por el listener si está activo.
        Solo hace .get() a Firebase si el cache no está inicializado o el listener no está activo.
        """
        # Verificar si el caché es válido (listener activo o dentro de TTL)
        if self._is_cache_valid():
            logger.debug(f"Usando cache (listener={'activo' if self._listener_active else 'inactivo'})")
            return self._all_devices_cache

        if not self.is_available():
            return None

        try:
            # Solo llega aquí si: no hay cache Y (listener inactivo O cache expirado)
            logger.info("Consultando Firebase .get() - cache no disponible o listener inactivo")
            ref = self.db.reference('ESP32')
            self._all_devices_cache = ref.get()
            self._cache_timestamp = time.time()
            return self._all_devices_cache
        except Exception as e:
            logger.error(f"Error obteniendo todos los dispositivos de RTDB: {e}")
            return None

    def get_authorized_devices(self, chat_id: str) -> List[str]:
        """
        Obtiene la lista de device_ids autorizados para un chat_id de Telegram.
        Busca en /ESP32 todos los dispositivos donde Telegram_ID o Group_ID coincida.
        Filtra duplicados (IDs truncados vs completos) retornando solo el más corto (truncado).
        """
        if not self.is_available():
            return []

        try:
            all_devices = self._get_all_devices()
            if not all_devices:
                return []

            authorized = []
            chat_id_str = str(chat_id)

            for device_id, device_data in all_devices.items():
                if not isinstance(device_data, dict):
                    continue

                telegram_id = str(device_data.get('Telegram_ID', ''))
                group_id = str(device_data.get('Group_ID', ''))

                if telegram_id == chat_id_str or group_id == chat_id_str:
                    authorized.append(device_id)

            # Filtrar duplicados: si hay ID truncado y completo, quedarse solo con el truncado
            # Ejemplo: ['6C_C8_40_4F_C7', '6C_C8_40_4F_C7_B2'] -> ['6C_C8_40_4F_C7']
            unique_devices = []
            for dev_id in authorized:
                # Verificar si este ID es un prefijo de otro (es el truncado)
                is_truncated = any(
                    other_id != dev_id and other_id.startswith(dev_id)
                    for other_id in authorized
                )
                # Verificar si otro ID es prefijo de este (este es el completo)
                has_truncated_version = any(
                    other_id != dev_id and dev_id.startswith(other_id)
                    for other_id in authorized
                )

                # Solo agregar si es el truncado o si no tiene versión truncada
                if is_truncated or not has_truncated_version:
                    unique_devices.append(dev_id)

            logger.debug(f"Dispositivos autorizados para chat {chat_id}: {unique_devices}")
            return unique_devices

        except Exception as e:
            logger.error(f"Error obteniendo dispositivos autorizados: {e}")
            return []

    def get_authorized_chats(self, device_id: str) -> List[str]:
        """
        Obtiene la lista de chat_ids autorizados para un dispositivo.
        Busca en todas las variantes del device_id (truncado/completo).
        Retorna Telegram_ID y Group_ID si existen.
        Usa solo el cache (el listener lo mantiene actualizado).
        """
        if not self.is_available():
            return []

        try:
            # Función auxiliar para buscar chats en un diccionario de dispositivos
            def find_chats_in_devices(devices: dict) -> set:
                chats = set()
                for dev_id, dev_data in devices.items():
                    if not isinstance(dev_data, dict):
                        continue
                    # Verificar si es el mismo dispositivo (uno es prefijo del otro)
                    if dev_id.startswith(device_id) or device_id.startswith(dev_id):
                        telegram_id = dev_data.get('Telegram_ID')
                        group_id = dev_data.get('Group_ID')
                        if telegram_id:
                            # Manejar IDs concatenados con ||| (bug de la app)
                            telegram_str = str(telegram_id)
                            if '|||' in telegram_str:
                                logger.warning(f"Telegram_ID concatenado detectado para {dev_id}: {telegram_str}")
                                for tid in telegram_str.split('|||'):
                                    if tid.strip():
                                        chats.add(tid.strip())
                            else:
                                chats.add(telegram_str)
                        if group_id:
                            # También manejar por si acaso en Group_ID
                            group_str = str(group_id)
                            if '|||' in group_str:
                                logger.warning(f"Group_ID concatenado detectado para {dev_id}: {group_str}")
                                for gid in group_str.split('|||'):
                                    if gid.strip():
                                        chats.add(gid.strip())
                            else:
                                chats.add(group_str)
                return chats

            # Usar solo el cache (el listener lo mantiene actualizado)
            all_devices = self._get_all_devices()
            if all_devices:
                chats = find_chats_in_devices(all_devices)
                if chats:
                    return list(chats)

            # Si no hay datos en cache, retornar vacío
            # El listener de Firebase debería mantener el cache actualizado
            logger.debug(f"No hay chats en cache para {device_id}")
            return []

        except Exception as e:
            logger.error(f"Error obteniendo chats autorizados para {device_id}: {e}")
            return []

    def get_device_location(self, device_id: str) -> Optional[str]:
        """
        Obtiene la ubicación/nombre de un dispositivo. Busca en todas las variantes.
        Usa solo el cache (el listener lo mantiene actualizado).
        """
        if not self.is_available():
            return None

        try:
            # Usar solo el cache (el listener lo mantiene actualizado)
            all_devices = self._get_all_devices()
            if all_devices:
                for dev_id, dev_data in all_devices.items():
                    if not isinstance(dev_data, dict):
                        continue
                    if dev_id.startswith(device_id) or device_id.startswith(dev_id):
                        nombre = dev_data.get('Nombre')
                        if nombre:
                            return nombre

            # Si no hay datos en cache, retornar valor por defecto
            return 'Desconocido'

        except Exception as e:
            logger.error(f"Error obteniendo ubicación de {device_id}: {e}")
            return None

    def get_device_owner(self, device_id: str) -> Optional[str]:
        """
        Obtiene el Telegram_ID del dueño/administrador de un dispositivo específico.
        Busca en todas las variantes del device_id.
        """
        if not self.is_available():
            return None

        try:
            all_devices = self._get_all_devices()
            if not all_devices:
                return None

            # Buscar en todas las variantes del device_id
            for dev_id, dev_data in all_devices.items():
                if not isinstance(dev_data, dict):
                    continue
                if dev_id.startswith(device_id) or device_id.startswith(dev_id):
                    telegram_id = dev_data.get('Telegram_ID')
                    if telegram_id:
                        return str(telegram_id)

            return None

        except Exception as e:
            logger.error(f"Error obteniendo dueño de {device_id}: {e}")
            return None

    # ========================================
    # Métodos stub para compatibilidad con TelegramBot
    # (Funcionalidades de gestión de usuarios legacy)
    # ========================================

    def get_user(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """Obtiene info de un usuario por chat_id (stub - retorna None)"""
        # En la nueva arquitectura, los usuarios están en los dispositivos
        return None

    def is_user_admin(self, chat_id: str) -> bool:
        """Verifica si un usuario es admin (stub - cualquier usuario autorizado es 'admin')"""
        return len(self.get_authorized_devices(chat_id)) > 0

    def is_group_chat(self, chat_id: str) -> bool:
        """
        Verifica si un chat_id es un grupo (solo notificaciones, no comandos).
        Retorna True si el chat_id aparece SOLO como Group_ID y NO como Telegram_ID.
        """
        if not self.is_available():
            return False

        try:
            all_devices = self._get_all_devices()
            if not all_devices:
                return False

            chat_id_str = str(chat_id)
            is_telegram_id = False
            is_group_id = False

            for device_data in all_devices.values():
                if not isinstance(device_data, dict):
                    continue

                telegram_id = str(device_data.get('Telegram_ID', ''))
                group_id = str(device_data.get('Group_ID', ''))

                # Manejar IDs concatenados con ||| (legacy de la app)
                if '|||' in telegram_id:
                    telegram_ids = [tid.strip() for tid in telegram_id.split('|||') if tid.strip()]
                    if chat_id_str in telegram_ids:
                        is_telegram_id = True
                elif telegram_id == chat_id_str:
                    is_telegram_id = True

                if '|||' in group_id:
                    group_ids = [gid.strip() for gid in group_id.split('|||') if gid.strip()]
                    if chat_id_str in group_ids:
                        is_group_id = True
                elif group_id == chat_id_str:
                    is_group_id = True

            # Verificar si es un ID de grupo real de Telegram (números negativos)
            # Los grupos de Telegram siempre tienen IDs negativos
            # Los usuarios individuales siempre tienen IDs positivos
            try:
                chat_id_int = int(chat_id_str)
                is_telegram_group_id = chat_id_int < 0
            except ValueError:
                is_telegram_group_id = False

            # Es grupo si:
            # 1. El ID es negativo (grupo real de Telegram), O
            # 2. Aparece SOLO como Group_ID y NO como Telegram_ID Y es un grupo real
            # PERO: Si es un ID positivo (usuario individual), NO es grupo aunque esté en Group_ID
            result = is_telegram_group_id and is_group_id and not is_telegram_id
            logger.debug(f"is_group_chat({chat_id_str}): telegram_id={is_telegram_id}, group_id={is_group_id}, is_negative={is_telegram_group_id}, result={result}")
            return result

        except Exception as e:
            logger.error(f"Error verificando si es grupo: {e}")
            return False

    def has_any_admin(self) -> bool:
        """Verifica si hay algún admin configurado (stub - siempre True si hay dispositivos)"""
        all_devices = self._get_all_devices()
        return bool(all_devices)

    def setup_initial_admin(self, chat_id: str, name: str, device_id: str):
        """Configura el primer admin (stub - no hace nada)"""
        logger.info(f"Setup admin stub: {name} ({chat_id}) para {device_id}")

    def get_all_users_formatted(self) -> str:
        """Obtiene lista formateada de usuarios (stub)"""
        return "📋 Lista de usuarios no disponible en esta versión."

    def add_pending_request(self, chat_id: str, name: str, device_id: str):
        """
        Agrega una solicitud de acceso pendiente en Firebase.
        Se guarda en /PendingRequests/{chat_id} con timestamp para expiración.
        Las solicitudes expiran después de 5 minutos.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para agregar solicitud pendiente")
            return

        try:
            pending_ref = self.db.reference(f'PendingRequests/{chat_id}')
            pending_ref.set({
                'name': name,
                'device_id': device_id,
                'timestamp': int(time.time()),
                'expires_at': int(time.time()) + 300  # 5 minutos
            })
            logger.info(f"Solicitud pendiente guardada: {name} ({chat_id}) -> {device_id}")
        except Exception as e:
            logger.error(f"Error guardando solicitud pendiente: {e}")

    def get_all_admin_chat_ids(self) -> List[str]:
        """Obtiene todos los chat_ids de admins (stub - retorna todos los Telegram_IDs)"""
        if not self.is_available():
            return []
        try:
            all_devices = self._get_all_devices()
            if not all_devices:
                return []
            admin_ids = set()
            for device_data in all_devices.values():
                if isinstance(device_data, dict):
                    tid = device_data.get('Telegram_ID')
                    if tid:
                        admin_ids.add(str(tid))
            return list(admin_ids)
        except Exception as e:
            logger.error(f"Error obteniendo admin IDs: {e}")
            return []

    def get_pending_request(self, chat_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una solicitud de acceso pendiente de Firebase.
        Retorna None si no existe o si ha expirado (> 5 minutos).
        Si está expirada, la elimina automáticamente.
        """
        if not self.is_available():
            return None

        try:
            pending_ref = self.db.reference(f'PendingRequests/{chat_id}')
            pending_data = pending_ref.get()

            if not pending_data:
                return None

            # Verificar si ha expirado
            expires_at = pending_data.get('expires_at', 0)
            if time.time() > expires_at:
                # Solicitud expirada, eliminarla
                pending_ref.delete()
                logger.info(f"Solicitud pendiente expirada y eliminada: {chat_id}")
                return None

            return pending_data

        except Exception as e:
            logger.error(f"Error obteniendo solicitud pendiente: {e}")
            return None

    def register_user(self, chat_id: str, name: str):
        """Registra un usuario (stub - no hace nada)"""
        logger.info(f"Registro usuario stub: {name} ({chat_id})")

    def add_authorized_device(self, chat_id: str, device_id: str):
        """Agrega dispositivo autorizado a usuario (stub - no hace nada)"""
        logger.info(f"Autorización stub: {chat_id} -> {device_id}")

    def add_authorized_chat(self, device_id: str, chat_id: str) -> bool:
        """
        Agrega un chat autorizado a un dispositivo.
        Busca coincidencias parciales del device_id (truncado/completo).
        Retorna True si se agregó correctamente.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para agregar chat autorizado")
            return False

        try:
            all_devices = self._get_all_devices()
            if not all_devices:
                logger.warning(f"No hay dispositivos en Firebase para agregar chat")
                return False

            # Buscar dispositivos que coincidan con el ID (parcial o completo)
            matching_devices = []
            for existing_id, dev_data in all_devices.items():
                if not isinstance(dev_data, dict):
                    continue
                if existing_id.startswith(device_id) or device_id.startswith(existing_id):
                    matching_devices.append((existing_id, dev_data))

            if not matching_devices:
                logger.warning(f"Dispositivo {device_id} no encontrado en Firebase")
                return False

            added = False
            for existing_id, device_data in matching_devices:
                device_ref = self.db.reference(f'ESP32/{existing_id}')

                # Si no tiene Telegram_ID, agregarlo ahí
                if not device_data.get('Telegram_ID'):
                    device_ref.child('Telegram_ID').set(chat_id)
                    logger.info(f"Chat {chat_id} agregado a {existing_id} como Telegram_ID")
                    added = True
                # Si ya tiene Telegram_ID pero no Group_ID, agregarlo como Group_ID
                elif not device_data.get('Group_ID'):
                    device_ref.child('Group_ID').set(chat_id)
                    logger.info(f"Chat {chat_id} agregado a {existing_id} como Group_ID")
                    added = True
                else:
                    logger.warning(f"El dispositivo {existing_id} ya tiene Telegram_ID y Group_ID asignados")

            # Invalidar caché para recargar
            self.invalidate_cache()
            return added

        except Exception as e:
            logger.error(f"Error agregando chat autorizado: {e}")
            return False

    def unlink_device_from_user(self, chat_id: str, device_id: str) -> bool:
        """
        Desvincula un dispositivo de un usuario específico.
        Elimina el chat_id de Telegram_ID o Group_ID del dispositivo.
        Retorna True si se desvinculó correctamente.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para desvincular dispositivo")
            return False

        try:
            device_ref = self.db.reference(f'ESP32/{device_id}')
            device_data = device_ref.get()

            if not device_data:
                logger.warning(f"Dispositivo {device_id} no encontrado en Firebase")
                return False

            chat_id_str = str(chat_id)
            unlinked = False

            # Verificar si el chat_id coincide con Telegram_ID
            telegram_id = str(device_data.get('Telegram_ID', ''))
            if telegram_id == chat_id_str:
                device_ref.child('Telegram_ID').delete()
                logger.info(f"Telegram_ID {chat_id} removido de {device_id}")
                unlinked = True

            # Verificar si el chat_id coincide con Group_ID
            group_id = str(device_data.get('Group_ID', ''))
            if group_id == chat_id_str:
                device_ref.child('Group_ID').delete()
                logger.info(f"Group_ID {chat_id} removido de {device_id}")
                unlinked = True

            if unlinked:
                # Invalidar caché
                self.invalidate_cache()
                logger.info(f"Dispositivo {device_id} desvinculado de chat {chat_id}")
                return True
            else:
                logger.warning(f"Chat {chat_id} no estaba vinculado al dispositivo {device_id}")
                return False

        except Exception as e:
            logger.error(f"Error desvinculando dispositivo: {e}")
            return False

    def remove_pending_request(self, chat_id: str):
        """Elimina una solicitud de acceso pendiente de Firebase."""
        if not self.is_available():
            return

        try:
            pending_ref = self.db.reference(f'PendingRequests/{chat_id}')
            pending_ref.delete()
            logger.info(f"Solicitud pendiente eliminada: {chat_id}")
        except Exception as e:
            logger.error(f"Error eliminando solicitud pendiente: {e}")

    def get_all_chat_ids(self) -> List[str]:
        """Obtiene todos los chat_ids registrados"""
        return self.get_all_admin_chat_ids()

    # ========================================
    # Métodos para persistencia de configuración de bengala
    # ========================================

    def get_bengala_mode_from_firebase(self, device_id: str) -> Optional[int]:
        """
        Obtiene el modo de bengala de un dispositivo desde Firebase.
        Returns: 0=automático, 1=con pregunta, None si no existe
        """
        if not self.is_available():
            return None

        try:
            all_devices = self._get_all_devices()
            if not all_devices or device_id not in all_devices:
                return None

            device_data = all_devices.get(device_id, {})
            modo = device_data.get('ModoBengala')
            if modo is not None:
                return int(modo)
            return None

        except Exception as e:
            logger.error(f"Error obteniendo modo bengala de {device_id}: {e}")
            return None

    def set_bengala_mode_in_firebase(self, device_id: str, mode: int, enable_bengala: bool = True):
        """
        Guarda el modo de bengala en Firebase para persistencia.
        mode: 0=automático, 1=con pregunta
        enable_bengala: Si es True, también habilita la bengala (BengalaHab=True)

        Busca y actualiza todos los dispositivos que coincidan con el ID
        (tanto truncado como completo) para mantener consistencia con la App.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para guardar modo bengala")
            return

        try:
            # Obtener todos los dispositivos de ESP32
            esp32_ref = self.db.reference('ESP32')
            all_devices = esp32_ref.get()

            if not all_devices:
                # Si no hay dispositivos, crear con el ID proporcionado
                device_ref = self.db.reference(f'ESP32/{device_id}')
                device_ref.child('ModoBengala').set(mode)
                if enable_bengala:
                    device_ref.child('BengalaHab').set(True)
                logger.info(f"[{device_id}] Modo bengala guardado en Firebase: {mode}, habilitada: {enable_bengala}")
            else:
                # Buscar todos los dispositivos que empiecen con el device_id
                updated_count = 0
                for existing_id in all_devices.keys():
                    # Coincidir si el ID existente empieza con el device_id proporcionado
                    # o si el device_id proporcionado empieza con el ID existente
                    if existing_id.startswith(device_id) or device_id.startswith(existing_id):
                        device_ref = self.db.reference(f'ESP32/{existing_id}')
                        device_ref.child('ModoBengala').set(mode)
                        if enable_bengala:
                            device_ref.child('BengalaHab').set(True)
                        logger.info(f"[{existing_id}] Modo bengala guardado en Firebase: {mode}, habilitada: {enable_bengala}")
                        updated_count += 1

                if updated_count == 0:
                    # Si no se encontró coincidencia, crear con el ID proporcionado
                    device_ref = self.db.reference(f'ESP32/{device_id}')
                    device_ref.child('ModoBengala').set(mode)
                    if enable_bengala:
                        device_ref.child('BengalaHab').set(True)
                    logger.info(f"[{device_id}] Modo bengala guardado en Firebase: {mode}, habilitada: {enable_bengala}")

            # Invalidar caché para que la próxima lectura traiga el valor actualizado
            self.invalidate_cache()
        except Exception as e:
            logger.error(f"Error guardando modo bengala de {device_id} en Firebase: {e}")

    def set_bengala_enabled_in_firebase(self, device_id: str, enabled: bool):
        """
        Guarda el estado de habilitación de bengala en Firebase.
        enabled: True=habilitada, False=deshabilitada

        Busca y actualiza todos los dispositivos que coincidan con el ID.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para guardar estado bengala")
            return

        try:
            esp32_ref = self.db.reference('ESP32')
            all_devices = esp32_ref.get()

            if not all_devices:
                device_ref = self.db.reference(f'ESP32/{device_id}')
                device_ref.child('BengalaHab').set(enabled)
                logger.info(f"[{device_id}] Bengala {'habilitada' if enabled else 'deshabilitada'} en Firebase")
            else:
                updated_count = 0
                for existing_id in all_devices.keys():
                    if existing_id.startswith(device_id) or device_id.startswith(existing_id):
                        device_ref = self.db.reference(f'ESP32/{existing_id}')
                        device_ref.child('BengalaHab').set(enabled)
                        logger.info(f"[{existing_id}] Bengala {'habilitada' if enabled else 'deshabilitada'} en Firebase")
                        updated_count += 1

                if updated_count == 0:
                    device_ref = self.db.reference(f'ESP32/{device_id}')
                    device_ref.child('BengalaHab').set(enabled)
                    logger.info(f"[{device_id}] Bengala {'habilitada' if enabled else 'deshabilitada'} en Firebase")

            self.invalidate_cache()
        except Exception as e:
            logger.error(f"Error guardando estado bengala de {device_id} en Firebase: {e}")


# Instancia singleton para uso global
firebase_manager = FirebaseManager()