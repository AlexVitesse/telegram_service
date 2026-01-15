import time
import logging
from typing import Dict, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from firebase_manager import FirebaseManager

logger = logging.getLogger(__name__)

class DeviceManager:
    """
    Gestiona el estado y la configuración de los dispositivos ESP32 conectados.
    Mantiene un registro de los dispositivos en estado de alarma y sus temporizadores
    para notificaciones repetitivas.
    """

    def __init__(self, firebase_manager: Optional['FirebaseManager'] = None):
        self.devices_state: Dict[str, Dict[str, Any]] = {}
        self.firebase_manager = firebase_manager
        logger.info("DeviceManager inicializado.")

    def _get_device_data(self, device_id: str) -> Dict[str, Any]:
        """Obtiene o inicializa los datos de un dispositivo."""
        if device_id not in self.devices_state:
            # Intentar cargar modo bengala desde Firebase para persistencia
            bengala_mode_from_firebase = 1  # Default: modo pregunta
            if self.firebase_manager:
                mode = self.firebase_manager.get_bengala_mode_from_firebase(device_id)
                if mode is not None:
                    bengala_mode_from_firebase = mode
                    logger.info(f"Modo bengala cargado desde Firebase para {device_id}: {mode}")

            self.devices_state[device_id] = {
                "id": device_id,
                "is_armed": False,
                "is_alarming": False,
                "is_online": False,
                "last_alarm_event_time": 0.0,
                "last_reminder_time": 0.0,
                "last_telemetry_time": 0.0,
                "offline_notified": False,  # Para no enviar notificaciones repetidas
                "location": "Desconocida",
                "telegram_ids": [], # Lista de chat_ids para notificar
                "group_id": None,
                "name": "Dispositivo sin nombre",
                "bengala_mode": bengala_mode_from_firebase,  # 0=automático, 1=con pregunta
                "bengala_enabled": True,  # Si la bengala está habilitada
            }
            logger.debug(f"Datos inicializados para el nuevo dispositivo: {device_id}")
        return self.devices_state[device_id]

    def update_device_info(self, device_id: str, info: Dict[str, Any]):
        """Actualiza la información básica de un dispositivo (nombre, ubicación, Telegram IDs)."""
        device_data = self._get_device_data(device_id)
        if "name" in info:
            device_data["name"] = info["name"]
        if "location" in info:
            device_data["location"] = info["location"]

        # Actualizar el estado también desde update_device_info si viene en la telemetría
        if "is_armed" in info:
            self.set_armed_state(device_id, info["is_armed"])

        # Actualizar estado de bengala desde telemetría
        if "bengala_enabled" in info:
            device_data["bengala_enabled"] = info["bengala_enabled"]

        logger.debug(f"Info actualizada para {device_id}: {device_data}")

    def set_armed_state(self, device_id: str, armed: bool):
        """Establece el estado de armado/desarmado de un dispositivo."""
        device_data = self._get_device_data(device_id)
        if device_data.get("is_armed") != armed:
            device_data["is_armed"] = armed
            logger.info(f"Estado de armado de {device_id} establecido a: {armed}")
            if self.firebase_manager:
                self.firebase_manager.update_device_state_in_firebase(device_id, {"is_armed": armed})

    def set_alarming_state(self, device_id: str, alarming: bool):
        """
        Establece el estado de alarma de un dispositivo.
        Inicia o detiene el temporizador de recordatorios.
        """
        device_data = self._get_device_data(device_id)
        if device_data.get("is_alarming") != alarming:
            device_data["is_alarming"] = alarming
            if alarming:
                device_data["last_alarm_event_time"] = time.time()
                device_data["last_reminder_time"] = 0.0
                logger.warning(f"Dispositivo {device_id} ha entrado en estado de alarma.")
            else:
                device_data["last_alarm_event_time"] = 0.0
                device_data["last_reminder_time"] = 0.0
                logger.info(f"Dispositivo {device_id} ha salido del estado de alarma.")
            
            if self.firebase_manager:
                self.firebase_manager.update_device_state_in_firebase(device_id, {"is_alarming": alarming})

    def get_alarming_devices(self, reminder_interval_seconds: int = 60) -> List[Dict[str, Any]]:
        """
        Retorna una lista de dispositivos que están en alarma y necesitan un recordatorio.
        Solo incluye dispositivos que están ONLINE para evitar enviar recordatorios
        cuando el dispositivo está desconectado.
        Actualiza `last_reminder_time` para los dispositivos que se retornan.
        """
        now = time.time()
        reminders_needed = []
        for device_id, data in self.devices_state.items():
            # Solo enviar recordatorios si el dispositivo está en alarma Y online
            # Si está offline, no tiene sentido enviar recordatorios porque
            # el usuario no puede interactuar con el dispositivo
            if data["is_alarming"] and data.get("is_online", False):
                if (now - data["last_reminder_time"]) >= reminder_interval_seconds:
                    reminders_needed.append(data)
                    data["last_reminder_time"] = now # Actualizar el tiempo del último recordatorio
            elif data["is_alarming"] and not data.get("is_online", False):
                # Si está alarmando pero offline, resetear el estado de alarma
                # ya que no podemos confirmar que la alarma sigue activa
                logger.warning(f"Dispositivo {device_id} estaba alarmando pero está offline. Reseteando estado de alarma.")
                data["is_alarming"] = False
                data["last_alarm_event_time"] = 0.0
                data["last_reminder_time"] = 0.0
        return reminders_needed

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Retorna la información completa de un dispositivo.
        Usa coincidencia parcial de IDs.
        """
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                return device_data
        return None

    def is_armed(self, device_id: str) -> bool:
        """
        Verifica si un dispositivo está armado.
        Usa coincidencia parcial de IDs (uno es prefijo del otro).
        """
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                if device_data.get("is_armed", False):
                    return True
        return False

    def is_alarming(self, device_id: str) -> bool:
        """
        Verifica si un dispositivo está en estado de alarma.
        Usa coincidencia parcial de IDs (uno es prefijo del otro).
        """
        # Buscar coincidencia parcial en todos los dispositivos
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                if device_data.get("is_alarming", False):
                    return True
        return False

    def get_all_device_ids(self) -> List[str]:
        """Retorna una lista de todos los IDs de dispositivos conocidos."""
        return list(self.devices_state.keys())

    def remove_device(self, device_id: str):
        """Elimina un dispositivo del gestor de estado."""
        if device_id in self.devices_state:
            del self.devices_state[device_id]
            logger.info(f"Dispositivo {device_id} eliminado del gestor de estado.")

    def update_telemetry_time(self, device_id: str):
        """Actualiza el tiempo de última telemetría y marca como online."""
        device_data = self._get_device_data(device_id)
        device_data["last_telemetry_time"] = time.time()

        # Si estaba offline y ahora recibimos telemetría, marcar como reconectado
        was_offline = device_data.get("offline_notified", False)
        if was_offline or not device_data.get("is_online", False):
            device_data["is_online"] = True
            device_data["offline_notified"] = False
            if was_offline:
                logger.info(f"Dispositivo {device_id} reconectado")
                return True  # Indica que se reconectó
        return False  # No hubo cambio de estado

    def is_online(self, device_id: str) -> bool:
        """
        Verifica si un dispositivo está online.
        Usa coincidencia parcial de IDs.
        """
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                if device_data.get("is_online", False):
                    return True
        return False

    def check_offline_devices(self, timeout_seconds: int = 90) -> List[Dict[str, Any]]:
        """
        Verifica qué dispositivos han dejado de enviar telemetría.
        Retorna lista de dispositivos que acaban de desconectarse (para notificar).
        """
        now = time.time()
        newly_offline = []

        for device_id, data in self.devices_state.items():
            last_telemetry = data.get("last_telemetry_time", 0)

            # Si nunca recibimos telemetría, ignorar
            if last_telemetry == 0:
                continue

            time_since_telemetry = now - last_telemetry

            # Si excede el timeout y no hemos notificado aún
            if time_since_telemetry > timeout_seconds:
                if data.get("is_online", True) and not data.get("offline_notified", False):
                    data["is_online"] = False
                    data["offline_notified"] = True
                    newly_offline.append(data)
                    logger.warning(f"Dispositivo {device_id} sin conexión (última telemetría hace {time_since_telemetry:.0f}s)")

        return newly_offline

    def get_bengala_mode(self, device_id: str) -> int:
        """
        Obtiene el modo de bengala de un dispositivo.
        Returns: 0=automático (dispara sin preguntar), 1=con pregunta (default)
        Usa coincidencia parcial de IDs.
        """
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                return device_data.get("bengala_mode", 1)
        return 1  # Default: modo pregunta

    def set_bengala_mode(self, device_id: str, mode: int, save_to_firebase: bool = True):
        """
        Establece el modo de bengala de un dispositivo.
        mode: 0=automático, 1=con pregunta
        save_to_firebase: Si es True, guarda también en Firebase para persistencia
        """
        device_data = self._get_device_data(device_id)
        device_data["bengala_mode"] = mode
        # Registrar timestamp para período de gracia (no sobrescribir desde telemetría por 10s)
        device_data["bengala_mode_set_time"] = time.time()
        logger.info(f"Modo bengala de {device_id} establecido a: {mode} ({'automático' if mode == 0 else 'pregunta'})")

        # Guardar en Firebase para persistencia
        if save_to_firebase and self.firebase_manager:
            self.firebase_manager.set_bengala_mode_in_firebase(device_id, mode)

    def sync_bengala_mode_from_telemetry(self, device_id: str, telemetry_mode: int):
        """
        Sincroniza el modo de bengala desde la telemetría del ESP32.
        Esto asegura que el servidor tenga el mismo modo que el dispositivo.
        Respeta un período de gracia después de cambios locales para evitar sobrescribir.
        """
        device_data = self._get_device_data(device_id)
        current_mode = device_data.get("bengala_mode", 1)

        # Verificar período de gracia (5 minutos después de un cambio local)
        # Nota: Aumentado a 5 min porque ESP32 actual no envía bengala_mode en telemetría,
        # Python usa default=1 (pregunta) y sobrescribe. Reducir a 10s cuando ESP32 esté actualizado.
        last_set_time = device_data.get("bengala_mode_set_time", 0)
        time_since_set = time.time() - last_set_time
        if time_since_set < 300:  # 5 minutos de gracia
            logger.debug(f"Ignorando sync bengala_mode de telemetría (cambio reciente hace {time_since_set:.1f}s)")
            return

        if current_mode != telemetry_mode:
            logger.info(f"Sincronizando modo bengala de {device_id}: servidor={current_mode} -> ESP32={telemetry_mode}")
            # Actualizar sin guardar en Firebase (el ESP32 ya tiene el valor correcto)
            device_data["bengala_mode"] = telemetry_mode

    def is_bengala_enabled(self, device_id: str) -> bool:
        """
        Verifica si la bengala está habilitada para un dispositivo.
        Usa coincidencia parcial de IDs.
        """
        for stored_id, device_data in self.devices_state.items():
            if stored_id.startswith(device_id) or device_id.startswith(stored_id):
                return device_data.get("bengala_enabled", True)
        return True  # Default: habilitada

    def set_bengala_enabled(self, device_id: str, enabled: bool):
        """Establece si la bengala está habilitada para un dispositivo."""
        device_data = self._get_device_data(device_id)
        device_data["bengala_enabled"] = enabled
        # Registrar timestamp para período de gracia
        device_data["bengala_enabled_set_time"] = time.time()
        logger.info(f"Bengala de {device_id} {'habilitada' if enabled else 'deshabilitada'}")
