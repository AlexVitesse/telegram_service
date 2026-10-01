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
from mqtt_protocol import Command, normalizar_mac # Importar el Enum de Comandos
from scheduler import scheduler, DAY_NAMES, elegir_por_dispositivo  # Para sincronizar horarios

from config import config # Asegurarse que config tenga la databaseURL
from chat_id_utils import normalize_chat_id, looks_like_stripped_supergroup

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

def lista_macs(datos) -> List[str]:
    """`Usuarios/{uid}/Dispositivos` como lista limpia: lista, dict o texto con comas (cuentas viejas)."""
    if isinstance(datos, list):
        crudas = datos
    elif isinstance(datos, dict):
        crudas = list(datos.values())
    elif isinstance(datos, str):
        crudas = datos.split(",")
    else:
        return []
    return [str(m).strip() for m in crudas if m and str(m).strip()]


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

        # Answer que escribimos nosotros para seguir a Estado: {dev_id: (valor, hora)}
        self._answer_eco: Dict[str, tuple] = {}

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
                # El eco de nuestra propia sincronizacion no es una orden.
                eco = self._answer_eco.pop(device_id, None)
                if eco and eco[0] is event.data and time.time() - eco[1] < 30:
                    return
                if event.data is True:
                    logger.info(f"Comando de App: ARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.ARM.value, device_id=device_id)
                elif event.data is False:
                    logger.info(f"Comando de App: DESARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.DISARM.value, device_id=device_id)

            elif command_key == 'DisparoApp' and event.data is True:
                # Solo disparar cuando DisparoApp cambia a True, no cuando se resetea a False
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

    @staticmethod
    def _parse_schedule_time(time_str: str) -> tuple:
        """Parsea hora en formato HH:MM o YYYY-MM-DDTHH:MM"""
        if not time_str or ':' not in time_str:
            return 0, 0
        if 'T' in time_str:
            time_str = time_str.split('T')[1]
        try:
            parts = time_str.split(':')
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 0, 0

    def _apply_schedule_to_scheduler(self, device_id: str, schedule_data: dict) -> bool:
        """
        Escribe el horario de Firebase en el scheduler local DE ESE dispositivo.
        Devuelve True si hubo cambios.
        """
        cfg = scheduler.cfg(device_id)
        enabled = bool(schedule_data.get('enabled', False))
        on_hour, on_minute = self._parse_schedule_time(schedule_data.get('activationTime', ''))
        off_hour, off_minute = self._parse_schedule_time(schedule_data.get('deactivationTime', ''))
        days = list(schedule_data.get('days') or DAY_NAMES)

        actual = (cfg.enabled, cfg.on_hour, cfg.on_minute, cfg.off_hour, cfg.off_minute, cfg.days)
        nuevo = (enabled, on_hour, on_minute, off_hour, off_minute, days)
        if actual == nuevo:
            # Sin cambios: no tocar los flags o el horario se re-ejecutaria hoy
            return False

        cfg.enabled = enabled
        cfg.on_hour, cfg.on_minute = on_hour, on_minute
        cfg.off_hour, cfg.off_minute = off_hour, off_minute
        cfg.days = days
        # Horario nuevo: limpiar flags para que pueda dispararse hoy
        cfg.last_on_reminder_sent = ""
        cfg.last_off_reminder_sent = ""
        cfg.last_on_executed = ""
        cfg.last_off_executed = ""
        scheduler._save_configs()
        logger.info(
            f"Scheduler [{device_id}] sincronizado desde Firebase: enabled={enabled}, "
            f"on={cfg.format_on_time()}, off={cfg.format_off_time()}, dias={cfg.format_days()}"
        )
        return True

    def _schedule_listener(self, event) -> None:
        """
        Callback de cambios en /Horarios.

        Antes el listener aplicaba "lo ultimo que se escribio" y la carga
        inicial elegia con otro criterio, asi que el VPS y la central podian
        quedarse con horarios distintos segun el orden de las escrituras. Y
        borrar una clave entera (`/Horarios/{clave}`) no se procesaba: sus
        equipos seguian con el horario puesto. Ahora cualquier cambio
        recalcula todo con el mismo criterio que el arranque. /Horarios es
        pequeno: leerlo entero es mas barato que equivocarse.
        """
        self._last_listener_event_time = time.time()

        if not self.mqtt_handler:
            return

        logger.debug(f"Evento de Horarios: Type={event.event_type}, Path={event.path}, Data={event.data}")

        if event.path == '/':
            self._recalcular_horarios(event.data if isinstance(event.data, dict) else {})
        else:
            self._recalcular_horarios()

    def _recalcular_horarios(self, todos: Optional[dict] = None) -> None:
        """
        Elige UN horario por equipo, lo aplica al scheduler y se lo manda a la
        central si cambio. Los equipos que ya no tienen horario (borrado, equipo
        dado de baja, entrada de alguien que no es el dueno) se deshabilitan:
        antes se quedaban armandose solos para siempre.
        """
        if todos is None:
            try:
                todos = self.db.reference('Horarios').get() or {}
            except Exception as e:
                # Sin datos no se decide nada: tomar un fallo de lectura por
                # "no hay horarios" deshabilitaria todas las centrales.
                logger.error(f"No se pudo leer /Horarios, no se recalcula: {e}")
                return

        try:
            elegidos = elegir_por_dispositivo(
                self._filtrar_horarios(todos), self._devices_for_schedule_key
            )
            for dev_id, horario in elegidos.items():
                if self._apply_schedule_to_scheduler(dev_id, horario):
                    self.enviar_horario(dev_id)

            for dev_id in [d for d in list(scheduler.configs) if d not in elegidos]:
                logger.info(f"Horario huerfano de {dev_id}: se deshabilita")
                scheduler.remove(dev_id)
                if self.mqtt_handler:
                    self.mqtt_handler.send_set_schedule(
                        enabled=False, on_hour=0, on_minute=0, off_hour=0, off_minute=0,
                        device_id=dev_id, queue_if_offline=True
                    )
        except Exception as e:
            logger.error(f"Error recalculando horarios: {e}")

    def enviar_horario(self, device_id: str) -> None:
        """
        Manda a la central el horario que tiene el scheduler para ella.

        Se usa al cambiar el horario y cuando la central arranca: sin eso, una
        central que estaba apagada al cambiarlo se quedaba con el viejo en NVS.
        Encola si esta desconectada.
        """
        if not self.mqtt_handler or device_id not in scheduler.configs:
            return
        cfg = scheduler.configs[device_id]
        logger.info(
            f"Horario a {device_id}: enabled={cfg.enabled}, on={cfg.format_on_time()}, "
            f"off={cfg.format_off_time()}, dias={cfg.days_indices()}"
        )
        self.mqtt_handler.send_set_schedule(
            enabled=cfg.enabled,
            on_hour=cfg.on_hour,
            on_minute=cfg.on_minute,
            off_hour=cfg.off_hour,
            off_minute=cfg.off_minute,
            days=cfg.days_indices(),
            device_id=device_id,
            queue_if_offline=True,
        )

    def _nodo(self, mac: str) -> Optional[dict]:
        nodo = (self._get_all_devices() or {}).get(mac)
        return nodo if isinstance(nodo, dict) else None

    def _horario_aplica(self, clave: str, mac: str) -> bool:
        """
        Si la entrada `Horarios/{clave}/devices/{mac}` cuenta.

        - Equipo que ya no existe: no (horario huerfano).
        - Equipo con `ownerUid`: solo si la clave es la del dueno, o su
          Telegram_ID mientras quedan claves viejas por migrar. Antes cualquiera
          que tuviera el equipo en su lista -o en Telegram_ID_2- le ponia
          horario, y asi llegaban recordatorios y armados de equipos ajenos.
        - Equipo sin `ownerUid` (datos sin migrar): como antes.
        """
        nodo = self._nodo(mac)
        if nodo is None:
            return False
        dueno = str(nodo.get("ownerUid") or "")
        if not dueno:
            return True
        return clave == dueno or clave == str(nodo.get("Telegram_ID") or "")

    def _filtrar_horarios(self, todos: dict) -> dict:
        """/Horarios sin las entradas especificas que no cuentan (ver _horario_aplica)."""
        limpio = {}
        for clave, datos in (todos or {}).items():
            devices = datos.get('devices') if isinstance(datos, dict) else None
            if not isinstance(devices, dict):
                continue
            validos = {
                dev: h for dev, h in devices.items()
                if dev == "system" or self._horario_aplica(str(clave), dev)
            }
            if validos:
                limpio[clave] = {"devices": validos}
        return limpio

    def update_device_state_in_firebase(self, device_id: str, state_payload: Dict[str, Any]):
        """
        Actualiza el estado de un dispositivo en Firebase.
        - is_armed -> /ESP32/{device_id}/Estado (boolean directo para compatibilidad con App)
        - is_alarming -> /ESP32/{device_id}/Alarming (boolean)

        Busca el dispositivo tanto por ID exacto como por variantes (truncado/completo).
        Actualiza TODAS las variantes encontradas para mantener sincronización con la App.
        Escribe solo las que no coincidan ya con el valor: se compara contra el
        cache de la RTDB, que mantiene el listener, no contra lo que creemos.
        """
        if not self.is_available():
            logger.error("Firebase no está disponible para actualizar el estado del dispositivo.")
            return

        try:
            # Usar solo el cache (el listener lo mantiene actualizado)
            all_devices = self._get_all_devices() or {}
            variantes = {
                dev_id: dev_data
                for dev_id, dev_data in all_devices.items()
                if isinstance(dev_data, dict)
                and (dev_id.startswith(device_id) or device_id.startswith(dev_id))
            }

            if not variantes:
                logger.warning(f"[{device_id}] Dispositivo no encontrado en Firebase")
                return

            # Aqui habia una guarda que se saltaba la escritura si ninguna
            # variante tenia `Telegram_ID`. Hacia que el estado que ve la APP
            # dependiera de si el equipo tiene TELEGRAM configurado, que no
            # tienen nada que ver. Y bastaba con que el campo estuviera vacio
            # -cadena vacia, no ausente- para que saltara: asi se quedo
            # `08_D1_F9_29_E4` mintiendo, primero "desarmada" con la central
            # armada y luego al reves, que es el lado peligroso.
            #
            # Se compara contra lo que hay EN LA BASE, no contra lo que creemos:
            # eso es lo que hace que una divergencia se repare sola en la
            # siguiente telemetria en vez de quedarse para siempre. El `cache`
            # lo mantiene al dia el listener, asi que no hay lectura extra.
            for dev_id, dev_data in variantes.items():
                device_ref = self.db.reference(f'ESP32/{dev_id}')

                # Escribir Estado como boolean directo (compatibilidad con App Ionic)
                if "is_armed" in state_payload:
                    if dev_data.get('Estado') != state_payload["is_armed"]:
                        device_ref.child('Estado').set(state_payload["is_armed"])
                        logger.info(f"[{dev_id}] Estado actualizado en Firebase: {state_payload['is_armed']}")
                        # La app ordena escribiendo `Answer`, y la RTDB no avisa si
                        # se escribe el mismo valor. Si la central cambio por horario,
                        # Telegram o teclado, `Answer` quedaba viejo y la siguiente
                        # orden de la app no llegaba (C8_2E_18_26_60, 30-sep).
                        if dev_data.get('Answer') != state_payload["is_armed"]:
                            self._answer_eco[dev_id] = (state_payload["is_armed"], time.time())
                            device_ref.child('Answer').set(state_payload["is_armed"])

                # Escribir Alarming como boolean
                if "is_alarming" in state_payload:
                    if dev_data.get('Alarming') != state_payload["is_alarming"]:
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

    def _devices_for_schedule_key(self, key: str) -> List[str]:
        """
        Dispositivos a los que aplica un horario "system".

        La clave de /Horarios era siempre un chat_id de Telegram. Desde que el
        Chat ID es opcional en la app, un usuario sin Telegram indexa sus
        horarios por su **uid** de Firebase Auth, y ese uid no coincide con
        ningun Telegram_ID: get_authorized_devices() devolveria lista vacia y
        el horario "system" no se aplicaria a nada, en silencio.

        Se intenta primero por Telegram, que es el caso comun, y solo si no hay
        nada se mira /Usuarios/{uid}/Dispositivos.

        NO sustituye a get_authorized_devices() para autorizar: esto solo
        resuelve a que equipos aplica un horario que el dueno ya escribio.
        """
        # Solo los equipos de los que esa clave es DUENA (Telegram_ID), no
        # los que la tienen como Telegram_ID_2 o Group_ID: un "system" de un
        # usuario armaba y mandaba recordatorios de equipos de otros.
        por_telegram = [
            mac for mac in self.get_authorized_devices(key)
            if str((self._nodo(mac) or {}).get("Telegram_ID") or "") == key
            and self._horario_aplica(key, mac)
        ]
        if por_telegram:
            return por_telegram

        # Un chat_id es entero (los grupos, negativo). Si lo es, no es un uid y
        # no hay nada mas que mirar.
        if key.lstrip("-").isdigit():
            return []

        try:
            datos = self.db.reference(f"Usuarios/{key}/Dispositivos").get()
        except Exception as e:
            logger.error(f"No se pudieron leer los dispositivos de {key}: {e}")
            return []

        macs = [m for m in lista_macs(datos) if self._horario_aplica(key, m)]
        if macs:
            logger.info(f"Horario 'system' de {key} resuelto por uid: {len(macs)} equipo(s)")
        return macs

    # ========================================
    # Propiedad del equipo (endpoints /equipos/*)
    # ========================================
    #
    # El dueno era "quien tenga la MAC en su lista" para la app y "quien sea
    # Telegram_ID" para el bot, y nadie mantenia los dos iguales: asi Pedrito
    # veia y armaba la central de Jose. Ahora hay un dueno, `ESP32/{mac}/ownerUid`,
    # y estas dos operaciones son las unicas que lo cambian. Van por el VPS
    # (Admin SDK) porque tocan listas y horarios de OTRAS cuentas, cosa que las
    # reglas de seguridad no le dejan hacer a la app.

    @staticmethod
    def _misma_mac(guardada: str, mac: str) -> bool:
        guardada = normalizar_mac(guardada)
        # [:-1]: listas viejas con un caracter de mas (la app las corrige al cargar).
        return guardada == mac or guardada[:-1] == mac

    def _quitar_de_listas(self, mac: str, excepto: Optional[str] = None) -> List[str]:
        """Quita la MAC de `Usuarios/*/Dispositivos` (menos la de `excepto`). Devuelve a quien se la quito."""
        usuarios = self.db.reference("Usuarios").get() or {}
        tocados = []
        for uid, datos in usuarios.items():
            if uid == excepto or not isinstance(datos, dict):
                continue
            macs = lista_macs(datos.get("Dispositivos"))
            quedan = [m for m in macs if not self._misma_mac(m, mac)]
            if len(quedan) == len(macs):
                continue
            ref = self.db.reference(f"Usuarios/{uid}/Dispositivos")
            ref.set(quedan) if quedan else ref.delete()
            tocados.append(uid)
            logger.info(f"{mac} quitado de la lista de {uid}")
        return tocados

    def _borrar_horarios_de(self, mac: str, excepto: Optional[str] = None) -> None:
        """Borra `Horarios/*/devices/{mac}` en todas las claves (menos `excepto`)."""
        todos = self.db.reference("Horarios").get() or {}
        for clave, datos in todos.items():
            if clave == excepto or not isinstance(datos, dict):
                continue
            if isinstance(datos.get("devices"), dict) and mac in datos["devices"]:
                self.db.reference(f"Horarios/{clave}/devices/{mac}").delete()
                logger.info(f"Horario de {mac} bajo {clave} borrado")

    def _apagar_horario_central(self, mac: str) -> None:
        scheduler.remove(mac)
        if self.mqtt_handler:
            self.mqtt_handler.send_set_schedule(
                enabled=False, on_hour=0, on_minute=0, off_hour=0, off_minute=0,
                device_id=mac, queue_if_offline=True
            )

    def reclamar_equipo(self, uid: str, mac: str, nombre: str = "",
                        telegram_id: str = "", group_id: str = "") -> Dict[str, Any]:
        """
        Da la central a `uid`. La prueba de que la tiene en la mano la comprueba
        quien llama (api_server); aqui solo se ejecuta.

        Si era de otra cuenta: se le quita de su lista, se borran sus horarios
        de ese equipo, se le quita el acceso por Telegram (Telegram_ID,
        Telegram_ID_2, Group_ID) y se apaga el horario de la central. La
        configuracion de la central (bengala, tiempos, telemetria) se conserva.
        """
        ref = self.db.reference(f"ESP32/{mac}")
        nodo = ref.get()
        nodo = nodo if isinstance(nodo, dict) else None
        dueno = str((nodo or {}).get("ownerUid") or "")

        otros = self._quitar_de_listas(mac, excepto=uid)
        anteriores = sorted(set(otros) | ({dueno} if dueno and dueno != uid else set()))
        traspaso = bool(anteriores)

        if nodo is None:
            ref.set({
                "Answer": False, "Estado": False, "Nombre": nombre or "Mi central",
                "Telegram_ID": telegram_id, "Group_ID": group_id,
                "Tiempo_Bomba": 60, "Tiempo_pre": 60,
                "DisparoApp": False, "DisparoESP": False,
                "ownerUid": uid,
            })
        else:
            cambios: Dict[str, Any] = {"ownerUid": uid}
            if nombre:
                cambios["Nombre"] = nombre
            if traspaso:
                # Lo del dueno anterior fuera, aunque venga vacio: un Telegram
                # suyo que se quedara seguiria mandando sobre la central.
                cambios.update({"Telegram_ID": telegram_id, "Group_ID": group_id, "Telegram_ID_2": None})
            else:
                if telegram_id:
                    cambios["Telegram_ID"] = telegram_id
                if group_id:
                    cambios["Group_ID"] = group_id
            ref.update(cambios)

        if traspaso:
            self._borrar_horarios_de(mac, excepto=uid)
            self._apagar_horario_central(mac)

        lista = self.db.reference(f"Usuarios/{uid}/Dispositivos")
        macs = lista_macs(lista.get())
        if not any(self._misma_mac(m, mac) for m in macs):
            lista.set(macs + [mac])

        self.invalidate_cache()
        logger.info(f"{mac} reclamado por {uid} (traspaso={traspaso}, anteriores={anteriores})")
        return {
            "traspaso": traspaso,
            "anteriores": anteriores,
            "nombre": (nodo or {}).get("Nombre") or nombre,
            "telegram_anterior": str((nodo or {}).get("Telegram_ID") or "") if traspaso else "",
        }

    def borrar_equipo(self, uid: str, mac: str) -> str:
        """
        Borra la central para todos: listas, horarios bajo cualquier clave, el
        nodo y el horario de la central. Antes la app borraba el nodo y nada
        mas: los horarios seguian armandola y otras cuentas la seguian viendo.

        Devuelve "ok" o "no_es_dueno". Un nodo sin `ownerUid` (sin migrar) lo
        puede borrar quien lo tenga en su lista, como hasta ahora.
        """
        nodo = self.db.reference(f"ESP32/{mac}").get()
        dueno = str(nodo.get("ownerUid") or "") if isinstance(nodo, dict) else ""
        if dueno and dueno != uid:
            return "no_es_dueno"
        if not dueno:
            mias = lista_macs(self.db.reference(f"Usuarios/{uid}/Dispositivos").get())
            if not any(self._misma_mac(m, mac) for m in mias):
                return "no_es_dueno"

        self._quitar_de_listas(mac)
        self._borrar_horarios_de(mac)
        if isinstance(nodo, dict):
            self.db.reference(f"ESP32/{mac}").delete()
        self._apagar_horario_central(mac)
        self.invalidate_cache()
        logger.info(f"{mac} borrado por {uid}")
        return "ok"

    def vincular_chat_id(self, uid: str, chat_id: str) -> str:
        """
        Escribe el Chat ID de Telegram en la cuenta de la app.

        Lo llama /start cuando el enlace profundo trae el uid dentro
        (`?start=<uid>`, que la app construye en `urlBotVinculacion()`). Antes
        el payload era la palabra "app", que no identifica a nadie: el bot solo
        podia reconocer a quien YA tenia equipos, asi que al usuario recien
        registrado -el unico que de verdad necesita vincularse- le contestaba
        "Usuario no registrado, pidele al administrador un codigo".

        NO pisa un valor existente. Cambiar el telegram_id de una cuenta obliga
        a mover `Horarios/{telegram_id}`, que se indexa con el; hacerlo aqui,
        callado y desde un /start, dejaria los horarios huerfanos.

        Devuelve: "vinculado" | "ya_estaba" | "otro" | "sin_cuenta" | "error"
        """
        if not self.is_available():
            return "error"

        try:
            cuenta = self.db.reference(f"Usuarios/{uid}").get()
        except Exception as e:
            logger.error(f"No se pudo leer la cuenta {uid}: {e}")
            return "error"

        # El uid llega de un enlace que cualquiera puede teclear. Si no hay
        # cuenta, no se crea: se escribiria un nodo Usuarios/{loquesea} con el
        # chat_id de quien lo mando.
        if not isinstance(cuenta, dict):
            logger.warning(f"/start con un uid que no tiene cuenta: {uid}")
            return "sin_cuenta"

        actual = str(cuenta.get("telegram_id") or "").strip()
        if actual == str(chat_id):
            # Tambien aqui: el que se vinculo antes de este cambio tiene equipos
            # sin Chat ID, y volver a tocar "Vincular" es lo que va a hacer.
            self._propagar_chat_id(uid, chat_id, cuenta.get("Dispositivos"))
            return "ya_estaba"
        if actual:
            logger.info(f"La cuenta {uid} ya tiene otro telegram_id; no se pisa")
            return "otro"

        if self.update_data(f"Usuarios/{uid}", {"telegram_id": str(chat_id)}):
            logger.info(f"Cuenta {uid} vinculada al chat {chat_id}")
            self._propagar_chat_id(uid, chat_id, cuenta.get("Dispositivos"))
            return "vinculado"
        return "error"

    def _propagar_chat_id(self, uid: str, chat_id: str, dispositivos) -> None:
        """
        Pone el Chat ID en los equipos del usuario que no lo tienen.

        Antes solo lo hacia la app, y solo si el dialogo de vinculacion estaba
        abierto en ese momento: la cuenta decia "vinculado" y la central no
        avisaba por Telegram a nadie. Solo equipos suyos (ownerUid) o sin dueno
        todavia, y solo si el campo esta vacio: nunca se pisa el de otro.
        """
        for mac in lista_macs(dispositivos):
            nodo = self._nodo(mac)
            if nodo is None or str(nodo.get("Telegram_ID") or "").strip():
                continue
            if nodo.get("ownerUid") not in (None, "", uid):
                continue
            if self.update_data(f"ESP32/{mac}", {"Telegram_ID": str(chat_id)}):
                logger.info(f"Chat ID de {uid} propagado a {mac}")

    #: chat_id -> (uid, cuando_se_resolvio). Ver _uid_por_chat_id.
    _cache_uid: Dict[str, tuple] = {}
    _CACHE_UID_TTL = 300

    def _uid_por_chat_id(self, chat_id: str) -> Optional[str]:
        """
        La cuenta de la app cuyo `telegram_id` es este chat.

        Consulta indexada sobre `Usuarios` en vez de descargarlo entero. La
        regla `.indexOn: ["telegram_id"]` tiene que existir: sin ella Firebase
        avisa por log y filtra en cliente, o sea que se trae todo el arbol de
        usuarios en cada evento. Ver docs/SECURITY.md de la app.

        Cachea 5 minutos porque esto corre por cada notificacion y la relacion
        casi nunca cambia. El precio de la cache: si alguien acaba de vincular o
        revincular su Telegram, puede tardar hasta ese rato en que se le
        apliquen sus preferencias. Es aceptable; lo contrario -una consulta por
        evento- no.
        """
        if not self.is_available():
            return None

        ahora = time.time()
        cacheado = self._cache_uid.get(str(chat_id))
        if cacheado and ahora - cacheado[1] < self._CACHE_UID_TTL:
            return cacheado[0]

        try:
            encontrados = (
                self.db.reference("Usuarios")
                .order_by_child("telegram_id")
                .equal_to(str(chat_id))
                .get()
            )
        except Exception as e:
            logger.error(f"No se pudo resolver el uid de {chat_id}: {e}")
            return None

        uid = None
        if isinstance(encontrados, dict) and encontrados:
            uid = next(iter(encontrados))
            if len(encontrados) > 1:
                # Dos cuentas con el mismo Telegram. No deberia pasar
                # -vincular_chat_id no pisa un valor existente- pero puede haber
                # datos viejos, y elegir en silencio esconderia el problema.
                logger.warning(
                    f"{len(encontrados)} cuentas comparten el chat {chat_id}; "
                    f"se usan las preferencias de {uid}"
                )

        self._cache_uid[str(chat_id)] = (uid, ahora)
        return uid

    def quiere_aviso_telegram(self, chat_id: str, clave: Optional[str]) -> bool:
        """
        Si este chat de Telegram quiere recibir este aviso.

        `clave` es la familia opcional ("armado", "conexion") o None para los
        avisos que no se pueden apagar por categoria -las alarmas-. Incluso con
        None se consulta `alertas/telegram`, que es el interruptor del CANAL:
        quien lo apaga esta diciendo "por Telegram no", no "de esto no".

        Lee `Usuarios/{uid}/alertas`, el mismo sitio que el push. **No hay nodo
        aparte.** Lo hubo un dia, indexado por chat_id, para ahorrarse esta
        resolucion; era duplicar el estado para no escribir una consulta.

        Todo lo que no se pueda resolver devuelve True. Un chat sin cuenta en la
        app -un grupo, o alguien que solo usa Telegram- no tiene preferencias
        que respetar, y quedarse callado ante la duda es justo lo que no puede
        hacer una alarma.
        """
        if not self.is_available():
            return True

        uid = self._uid_por_chat_id(chat_id)
        if not uid:
            return True

        try:
            alertas = self.db.reference(f"Usuarios/{uid}/alertas").get()
        except Exception as e:
            logger.error(f"Error leyendo alertas de {uid}: {e}")
            return True

        if not isinstance(alertas, dict):
            return True

        # El canal entero, alarmas incluidas. Es una eleccion explicita del
        # usuario sobre DONDE quiere que le avisen, no sobre QUE.
        if alertas.get("telegram") is False:
            return False

        if not clave:
            return True

        return alertas.get(clave) is not False

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
                logger.debug(f"get_authorized_devices({chat_id}): No hay dispositivos en cache/Firebase")
                return []

            authorized = []
            chat_id_str = str(chat_id)

            for device_id, device_data in all_devices.items():
                if not isinstance(device_data, dict):
                    continue

                # Normalizar valores guardados (auto-fix supergrupos sin '-' por si el dato esta viejo)
                af = config.telegram.auto_fix_group_id
                telegram_id = normalize_chat_id(device_data.get('Telegram_ID', ''), auto_fix=af)
                telegram_id_2 = normalize_chat_id(device_data.get('Telegram_ID_2', ''), auto_fix=af)
                group_id = normalize_chat_id(device_data.get('Group_ID', ''), auto_fix=af)

                if telegram_id == chat_id_str or telegram_id_2 == chat_id_str or group_id == chat_id_str:
                    authorized.append(device_id)
                    if telegram_id == chat_id_str:
                        match_type = "Telegram_ID"
                    elif telegram_id_2 == chat_id_str:
                        match_type = "Telegram_ID_2"
                    else:
                        match_type = "Group_ID"
                    logger.debug(f"get_authorized_devices({chat_id}): Match en {device_id} via {match_type}")

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

            if unique_devices:
                logger.info(f"get_authorized_devices({chat_id}): {len(unique_devices)} dispositivo(s): {unique_devices}")
            else:
                logger.warning(f"get_authorized_devices({chat_id}): SIN dispositivos autorizados (authorized={authorized})")
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
                        # Leer los 3 campos de usuario: Telegram_ID, Telegram_ID_2, Group_ID
                        telegram_id = dev_data.get('Telegram_ID')
                        telegram_id_2 = dev_data.get('Telegram_ID_2')
                        group_id = dev_data.get('Group_ID')

                        for field_name, field_value in [('Telegram_ID', telegram_id), ('Telegram_ID_2', telegram_id_2), ('Group_ID', group_id)]:
                            if field_value:
                                field_str = str(field_value)
                                if '|||' in field_str:
                                    logger.warning(f"{field_name} concatenado detectado para {dev_id}: {field_str}")
                                    for tid in field_str.split('|||'):
                                        tid = tid.strip()
                                        if tid:
                                            # Auto-fix + validacion. Si la basura no
                                            # se puede normalizar, normalize devuelve "".
                                            normalized = normalize_chat_id(
                                                tid, auto_fix=config.telegram.auto_fix_group_id
                                            )
                                            if normalized:
                                                chats.add(normalized)
                                else:
                                    normalized = normalize_chat_id(
                                        field_str, auto_fix=config.telegram.auto_fix_group_id
                                    )
                                    if normalized:
                                        chats.add(normalized)
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
            af = config.telegram.auto_fix_group_id

            for device_data in all_devices.values():
                if not isinstance(device_data, dict):
                    continue

                # Normalizar valores guardados (auto-fix supergrupos sin '-' si el dato esta viejo)
                telegram_id = normalize_chat_id(device_data.get('Telegram_ID', ''), auto_fix=af)
                telegram_id_2 = normalize_chat_id(device_data.get('Telegram_ID_2', ''), auto_fix=af)
                group_id = normalize_chat_id(device_data.get('Group_ID', ''), auto_fix=af)

                # Verificar en Telegram_ID
                if '|||' in telegram_id:
                    telegram_ids = [tid.strip() for tid in telegram_id.split('|||') if tid.strip()]
                    if chat_id_str in telegram_ids:
                        is_telegram_id = True
                elif telegram_id == chat_id_str:
                    is_telegram_id = True

                # Verificar en Telegram_ID_2
                if telegram_id_2 == chat_id_str:
                    is_telegram_id = True

                # Verificar en Group_ID
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

    def save_lead(
        self,
        chat_id: str,
        first_name: str,
        email: str,
        phone: str = "",
        original_question: str = "",
    ) -> bool:
        """
        Guarda un lead capturado del modo vendedor en Firebase.

        Path: /Leads/{chat_id}. Si ya existe, sobrescribe (se asume que el
        prospecto repitio el flujo de captura intencionalmente).

        Args:
            chat_id: chat_id de Telegram del prospecto.
            first_name: nombre del usuario en Telegram.
            email: email validado.
            phone: telefono (opcional, "" si saltado).
            original_question: pregunta inicial que disparo el interes.

        Returns:
            True si se guardo correctamente.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para guardar lead")
            return False

        try:
            lead_ref = self.db.reference(f'Leads/{chat_id}')
            lead_ref.set({
                'chat_id': str(chat_id),
                'first_name': first_name or "",
                'email': email,
                'phone': phone or "",
                'original_question': (original_question or "")[:500],
                'created_at': int(time.time()),
                'status': 'new',
            })
            logger.info(f"💼 Lead guardado: {first_name} ({chat_id}) email={email}")
            return True
        except Exception as e:
            logger.error(f"Error guardando lead {chat_id}: {e}")
            return False

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
        Prioriza el dispositivo con ID más LARGO (completo = real MQTT) para consistencia.
        Soporta 3 slots: Telegram_ID (dueño), Telegram_ID_2 (segundo usuario), Group_ID (grupo).
        Retorna True si se agregó correctamente.

        Aplica auto-correccion defensiva: si el chat_id parece un supergrupo
        sin '-' (patron 100xxxxxxxxxx de 13 digitos), le agrega el '-' antes
        de guardar y loguea WARNING. Controlado por TELEGRAM_AUTO_FIX_GROUP_ID.
        """
        if not self.is_available():
            logger.warning("Firebase no disponible para agregar chat autorizado")
            return False

        # Normalizar chat_id (auto-corrige supergrupo sin '-' si aplica)
        chat_id = normalize_chat_id(chat_id, auto_fix=config.telegram.auto_fix_group_id)
        if not chat_id:
            logger.error("add_authorized_chat: chat_id vacio o invalido")
            return False

        try:
            # Forzar recarga del cache para tener datos frescos
            self.invalidate_cache()
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

            # Ordenar por longitud del ID (más LARGO primero = dispositivo real MQTT)
            # El dispositivo completo es el que responde a comandos MQTT
            matching_devices.sort(key=lambda x: len(x[0]), reverse=True)
            logger.info(f"Dispositivos encontrados para {device_id} (priorizando completo): {[d[0] for d in matching_devices]}")

            # Convertir chat_id a int para consistencia con Telegram_ID existente
            try:
                chat_id_int = int(chat_id)
            except ValueError:
                chat_id_int = chat_id  # Mantener como string si no es número

            # Determinar si el chat_id es un grupo (ID negativo)
            is_group_chat = str(chat_id).startswith('-')

            added = False
            added_to_device = None

            for existing_id, device_data in matching_devices:
                device_ref = self.db.reference(f'ESP32/{existing_id}')
                current_telegram_id = device_data.get('Telegram_ID')
                current_telegram_id_2 = device_data.get('Telegram_ID_2')
                current_group_id = device_data.get('Group_ID')

                logger.info(f"Revisando {existing_id}: Telegram_ID={current_telegram_id}, Telegram_ID_2={current_telegram_id_2}, Group_ID={current_group_id}")

                # Verificar si el chat ya está autorizado
                chat_str = str(chat_id_int)
                if (str(current_telegram_id) == chat_str or
                    str(current_telegram_id_2) == chat_str or
                    str(current_group_id) == chat_str):
                    logger.info(f"Chat {chat_id} ya está autorizado en {existing_id}")
                    return True

                if is_group_chat:
                    # Para grupos: solo usar Group_ID
                    if not current_group_id:
                        device_ref.child('Group_ID').set(chat_id_int)
                        logger.info(f"✅ Grupo {chat_id} agregado a {existing_id} como Group_ID")
                        added = True
                        added_to_device = existing_id
                        break
                    else:
                        logger.warning(f"Dispositivo {existing_id} ya tiene Group_ID={current_group_id}")
                else:
                    # Para usuarios: usar Telegram_ID → Telegram_ID_2
                    if not current_telegram_id:
                        device_ref.child('Telegram_ID').set(chat_id_int)
                        logger.info(f"✅ Chat {chat_id} agregado a {existing_id} como Telegram_ID")
                        added = True
                        added_to_device = existing_id
                        break
                    elif not current_telegram_id_2:
                        device_ref.child('Telegram_ID_2').set(chat_id_int)
                        logger.info(f"✅ Chat {chat_id} agregado a {existing_id} como Telegram_ID_2")
                        added = True
                        added_to_device = existing_id
                        break
                    else:
                        logger.warning(f"Dispositivo {existing_id} ya tiene Telegram_ID={current_telegram_id} y Telegram_ID_2={current_telegram_id_2}")

            if not added:
                slot_type = "Group_ID" if is_group_chat else "Telegram_ID/Telegram_ID_2"
                logger.error(f"❌ No se pudo agregar chat {chat_id} - slots de {slot_type} llenos en todos los dispositivos")

            # Invalidar y recargar caché para asegurar consistencia
            self.invalidate_cache()

            # Forzar recarga inmediata del dispositivo modificado
            if added_to_device:
                try:
                    fresh_data = self.db.reference(f'ESP32/{added_to_device}').get()
                    if self._all_devices_cache is None:
                        self._all_devices_cache = {}
                    self._all_devices_cache[added_to_device] = fresh_data
                    self._cache_timestamp = time.time()
                    logger.info(f"Cache actualizado para {added_to_device}: Telegram_ID={fresh_data.get('Telegram_ID')}, Telegram_ID_2={fresh_data.get('Telegram_ID_2')}, Group_ID={fresh_data.get('Group_ID')}")
                except Exception as e:
                    logger.warning(f"No se pudo recargar cache para {added_to_device}: {e}")

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

            # Verificar si el chat_id coincide con Telegram_ID_2
            telegram_id_2 = str(device_data.get('Telegram_ID_2', ''))
            if telegram_id_2 == chat_id_str:
                device_ref.child('Telegram_ID_2').delete()
                logger.info(f"Telegram_ID_2 {chat_id} removido de {device_id}")
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