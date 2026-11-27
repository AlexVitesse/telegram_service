"""
Gestor de Firebase para el Sistema de Alarma (Version para Realtime Database)
==============================================================================
Maneja la conexion con Firebase Realtime Database (RTDB) para:
- Buscar dispositivos autorizados por chat_id
- Obtener la informacion de un dispositivo
"""
import logging
import re
import threading
import time
from typing import Callable, Optional, List, Dict, Any, TYPE_CHECKING
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


def es_disparo_app(data) -> bool:
    """
    El SOS de la app escribe `DisparoApp = {"<fecha>": true}` (un objeto, con set()),
    no `true` a secas. Hasta el 15-oct solo se aceptaba `true` y el SOS de la app
    no llegaba nunca a la central, ni con ella en linea. Desactivar escribe
    `{"<fecha>": false}`: eso no dispara.
    """
    if data is True:
        return True
    return isinstance(data, dict) and any(v is True for v in data.values())

class FirebaseManager:
    #: Serializa `reclamar_equipo` y `borrar_equipo`: los dos leen `ownerUid` y
    #: luego escriben listas y nodo, y la API los corre en hilos. Sin esto un
    #: borrado con la foto vieja podia deshacer un traspaso recien hecho.
    # ponytail: lock global de un solo proceso (hoy hay uno). Con varias
    # instancias haria falta una transaccion RTDB que recompruebe ownerUid.
    _lock_propiedad = threading.Lock()

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
        # Lo pone main.py: avisa del SOS al grupo de Telegram de la central.
        self.on_sos: Optional[Callable[[str], None]] = None
        # Lo pone main.py: la app pidio autorizar un sensor en cuarentena
        # (`ESP32/{mac}/Pendientes/{sensorId}/autorizar = true`).
        self.on_autorizar: Optional[Callable[[str, str], None]] = None
        # Lo pone main.py: la app pidio eliminar o renombrar un sensor
        # (`Sensors/{id}/borrar = true` / `Sensors/{id}/renombrar = "texto"`).
        self.on_sensor_orden: Optional[Callable[[str, str, str, Optional[str]], None]] = None
        # Lo pone main.py: un miembro armo, desarmo o pidio panico (#124 C2).
        # (mac, dueno, nombre_miembro, accion, ts_ms, local). Aviso obligatorio.
        self.on_orden_miembro: Optional[Callable[[str, str, str, str, int, bool], None]] = None
        # mac -> (por, ts) de la ultima Orden atendida (dedup; ver _orden_de_miembro).
        self._ultima_orden: Dict[str, tuple] = {}

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

    def anotar_pendiente(self, device_id: str, sensor_id: str, tipo: str) -> bool:
        """
        Apunta un sensor en cuarentena en `ESP32/{mac}/Pendientes/{sensorId}`,
        que es lo que lee la app. True si es nuevo: la central lo repite en cada
        `ON` y en cada reconexion, y solo se avisa la primera vez.
        """
        if not self.is_available() or not sensor_id:
            return False
        try:
            ref = self.db.reference(f"ESP32/{normalizar_mac(device_id)}/Pendientes/{sensor_id}")
            if ref.get():
                return False
            ref.set({"tipo": tipo or "", "desde": int(time.time())})
            return True
        except Exception as e:
            logger.error(f"No se pudo anotar el sensor pendiente {sensor_id} de {device_id}: {e}")
            return False

    def guardar_sensores(self, device_id: str, sensores) -> None:
        """
        La lista que manda la central (`sensors_list`) en `ESP32/{mac}/Sensors`,
        que es lo que la app enseña para renombrar y eliminar. Se reemplaza
        entera: un sensor borrado desaparece.
        """
        if not self.is_available():
            return
        datos = {
            s.sensor_id: {
                "name": s.name or s.sensor_id,
                "type": s.sensor_type,
                "location": s.location or "",
                "authorized": bool(s.authorized),
                "online": bool(s.active),
                "lastSeenSec": int(s.last_seen_sec or 0),
            }
            for s in sensores if s.sensor_id
        }
        try:
            ref = self.db.reference(f"ESP32/{normalizar_mac(device_id)}/Sensors")
            # set(None) lo rechaza el SDK ("Value must not be None") y el ultimo
            # sensor borrado se quedaba en la app (27-oct).
            ref.set(datos) if datos else ref.delete()
            # La lista es completa, cuarentena incluida: un pendiente que no sale
            # en ella lo olvido la central (reinicio o tope de 5) y en la app
            # seria un "Autorizar" que no puede salir bien (28-oct).
            en_espera = {s.sensor_id for s in sensores if s.sensor_id and not s.authorized}
            pendientes = self.db.reference(f"ESP32/{normalizar_mac(device_id)}/Pendientes")
            for sensor_id in (pendientes.get(shallow=True) or {}):
                if sensor_id not in en_espera:
                    pendientes.child(sensor_id).delete()
        except Exception as e:
            logger.error(f"No se pudo guardar la lista de sensores de {device_id}: {e}")

    def ignorar_pendiente(self, device_id: str, sensor_id: str) -> bool:
        """
        #313: «Ignorar» (Telegram o app) marca `Pendientes/{id}/ignorado`. No se
        borra: sigue sin disparar, no se vuelve a avisar (anotar_pendiente ve
        que ya existe) y se puede autorizar despues con /sensores o la app.
        Solo si el pendiente sigue ahi: no se crea uno a medias.
        """
        if not self.is_available() or not sensor_id:
            return False
        try:
            ref = self.db.reference(f"ESP32/{normalizar_mac(device_id)}/Pendientes/{sensor_id}")
            if not ref.get():
                return False
            ref.update({"ignorado": True})
            return True
        except Exception as e:
            logger.error(f"No se pudo ignorar el sensor pendiente {sensor_id} de {device_id}: {e}")
            return False

    def quitar_pendiente(self, device_id: str, sensor_id: str) -> None:
        if not self.is_available() or not sensor_id:
            return
        try:
            self.db.reference(f"ESP32/{normalizar_mac(device_id)}/Pendientes/{sensor_id}").delete()
        except Exception as e:
            logger.error(f"No se pudo quitar el sensor pendiente {sensor_id} de {device_id}: {e}")

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

    @staticmethod
    def _poner_en_ruta(raiz: dict, ruta: list, valor):
        """Escribe `valor` en `raiz` siguiendo `ruta`; None borra la hoja."""
        nodo = raiz
        for clave in ruta[:-1]:
            hijo = nodo.get(clave)
            if not isinstance(hijo, dict):
                if valor is None:
                    return
                hijo = nodo[clave] = {}
            nodo = hijo
        if valor is None:
            nodo.pop(ruta[-1], None)
        else:
            nodo[ruta[-1]] = valor

    def _update_cache_from_event(self, event) -> None:
        """
        Aplica un evento del listener al cache siguiendo la ruta COMPLETA.
        `put` reemplaza el nodo de la ruta; `patch` escribe cada hijo (la clave
        puede ser una subruta "a/b"); None borra. Antes solo se miraba el
        segundo nivel: un evento en /{mac}/miembros/{uid} dejaba `miembros`
        igual a {"rol": "familia"} y borrar un miembro borraba a todos.
        """
        try:
            ruta = [p for p in (event.path or "/").split("/") if p]
            if not ruta and event.event_type != "patch":
                # Snapshot inicial o reset completo
                self._all_devices_cache = event.data if isinstance(event.data, dict) else {}
                self._cache_timestamp = time.time()
                logger.debug(f"Cache actualizado desde listener (snapshot completo): {len(self._all_devices_cache)} dispositivos")
                return
            if self._all_devices_cache is None:
                logger.debug("Cache no inicializado, se cargará en próxima consulta")
                return
            if event.event_type == "patch" and isinstance(event.data, dict):
                cambios = [(ruta + [p for p in k.split("/") if p], v) for k, v in event.data.items()]
            else:
                cambios = [(ruta, event.data)]
            for r, valor in cambios:
                if r:
                    self._poner_en_ruta(self._all_devices_cache, r, valor)
            self._cache_timestamp = time.time()

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
                # Solo llega aqui una escritura en la ruta /Answer (la de la app).
                # La sincronizacion del servidor entra por el caso 2 como patch
                # del nodo, que no lee `Answer`: no hace falta reconocer ecos.
                if event.data is True:
                    logger.info(f"Comando de App: ARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.ARM.value, device_id=device_id)
                elif event.data is False:
                    logger.info(f"Comando de App: DESARMAR para {device_id}")
                    self.mqtt_handler.send_command(cmd=Command.DISARM.value, device_id=device_id)

            elif command_key == 'DisparoApp' and es_disparo_app(event.data):
                logger.info(f"Comando de App: DISPARO para {device_id}")
                self.mqtt_handler.send_command(cmd=Command.TRIGGER_ALARM.value, device_id=device_id)
                if self.on_sos:
                    try:
                        self.on_sos(device_id)
                    except Exception as e:  # el aviso nunca debe tumbar el listener
                        logger.error(f"[{device_id}] No se pudo avisar del SOS al grupo: {e}")

            elif command_key == 'Orden' and len(parts) == 3:
                # Orden de un miembro de familia (#124 C1): autor y accion en el
                # mismo evento. Las reglas ya exigen `por == auth.uid`.
                try:
                    self._orden_de_miembro(device_id, event.data)
                except Exception as e:  # nunca tumbar el listener
                    logger.error(f"[{device_id}] No se pudo procesar la Orden {event.data}: {e}")

            elif command_key == 'Pendientes':
                # /{mac}/Pendientes/{id}/autorizar = true, o el pendiente entero
                # con autorizar dentro. Las escrituras del propio VPS (alta y
                # borrado del pendiente) no lo traen.
                sensor_id = parts[3] if len(parts) > 3 else ""
                pide = (len(parts) > 4 and parts[4] == 'autorizar' and event.data is True) or                        (len(parts) == 4 and isinstance(event.data, dict) and event.data.get('autorizar') is True)
                if sensor_id and pide and self.on_autorizar:
                    logger.info(f"Comando de App: AUTORIZAR SENSOR {sensor_id} en {device_id}")
                    try:
                        self.on_autorizar(device_id, sensor_id)
                    except Exception as e:  # nunca tumbar el listener
                        logger.error(f"[{device_id}] No se pudo pedir la autorizacion de {sensor_id}: {e}")

            elif command_key == 'Sensors':
                # /{mac}/Sensors/{id}/borrar = true, /{mac}/Sensors/{id}/renombrar = "x"
                # (o el sensor entero con eso dentro). La lista que escribe el
                # propio VPS no los trae.
                sensor_id = parts[3] if len(parts) > 3 else ""
                datos = {parts[4]: event.data} if len(parts) > 4 else (event.data if isinstance(event.data, dict) else {})
                orden, nombre = None, None
                if datos.get("borrar") is True:
                    orden = "borrar"
                elif isinstance(datos.get("renombrar"), str) and datos["renombrar"].strip():
                    orden, nombre = "renombrar", datos["renombrar"].strip()[:32]
                if sensor_id and orden and self.on_sensor_orden:
                    logger.info(f"Comando de App: {orden.upper()} SENSOR {sensor_id} en {device_id}")
                    try:
                        self.on_sensor_orden(device_id, sensor_id, orden, nombre)
                    except Exception as e:
                        logger.error(f"[{device_id}] No se pudo pedir {orden} de {sensor_id}: {e}")

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
                self._avisar_tiempo_fuera_de_rango(device_id, event.data)
                if isinstance(event.data, (int, float)) and event.data >= 10:
                    seconds = int(event.data)
                    logger.info(f"Comando de App: TIEMPO DE SALIDA {seconds}s para {device_id}")
                    self.mqtt_handler.send_set_exit_time(seconds=seconds, device_id=device_id)

            # Caso 2: Patch a nivel dispositivo (ej: path=/device_id, data={'Tiempo_Bomba': 180, ...})
            elif command_key == "" and isinstance(event.data, dict):
                # Una Orden escrita con update() del nodo llega aqui como patch:
                # las reglas la aceptan igual, asi que tambien se atiende.
                if 'Orden' in event.data:
                    try:
                        self._orden_de_miembro(device_id, event.data['Orden'])
                    except Exception as e:
                        logger.error(f"[{device_id}] No se pudo procesar la Orden {event.data['Orden']}: {e}")

                # Inicializar cache de valores para este dispositivo si no existe
                if device_id not in self._last_known_values:
                    self._last_known_values[device_id] = {}

                # Procesar Tiempo_Bomba si viene en el diccionario Y cambió
                if 'Tiempo_Bomba' in event.data:
                    tiempo_bomba = event.data['Tiempo_Bomba']
                    self._avisar_tiempo_fuera_de_rango(device_id, tiempo_bomba)
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

    _ACCIONES_ORDEN = {"arm": Command.ARM, "disarm": Command.DISARM, "panic": Command.TRIGGER_ALARM}

    def _orden_de_miembro(self, mac: str, orden) -> bool:
        """
        `ESP32/{mac}/Orden = {accion, por, ts, local?}` (#124 C1/C2).

        Manda el comando por MQTT (salvo `local`: ya salio por la LAN),
        sincroniza `Answer` como patch del nodo -que no manda ordenes- y avisa
        al dueno con el nombre del miembro. Deduplica por `ts`: el listener
        reconecta y RTDB reentrega escrituras guardadas sin red.

        True si la orden se aplico (la usa tambien Telegram, #308).
        """
        if not isinstance(orden, dict):
            return False
        accion, por, ts = orden.get("accion"), str(orden.get("por") or ""), orden.get("ts")
        local = orden.get("local") is True
        if accion not in self._ACCIONES_ORDEN or not por or not isinstance(ts, (int, float)):
            return False
        nodo = self._nodo(mac) or {}
        dueno = str(nodo.get("ownerUid") or "")
        miembros = nodo.get("miembros") if isinstance(nodo.get("miembros"), dict) else {}
        if por != dueno and por not in miembros:
            logger.warning(f"[{mac}] Orden de {por}, que no es dueno ni miembro: se ignora")
            return False
        # Solo la repeticion exacta (misma persona, mismo ts). Comparar contra el
        # ts mas alto de la central dejaba que el reloj adelantado de un
        # telefono -o un ts absurdo- tirara las ordenes de los demas.
        if self._ultima_orden.get(mac) == (por, ts):
            return False
        self._ultima_orden[mac] = (por, ts)

        logger.info(f"Orden de miembro: {accion.upper()} para {mac} por {por} (local={local})")
        if not local and self.mqtt_handler:
            enviada = self.mqtt_handler.send_command(cmd=self._ACCIONES_ORDEN[accion].value, device_id=mac)
            if not enviada and accion in ("arm", "disarm"):
                # Sin broker no se da por hecha (#278): antes se escribia Answer y
                # se avisaba al dueno de que armo, y la dedup impedia reintentar.
                # No se encola: armar/desarmar horas despues seria peor.
                self._ultima_orden.pop(mac, None)
                logger.error(f"[{mac}] {accion.upper()} de {por} no se pudo publicar por MQTT: no se aplica ni se avisa")
                return False
        if accion in ("arm", "disarm"):
            self.db.reference(f"ESP32/{mac}").update({"Answer": accion == "arm"})
        elif self.on_sos:
            self.on_sos(mac)   # aviso al grupo, tambien si la sirena salio por la LAN

        if por != dueno and dueno and self.on_orden_miembro:
            datos = self.db.reference(f"Miembros/{mac}/{por}").get() or {}
            nombre = str(datos.get("nombre") or "") if isinstance(datos, dict) else ""
            self.on_orden_miembro(mac, dueno, nombre or "Un miembro", accion, int(ts), local)
        return True

    def centrales_familia(self, chat_id: str) -> List[str]:
        """
        #308: centrales donde la cuenta de la app vinculada a este chat es
        familiar (ESP32/{mac}/miembros). Por Telegram solo arma, desarma, pide
        panico y ve el estado, como en la app. Fuera las que ya tiene como
        dueno, Usuario 2 o grupo: esas siguen por el camino de siempre.

        La membresia se mira en la cache del listener, asi que quitar a alguien
        le corta Telegram al momento; la cuenta por chat se cachea 5 min.
        """
        if not chat_id or str(chat_id).startswith("-") or not self.is_available():
            return []
        uids = set(self._uids_por_chat_id(str(chat_id)))
        if not uids:
            return []
        ya = set(self.get_authorized_devices(chat_id))
        return [mac for mac, nodo in (self._get_all_devices() or {}).items()
                if isinstance(nodo, dict) and mac not in ya and uids & set(self._miembros(nodo))]

    def orden_familia(self, mac: str, chat_id: str, accion: str) -> bool:
        """
        Orden de un familiar desde Telegram: el mismo camino que la `Orden` de
        la app (MQTT, `Answer`, SOS al grupo y aviso al dueno con su nombre).
        """
        miembros = self._miembros(self._nodo(mac) or {})
        uid = next((u for u in self._uids_por_chat_id(str(chat_id)) if u in miembros), None)
        if not uid:
            logger.warning(f"[{mac}] Orden {accion} por Telegram de {chat_id}, que no es familiar: se ignora")
            return False
        return self._orden_de_miembro(mac, {"accion": accion, "por": uid, "ts": int(time.time() * 1000)})

    ROLES = ("familia", "admin")

    def _es_admin(self, nodo, uids) -> bool:
        miembros = self._miembros(nodo)
        return any(isinstance(miembros.get(u), dict) and miembros[u].get("rol") == "admin" for u in uids)

    def centrales_ajustes(self, chat_id: str) -> List[str]:
        """
        #314: donde este chat cambia horarios, bengala, modo y sensores: las
        suyas como dueno y aquellas donde su cuenta de la app es miembro
        Administrador. Usuario 2 (Telegram_ID_2) y Familia solo arman, desarman,
        piden panico y ven el estado. Invitar, quitar y aprobar siguen siendo
        solo del dueno (es_dueno).
        """
        if not chat_id or str(chat_id).startswith("-") or not self.is_available():
            return []
        chat = str(chat_id)
        propias = [d for d in self.get_authorized_devices(chat) if self.es_dueno(d, chat)]
        uids = set(self._uids_por_chat_id(chat))
        if not uids:
            return propias
        return propias + [mac for mac, nodo in (self._get_all_devices() or {}).items()
                          if mac not in propias and isinstance(nodo, dict) and self._es_admin(nodo, uids)]

    def puede_ajustar(self, mac: str, chat_id: str) -> bool:
        """Dueno o Administrador de esta central (#314)."""
        if self.es_dueno(mac, chat_id):
            return True
        if not chat_id or str(chat_id).startswith("-"):
            return False
        return self._es_admin(self._nodo(mac) or {}, set(self._uids_por_chat_id(str(chat_id))))

    def cambiar_rol(self, uid_dueno: str, mac: str, uid: str, rol: str) -> Any:
        """El dueno elige Familia o Administrador para un miembro (#314)."""
        if rol not in self.ROLES:
            return "rol_malo"
        with self._lock_propiedad:
            nodo = self.db.reference(f"ESP32/{mac}").get()
            if not isinstance(nodo, dict) or str(nodo.get("ownerUid") or "") != uid_dueno:
                return "no_es_dueno"
            if uid not in self._miembros(nodo):
                return "no_es_miembro"
            self.db.reference(f"ESP32/{mac}/miembros/{uid}").update({"rol": rol})
            self.invalidate_cache()
            logger.info(f"{mac}: {uid} ahora es {rol}")
            return {"nombre": nodo.get("Nombre") or mac}

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

    @classmethod
    def _lista_para_firmware(cls, schedule_data: dict) -> Optional[list]:
        """
        `lista` de la app ({nombre, activationTime, deactivationTime, days,
        enabled, desde, hasta}) al formato del firmware. El nombre se queda en
        la app. None si no hay lista (horario de siempre).
        """
        lista = schedule_data.get('lista')
        if not isinstance(lista, list) or not lista:
            return None
        fw = []
        for h in lista[:4]:
            if not isinstance(h, dict):
                continue
            on_h, on_m = cls._parse_schedule_time(h.get('activationTime', ''))
            off_h, off_m = cls._parse_schedule_time(h.get('deactivationTime', ''))
            solo_arma = bool(h.get('soloArma')) and not h.get('desde')
            item = {
                'en': h.get('enabled') is not False,
                'on': on_h * 60 + on_m,
                # 0xFFFF: solo arma, se desarma a mano (firmware SIN_DESARME).
                'off': 0xFFFF if solo_arma else off_h * 60 + off_m,
            }
            desde, hasta = str(h.get('desde') or ''), str(h.get('hasta') or '')
            if desde and hasta:
                item['desde'] = int(desde.replace('-', '')[:8])
                item['hasta'] = int(hasta.replace('-', '')[:8])
            else:
                dias = h.get('days') or DAY_NAMES
                item['dias'] = sum(1 << i for i, d in enumerate(DAY_NAMES) if d in dias)
            fw.append(item)
        return fw or None

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
        lista = self._lista_para_firmware(schedule_data)

        actual = (cfg.enabled, cfg.on_hour, cfg.on_minute, cfg.off_hour, cfg.off_minute, cfg.days, cfg.lista)
        nuevo = (enabled, on_hour, on_minute, off_hour, off_minute, days, lista)
        if actual == nuevo:
            # Sin cambios: no tocar los flags o el horario se re-ejecutaria hoy
            return False

        cfg.enabled = enabled
        cfg.on_hour, cfg.on_minute = on_hour, on_minute
        cfg.off_hour, cfg.off_minute = off_hour, off_minute
        cfg.days = days
        cfg.lista = lista
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

        # Solo un `put` en la raiz trae /Horarios entero. Un `patch` en la raiz
        # (el `update()` de /horarios del bot) trae rutas "uid/devices/mac":
        # tomarlo por el arbol completo dejaba todo "huerfano" y deshabilitaba
        # el horario recien habilitado (#315, visto el 25-nov).
        if event.path == '/' and event.event_type == 'put':
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

    @staticmethod
    def _avisar_tiempo_fuera_de_rango(device_id: str, valor) -> None:
        """La app deja elegir 0-180 s; aqui se descarta lo menor de 10 y el
        firmware solo acepta 10-300. Antes se descartaba en silencio: la app
        decia "guardado" y la central seguia con el valor anterior."""
        if isinstance(valor, (int, float)) and not 10 <= valor <= 300:
            logger.warning(
                f"Tiempo_Bomba={valor} para {device_id} fuera del rango del firmware "
                f"(10-300 s): no se aplica, la central conserva el anterior"
            )

    def enviar_tiempo_salida(self, device_id: str) -> None:
        """
        Manda a la central el `Tiempo_Bomba` de su nodo al arrancar.

        El listener solo lo envia cuando cambia, y comparando contra su propia
        cache: si la central estaba offline cuando se guardo, o el VPS se
        reinicio, volver a guardar el mismo valor no lo reenviaba nunca. La
        central lo guarda en NVS, asi que repetirlo no tiene efecto si ya lo
        tenia. Fuera de 10-300 s el firmware lo rechaza: no se manda.
        """
        if not self.mqtt_handler:
            return
        mac = normalizar_mac(device_id)
        nodos = self._get_all_devices() or {}
        clave = next((k for k in nodos if self._misma_mac(k, mac)), None)
        valor = (nodos.get(clave) or {}).get("Tiempo_Bomba") if clave else None
        if isinstance(valor, (int, float)) and 10 <= valor <= 300:
            logger.info(f"Tiempo de salida a {device_id}: {int(valor)} s")
            self.mqtt_handler.send_set_exit_time(seconds=int(valor), device_id=device_id)

    def enviar_horario(self, device_id: str, arrancando: bool = False) -> None:
        """
        Manda a la central el horario que tiene el scheduler para ella.

        Se usa al cambiar el horario y cuando la central arranca: sin eso, una
        central que estaba apagada al cambiarlo se quedaba con el viejo en NVS.
        Encola si esta desconectada.

        El id llega como lo manda la central por MQTT (puede ser la MAC de 17
        caracteres) y el scheduler usa la clave de Firebase: se busca por MAC.

        Una central SIN nodo en ESP32 (borrada) recibe el horario apagado. Al
        borrarla solo se le encolaba ese "apagado"; si estaba offline y la cola
        se perdia o caducaba, seguia armandose sola con el horario de su NVS
        para siempre, sin dueno que la viera.
        """
        if not self.mqtt_handler:
            return
        mac = normalizar_mac(device_id)
        # Primero si existe: un horario que quedase en el scheduler local de una
        # central ya borrada (caida a mitad de la limpieza) no debe reactivarla.
        nodos = self._get_all_devices()
        # Sin cache (Firebase caido) no se decide nada: mejor no tocar.
        if nodos and not any(self._misma_mac(k, mac) for k in nodos):
            logger.warning(f"{device_id} sin nodo en ESP32 (central borrada): se le apaga el horario")
            self.mqtt_handler.send_set_schedule(
                enabled=False, on_hour=0, on_minute=0, off_hour=0, off_minute=0,
                device_id=device_id, queue_if_offline=True,
            )
            self._olvidar(device_id, conectada=arrancando)
            return
        clave = next((k for k in scheduler.configs if self._misma_mac(k, mac)), None)
        if clave is None:
            return
        cfg = scheduler.configs[clave]
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
            lista=cfg.lista,
        )

    def _olvidar(self, device_id: str, conectada: bool = False) -> None:
        """
        La central borrada vuelve a los ajustes de fabrica (horario, tiempos,
        bengala; no la WiFi). Firmware de la fase 3; el anterior lo ignora.

        Solo si esta conectada, NUNCA encolado: un "olvidar" pendiente le
        llegaria a la central despues de volver a darla de alta y le borraria
        la configuracion nueva. Si estaba offline se lo manda el siguiente
        arranque (enviar_horario, rama sin nodo).

        `conectada`: quien llama ya sabe que lo esta. El `system_boot` llega
        antes que la primera telemetria, y sin esto is_device_online() decia
        "offline" justo al arrancar: la central borrada no olvidaba nunca
        (auditoria del 7-oct-2026).
        """
        if conectada or self.mqtt_handler.is_device_online(device_id):
            self.mqtt_handler.send_command(Command.FORGET.value, device_id=device_id)

    def revisar_horario(self, t) -> None:
        """
        Con la telemetria (firmware de la fase 3 en adelante, que manda el
        horario que tiene): si no es el de la nube, se le reenvia. Antes, si
        la central no lo habia aplicado, nadie se enteraba.

        Como mucho uno cada 10 min por central: uno que la central rechace no
        se repite en bucle. Sin horario en la nube no se decide nada (el
        arranque ya cubre la central borrada).
        """
        if t.sched_on is None:
            return
        mac = normalizar_mac(t.device_id)
        clave = next((k for k in scheduler.configs if self._misma_mac(k, mac)), None)
        if clave is None:
            return
        cfg = scheduler.configs[clave]
        # ponytail: la telemetria solo dice el primer horario; con varios no se
        # comprueba (se reenvian al arrancar la central y al cambiar).
        if cfg.decide_la_central():
            return
        if cfg.enabled:
            igual = (bool(t.auto_schedule_enabled)
                     and t.sched_on == cfg.on_hour * 60 + cfg.on_minute
                     and t.sched_off == cfg.off_hour * 60 + cfg.off_minute
                     and t.sched_days == sum(1 << d for d in cfg.days_indices()))
        else:
            igual = not t.auto_schedule_enabled
        if igual:
            return
        reenvios = self.__dict__.setdefault("_reenvio_horario", {})
        ahora = time.time()
        if ahora - reenvios.get(mac, 0) < 600:
            return
        reenvios[mac] = ahora
        logger.warning(f"El horario de {t.device_id} no es el de la nube: se le reenvia")
        self.enviar_horario(t.device_id)

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
                    # La app ordena escribiendo `Answer`, y la RTDB no avisa si se
                    # escribe el mismo valor. Si la central cambio por horario,
                    # Telegram o teclado -o una orden no llego a ejecutarse-,
                    # `Answer` quedaba viejo y la siguiente orden de la app se
                    # perdia (C8_2E_18_26_60, 30-sep). Se compara siempre, no solo
                    # cuando cambia Estado.
                    #
                    # `update()` sobre el nodo y no `child('Answer').set()`: el
                    # listener lo recibe como patch en /{dev_id} con {'Answer': X}
                    # (caso 2), que no manda ordenes, en vez de como put en
                    # /{dev_id}/Answer, que es una orden de la app. La version
                    # anterior llevaba la cuenta de sus "ecos" y perdia ordenes
                    # reales: dos escrituras iguales dejaban un eco de mas, y una
                    # escritura fallida dejaba uno que nunca llegaba (auditoria
                    # del 1-oct).
                    if dev_data.get('Answer') != state_payload["is_armed"]:
                        device_ref.update({'Answer': state_payload["is_armed"]})

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
        # [:14] con 16: las claves legacy `AA_BB_CC_DD_EE_F` (medio octeto de mas),
        # que con [:-1] quedaban en `AA_BB_CC_DD_EE_` y no casaban con nada.
        return (guardada == mac or guardada[:-1] == mac
                or (len(guardada) == 16 and guardada[14] == "_" and guardada[:14] == mac))

    def resolver_equipo(self, raw: str, entre=None) -> Optional[str]:
        """
        La clave real de una central a partir de lo que llegue: MAC con `:` o
        `_`, de 17 caracteres, o la legacy de 16. `entre` limita la busqueda
        (p. ej. a las centrales de un chat, y asi sirve de control de acceso).

        Coincidencia exacta primero, sea cual sea el largo. Las parciales solo
        con una MAC completa: un "/join_6" no puede casar con media flota.
        """
        pool = list(entre if entre is not None else (self._get_all_devices() or {}))
        texto = str(raw or "").strip()
        if texto in pool:
            return texto
        mac = normalizar_mac(texto)
        if len(mac) < 14:
            return None
        candidatas = [k for k in pool if self._misma_mac(k, mac)]
        # Dos centrales que casan con la misma MAC: no se elige ninguna. Un
        # boton de bengala no puede acabar en la central equivocada.
        if len(candidatas) != 1:
            if candidatas:
                logger.warning(f"{texto} es ambiguo entre {candidatas}: no se actua")
            return None
        return candidatas[0]

    def es_dueno(self, device_id: str, chat_id: str) -> bool:
        """
        Si el chat es el del dueno de la central: solo el puede invitar y
        aprobar. Ser "Usuario 2" o grupo no basta.

        Con `ownerUid` (la cuenta de la app) manda la cuenta vinculada a este
        chat; un Telegram_ID viejo de otro dueno no basta. `Telegram_ID` solo
        decide en nodos sin migrar o si el chat no tiene cuenta vinculada.
        """
        if not chat_id or str(chat_id).startswith("-"):
            return False
        nodo = self._nodo(device_id) or {}
        dueno = str(nodo.get("ownerUid") or "")
        if dueno:
            # Todas, no la primera: un mismo Telegram vinculado a dos cuentas
            # (27-oct: la del dueño y una de prueba) dejaba al dueño sin el aviso
            # para autorizar sensores, porque salía la otra.
            uids = self._uids_por_chat_id(str(chat_id))
            if uids:
                return dueno in uids
        return str(nodo.get("Telegram_ID") or "") == str(chat_id)

    def _quitar_de_listas(self, mac: str, excepto: Optional[str] = None) -> List[str]:
        """Quita la MAC de `Usuarios/*/Dispositivos` (menos la de `excepto`). Devuelve a quien se la quito."""
        usuarios = self.db.reference("Usuarios").get() or {}
        tocados = []
        for uid, datos in usuarios.items():
            if uid == excepto or not isinstance(datos, dict):
                continue
            if not any(self._misma_mac(m, mac) for m in lista_macs(datos.get("Dispositivos"))):
                continue
            # En transaccion (#124 C4): la app escribe esa lista a la vez.
            if not self._quitar_de_mi_lista(uid, mac):
                continue
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

    def reclamar_equipo(self, *args, **kwargs) -> Dict[str, Any]:
        with self._lock_propiedad:
            return self._reclamar_equipo(*args, **kwargs)

    def _reclamar_equipo(self, uid: str, mac: str, nombre: str = "",
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

        # Re-reclamo del propio dueno: no es traspaso y las listas de sus
        # miembros se quedan (#124 C3). Antes de mirar listas: un miembro con la
        # MAC en la suya contaria como "otro" y borraria Telegram y horarios.
        otros = [] if dueno == uid else self._quitar_de_listas(mac, excepto=uid)
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
                # miembros y Orden (lleva el uid del ultimo miembro que mando):
                # al nuevo dueno no le queda nada de la familia anterior.
                cambios.update({"Telegram_ID": telegram_id, "Group_ID": group_id, "Telegram_ID_2": None,
                                "miembros": None, "Orden": None})
            else:
                if telegram_id:
                    cambios["Telegram_ID"] = telegram_id
                if group_id:
                    cambios["Group_ID"] = group_id
            ref.update(cambios)

        if traspaso or nodo is None:
            self.db.reference(f"Miembros/{mac}").delete()
        if traspaso:
            self._borrar_horarios_de(mac, excepto=uid)
            self._apagar_horario_central(mac)

        self._agregar_a_mi_lista(uid, mac)

        self.invalidate_cache()
        logger.info(f"{mac} reclamado por {uid} (traspaso={traspaso}, anteriores={anteriores})")
        return {
            "traspaso": traspaso,
            "anteriores": anteriores,
            "nombre": (nodo or {}).get("Nombre") or nombre,
            "telegram_anterior": str((nodo or {}).get("Telegram_ID") or "") if traspaso else "",
        }

    def borrar_equipo(self, uid: str, mac: str) -> str:
        with self._lock_propiedad:
            return self._borrar_equipo(uid, mac)

    def _quitar_de_mi_lista(self, uid: str, mac: str) -> bool:
        """
        Quita la MAC solo de `Usuarios/{uid}/Dispositivos`. En transaccion: la
        app escribe esa lista directamente, y un get+set perderia un alta que
        entrase entre medias.
        """
        quitada = False

        def quitar(actual):
            nonlocal quitada
            macs = lista_macs(actual)
            quedan = [m for m in macs if not self._misma_mac(m, mac)]
            quitada = len(quedan) != len(macs)
            if not quitada:
                return actual if actual is not None else []   # sin lista: nada que escribir
            # [] y no None: firebase_admin rechaza None en una transaccion
            # ("Value must not be none") y la RTDB guarda [] como borrado.
            return quedan

        self.db.reference(f"Usuarios/{uid}/Dispositivos").transaction(quitar)
        return quitada

    def _agregar_a_mi_lista(self, uid: str, mac: str) -> None:
        """Pone la MAC en `Usuarios/{uid}/Dispositivos` si no esta. En transaccion, idempotente."""
        def agregar(actual):
            macs = lista_macs(actual)
            return actual if any(self._misma_mac(m, mac) for m in macs) else macs + [mac]

        self.db.reference(f"Usuarios/{uid}/Dispositivos").transaction(agregar)

    # ------------------------------------------------------------------
    # Familia (#124): invitar, unirse, quitar. Plan en
    # docs/PLAN_FAMILIA_PARTICIPANTES_2026-11-18.md (C3, C4, C7).
    # ------------------------------------------------------------------

    ALFABETO_CODIGO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sin 0/O, 1/I
    TOPE_MIEMBROS = 10
    VIGENCIA_QR = 15 * 60
    VIGENCIA_REMOTO = 24 * 3600

    @staticmethod
    def _miembros(nodo) -> Dict[str, Any]:
        m = (nodo or {}).get("miembros") if isinstance(nodo, dict) else None
        return m if isinstance(m, dict) else {}

    def crear_invitacion(self, uid: str, mac: str, remoto: bool = False) -> Any:
        """
        Codigo de un solo uso para unirse a la central. Solo el dueno. Anula los
        anteriores de esa central (y limpia los vencidos de todas).
        Devuelve {"codigo", "expira"} o "no_es_dueno" / "tope".
        """
        import secrets
        with self._lock_propiedad:
            nodo = self.db.reference(f"ESP32/{mac}").get()
            if not isinstance(nodo, dict) or str(nodo.get("ownerUid") or "") != uid:
                return "no_es_dueno"
            if len(self._miembros(nodo)) >= self.TOPE_MIEMBROS:
                return "tope"
            ahora = int(time.time())
            vivas = self.db.reference("Invitaciones").get() or {}
            fuera = {f"Invitaciones/{c}": None for c, inv in vivas.items()
                     if not isinstance(inv, dict) or inv.get("mac") == mac or (inv.get("expira") or 0) < ahora}
            if fuera:
                self.db.reference("/").update(fuera)
            while True:
                codigo = "".join(secrets.choice(self.ALFABETO_CODIGO) for _ in range(8))
                if codigo not in vivas:
                    break
            expira = ahora + (self.VIGENCIA_REMOTO if remoto else self.VIGENCIA_QR)
            self.db.reference(f"Invitaciones/{codigo}").set({"mac": mac, "invitadoPor": uid, "expira": expira})
            logger.info(f"Invitacion para {mac} creada por {uid} (remoto={remoto})")
            return {"codigo": codigo, "expira": expira}

    def unirse(self, uid: str, codigo: str) -> Any:
        """
        Canjea un codigo. Devuelve {"mac", "nombre", "dueno", "miembro"} o
        "no_existe" (no existe, vencido, usado o de un dueno que ya no lo es:
        indistinguibles), "es_dueno" o "tope".

        El canje es un `update` multipath de la raiz (membresia, nombre y el
        codigo marcado como usado); la lista va despues en transaccion. Si la
        lista falla, el mismo uid puede reintentar con el mismo codigo (C4).
        """
        with self._lock_propiedad:
            ref_inv = self.db.reference(f"Invitaciones/{codigo}")
            inv = ref_inv.get()
            if not isinstance(inv, dict) or (inv.get("expira") or 0) < time.time() \
                    or inv.get("usadoPor") not in (None, uid):
                return "no_existe"
            mac = str(inv.get("mac") or "")
            nodo = self.db.reference(f"ESP32/{mac}").get() if mac else None
            dueno = str(nodo.get("ownerUid") or "") if isinstance(nodo, dict) else ""
            if not dueno or dueno != inv.get("invitadoPor"):
                ref_inv.delete()   # la central cambio de dueno o ya no existe
                return "no_existe"
            if dueno == uid:
                return "es_dueno"
            miembros = self._miembros(nodo)
            if uid not in miembros and len(miembros) >= self.TOPE_MIEMBROS:
                return "tope"

            cuenta = self.db.reference(f"Usuarios/{uid}").get() or {}
            cuenta = cuenta if isinstance(cuenta, dict) else {}
            nombre_miembro = str(cuenta.get("userName") or cuenta.get("email") or "").strip()[:60] or "Sin nombre"
            self.db.reference("/").update({
                f"ESP32/{mac}/miembros/{uid}": {"rol": "familia"},
                # La copia de la llave local para apps < 8.2 sale en el mismo
                # update: un miembro lee ESP32/{mac} entero (#274).
                f"ESP32/{mac}/Local": None,
                f"Miembros/{mac}/{uid}": {"nombre": nombre_miembro, "alta": int(time.time() * 1000),
                                          "invitadoPor": dueno,
                                          # Para quitarle Usuario 2 de Telegram aunque cambie el suyo (#275)
                                          "telegram": str(cuenta.get("telegram_id") or "").strip() or None},
                f"Invitaciones/{codigo}/usadoPor": uid,
            })
            self._agregar_a_mi_lista(uid, mac)
            ref_inv.delete()
            self.invalidate_cache()
            logger.info(f"{uid} se unio a {mac} (dueno {dueno})")
            return {"mac": mac, "nombre": nodo.get("Nombre") or mac, "dueno": dueno, "miembro": nombre_miembro}

    def quitar_miembro(self, uid_dueno: str, mac: str, uid: str) -> Any:
        """El dueno quita a un miembro. Devuelve el nombre de la central, o "no_es_dueno" / "no_es_miembro"."""
        with self._lock_propiedad:
            nodo = self.db.reference(f"ESP32/{mac}").get()
            if not isinstance(nodo, dict) or str(nodo.get("ownerUid") or "") != uid_dueno:
                return "no_es_dueno"
            if not self._revocar(mac, uid, nodo):
                return "no_es_miembro"
            return {"nombre": nodo.get("Nombre") or mac}

    def _revocar(self, mac: str, uid: str, nodo: dict) -> bool:
        """
        Quita a un miembro de todo (C3), para "quitar" y "salir": su lista,
        Usuario 2 de Telegram si era el, los codigos que canjeo para esta
        central, llave local nueva (su telefono pudo guardar la de antes) y, AL
        FINAL, la membresia y su nombre. False si no era miembro.

        La membresia va la ultima a proposito (#275): antes se borraba primero y,
        si algo fallaba despues, el reintento respondia "no_es_miembro" y se
        quedaban Telegram_ID_2 y la llave vieja. Todo lo anterior se puede repetir.
        Llamar con `_lock_propiedad` tomado.
        """
        if uid not in self._miembros(nodo):
            return False
        # Telegram: el chat de ahora y el que tenia al unirse; pudo cambiar el
        # suyo en la cuenta antes de que lo quitaran.
        alta = self.db.reference(f"Miembros/{mac}/{uid}").get()
        chats = {str(self.db.reference(f"Usuarios/{uid}/telegram_id").get() or "").strip(),
                 str(alta.get("telegram") or "").strip() if isinstance(alta, dict) else ""} - {""}
        cambios = {f"ESP32/{mac}/miembros/{uid}": None, f"Miembros/{mac}/{uid}": None}
        if str(nodo.get("Telegram_ID_2") or "").strip() in chats:
            cambios[f"ESP32/{mac}/Telegram_ID_2"] = None
        # Un codigo a medio canjear (fallo la lista, C4) le dejaba volver a entrar.
        invitaciones = self.db.reference("Invitaciones").get() or {}
        for codigo, inv in (invitaciones.items() if isinstance(invitaciones, dict) else []):
            if isinstance(inv, dict) and inv.get("usadoPor") == uid and self._misma_mac(str(inv.get("mac") or ""), mac):
                cambios[f"Invitaciones/{codigo}"] = None
        if self.mqtt_handler:
            # Durable hasta el cmd_ack de la central (#276). Solo la llave de
            # familia (#283): la del dueno no la tenia el miembro. El firmware
            # anterior ignora el argumento y rota todo, como antes.
            self.mqtt_handler.send_command(Command.LOCAL_ROTATE.value, {"familia": True},
                                           device_id=mac, queue_if_offline=True)
        self._quitar_de_mi_lista(uid, mac)
        self.db.reference("/").update(cambios)
        self.invalidate_cache()
        logger.info(f"{uid} ya no es miembro de {mac}")
        return True

    def _borrar_equipo(self, uid: str, mac: str) -> str:
        """
        Borra la central para todos: listas, horarios bajo cualquier clave, el
        nodo y el horario de la central. Antes la app borraba el nodo y nada
        mas: los horarios seguian armandola y otras cuentas la seguian viendo.

        Devuelve "ok", "quitado" o "no_es_dueno". Un nodo sin `ownerUid` (sin
        migrar) lo puede borrar quien lo tenga en su lista, como hasta ahora.
        Si el nodo NO existe, solo se limpia la lista de quien pide: estar en
        una lista que el cliente escribe no autoriza a tocar las de otros.

        "quitado": la central es de OTRA cuenta pero sigue en la lista de quien
        pide borrarla (traspasos de antes de la migracion, o una app vieja que
        la volvio a escribir). Las reglas no le dejan leer el nodo, asi que la
        app la pinta como "Error al cargar", y antes tampoco podia borrarla: se
        le quedaba para siempre. Se le quita solo de SU lista; la central y la
        cuenta del dueno no se tocan.
        """
        nodo = self.db.reference(f"ESP32/{mac}").get()
        dueno = str(nodo.get("ownerUid") or "") if isinstance(nodo, dict) else ""
        if (dueno and dueno != uid) or not isinstance(nodo, dict):
            # Un miembro que "borra" sale de la central (#124): se le revoca todo,
            # aunque la MAC ya no estuviera en su lista.
            if isinstance(nodo, dict) and self._revocar(mac, uid, nodo):
                return "quitado"
            if not self._quitar_de_mi_lista(uid, mac):
                return "no_es_dueno"
            logger.info(f"{mac} quitado de la lista de {uid} (central ajena o inexistente)")
            return "quitado"
        if not dueno:
            mias = lista_macs(self.db.reference(f"Usuarios/{uid}/Dispositivos").get())
            if not any(self._misma_mac(m, mac) for m in mias):
                return "no_es_dueno"

        self._quitar_de_listas(mac)
        self._borrar_horarios_de(mac)
        self.db.reference(f"ESP32/{mac}").delete()
        self.db.reference(f"Miembros/{mac}").delete()
        self.db.reference(f"Locales/{mac}").delete()
        self._apagar_horario_central(mac)
        if self.mqtt_handler:
            self._olvidar(mac)
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
            # Si este chat escribio antes de vincularse, la cache lo tenia como
            # "sin cuenta" 5 min: un familiar no podria usar el bot (#308).
            self._cache_uid.pop(str(chat_id), None)
            self._propagar_chat_id(uid, chat_id, cuenta.get("Dispositivos"))
            return "vinculado"
        return "error"

    FICHA_ENLACE = re.compile(r"^t-[A-Za-z0-9]{22}$")

    def vincular_desde_enlace(self, payload: str, chat_id: str) -> str:
        """
        `/start <payload>` desde la app (#277). La app 8.2 manda una ficha
        aleatoria que la cuenta escribio en su propio Usuarios/{uid}/enlaceTelegram
        (solo ella puede): prueba de que el enlace es suyo.

        Las apps < 8.2 mandan el uid a pelo, y con familia los uids ya no son
        secretos (un miembro ve el del dueno). El uid solo se acepta para
        cuentas sin centrales ni membresias -el recien registrado, para quien
        se hizo esto-; a las demas el bot les dice su ID para escribirlo a mano.
        Mismos resultados que vincular_chat_id.
        """
        if self.FICHA_ENLACE.match(payload):
            try:
                encontrados = (self.db.reference("Usuarios").order_by_child("enlaceTelegram")
                               .equal_to(payload).get())
            except Exception as e:
                logger.error(f"No se pudo buscar la ficha de enlace: {e}")
                return "error"
            uids = list(encontrados) if isinstance(encontrados, dict) else []
            if len(uids) != 1:
                logger.warning(f"/start con una ficha que no es de una sola cuenta ({len(uids)})")
                return "sin_cuenta"
            return self.vincular_chat_id(uids[0], chat_id)
        if self._tiene_centrales(payload):
            logger.warning(f"/start con el uid de una cuenta con centrales ({payload}): se pide la ficha")
            return "sin_cuenta"
        return self.vincular_chat_id(payload, chat_id)

    def _tiene_centrales(self, uid: str) -> bool:
        """Dueno o miembro de alguna central (en el cache del listener)."""
        for nodo in (self._get_all_devices() or {}).values():
            if isinstance(nodo, dict) and (str(nodo.get("ownerUid") or "") == uid or uid in self._miembros(nodo)):
                return True
        return False

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
        """La cuenta de la app cuyo `telegram_id` es este chat (la primera si hay varias)."""
        uids = self._uids_por_chat_id(chat_id)
        return uids[0] if uids else None

    def _uids_por_chat_id(self, chat_id: str) -> List[str]:
        """
        Las cuentas de la app cuyo `telegram_id` es este chat.

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
            return []

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
            return []

        uids = list(encontrados) if isinstance(encontrados, dict) else []
        if uids:
            uid = uids[0]
            if len(uids) > 1:
                # Dos cuentas con el mismo Telegram. No deberia pasar
                # -vincular_chat_id no pisa un valor existente- pero puede haber
                # datos viejos, y elegir en silencio esconderia el problema.
                logger.warning(
                    f"{len(encontrados)} cuentas comparten el chat {chat_id}; "
                    f"se usan las preferencias de {uid}"
                )

        self._cache_uid[str(chat_id)] = (uids, ahora)
        return uids

    def quiere_aviso_telegram(
        self, chat_id: str, clave: Optional[str], device_id: Optional[str] = None
    ) -> bool:
        """
        Si este chat de Telegram quiere recibir este aviso.

        `clave` es la familia opcional ("armado", "conexion"), "alarma" para
        intrusion y SOS, o None para el resto de eventos.

        GRUPOS (chat_id negativo): solo alarmas (intrusion y SOS), salvo que el
        DUENO de la central (`device_id`) encienda `Usuarios/{dueno}/alertas/grupo`.
        27-oct: decidido por el usuario como valor por defecto. Saber cuando se
        arma y se desarma es saber cuando la casa esta sola, y en el grupo puede
        haber quien no deberia saberlo. Sin `device_id` no hay dueno a quien
        preguntar: solo alarmas. Incluso con
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

        if str(chat_id).startswith("-"):
            if clave == "alarma":
                return True
            return bool(device_id) and self._grupo_quiere_todo(device_id)

        uids = self._uids_por_chat_id(chat_id)
        if not uids:
            return True
        # Un Telegram en varias cuentas (12-nov: la del dueño y dos de prueba con
        # Telegram apagado): la primera callaba las alarmas del dueño. Mandan las
        # preferencias del dueño de esta central si es una de ellas.
        dueno = str((self._nodo(device_id) or {}).get("ownerUid") or "") if device_id else ""
        uid = dueno if dueno in uids else uids[0]

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

    def _grupo_quiere_todo(self, device_id: str) -> bool:
        """`Usuarios/{dueno}/alertas/grupo` encendido a proposito; ante la duda, solo alarmas."""
        dueno = (self._nodo(device_id) or {}).get("ownerUid")
        if not dueno:
            return False
        try:
            return self.db.reference(f"Usuarios/{dueno}/alertas/grupo").get() is True
        except Exception as e:
            logger.error(f"Error leyendo alertas/grupo de {dueno}: {e}")
            return False

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

            # La clave exacta primero: con prefijos, una clave de 14 y otra de
            # 17 de distintos duenos daban el dueno de la que saliese antes.
            exacto = all_devices.get(device_id)
            if isinstance(exacto, dict):
                return str(exacto.get('Telegram_ID')) if exacto.get('Telegram_ID') else None

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

            # La clave exacta, si existe, es la UNICA: con prefijos el chat podia
            # acabar autorizado en la variante larga de OTRA central.
            if isinstance(all_devices.get(device_id), dict):
                matching_devices = [(device_id, all_devices[device_id])]

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