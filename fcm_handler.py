"""
FCM Handler - Firebase Cloud Messaging para Push Notifications
==============================================================
Envía notificaciones push a la App móvil cuando ocurren eventos.
"""
import logging
import time
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from firebase_manager import FirebaseManager

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Tipos de notificaciones push"""
    ALARM_TRIGGERED = "alarm_triggered"
    SYSTEM_ARMED = "system_armed"
    SYSTEM_DISARMED = "system_disarmed"
    BENGALA_ACTIVATED = "bengala_activated"
    SENSOR_OFFLINE = "sensor_offline"
    DEVICE_OFFLINE = "device_offline"
    DEVICE_ONLINE = "device_online"
    MOVEMENT_DETECTED = "movement_detected"
    DOOR_OPEN = "door_open"


@dataclass
class PushNotification:
    """Estructura de una notificación push"""
    title: str
    body: str
    data: Dict[str, str]
    notification_type: NotificationType
    priority: str = "high"  # "high" o "normal"

    def to_fcm_message(self, token: str) -> Dict[str, Any]:
        """Convierte a formato de mensaje FCM"""
        return {
            "token": token,
            "notification": {
                "title": self.title,
                "body": self.body,
            },
            "data": {
                **self.data,
                "type": self.notification_type.value,
                "timestamp": str(int(time.time())),
            },
            "android": {
                "priority": self.priority,
                "notification": {
                    "channel_id": "alarm_notifications",
                    "sound": "default",
                    "click_action": "FLUTTER_NOTIFICATION_CLICK",
                }
            },
            "apns": {
                "payload": {
                    "aps": {
                        "sound": "default",
                        "badge": 1,
                    }
                }
            }
        }


class FCMHandler:
    """Manejador de Firebase Cloud Messaging para notificaciones push"""

    def __init__(self, firebase_manager: 'FirebaseManager'):
        self.firebase_manager = firebase_manager
        self.initialized = False
        self._messaging = None

        # Rate limiting: evitar spam de notificaciones
        self._last_notification_time: Dict[str, float] = {}  # {user_id: timestamp}
        self.MIN_NOTIFICATION_INTERVAL = 5  # segundos entre notificaciones al mismo usuario

        self._initialize()

    def _initialize(self):
        """Inicializa Firebase Cloud Messaging"""
        try:
            # Firebase Admin SDK ya está inicializado por FirebaseManager
            # Solo necesitamos importar messaging
            from firebase_admin import messaging
            self._messaging = messaging
            self.initialized = True
            logger.info("FCM Handler inicializado correctamente")
        except ImportError as e:
            logger.error(f"Error importando firebase_admin.messaging: {e}")
            self.initialized = False
        except Exception as e:
            logger.error(f"Error inicializando FCM: {e}")
            self.initialized = False

    def is_available(self) -> bool:
        """Verifica si FCM está disponible"""
        return self.initialized and self._messaging is not None

    # ========================================
    # Métodos para enviar notificaciones
    # ========================================

    def send_to_token(self, token: str, notification: PushNotification) -> bool:
        """
        Envía una notificación push a un token específico.

        Args:
            token: Token FCM del dispositivo
            notification: Objeto PushNotification con los datos

        Returns:
            True si se envió correctamente
        """
        if not self.is_available():
            logger.warning("FCM no disponible")
            return False

        try:
            message = self._messaging.Message(
                token=token,
                notification=self._messaging.Notification(
                    title=notification.title,
                    body=notification.body,
                ),
                data={
                    **notification.data,
                    "type": notification.notification_type.value,
                    "timestamp": str(int(time.time())),
                },
                android=self._messaging.AndroidConfig(
                    priority=notification.priority,
                    notification=self._messaging.AndroidNotification(
                        channel_id="alarm_notifications",
                        sound="default",
                    )
                ),
                apns=self._messaging.APNSConfig(
                    payload=self._messaging.APNSPayload(
                        aps=self._messaging.Aps(
                            sound="default",
                            badge=1,
                        )
                    )
                )
            )

            response = self._messaging.send(message)
            logger.debug(f"Notificación enviada: {response}")
            return True

        except self._messaging.UnregisteredError:
            logger.warning(f"Token no registrado, debe eliminarse: {token[:20]}...")
            return False
        except Exception as e:
            logger.error(f"Error enviando notificación: {e}")
            return False

    def send_to_user(self, user_id: str, notification: PushNotification) -> int:
        """
        Envía una notificación a todos los dispositivos de un usuario.

        Args:
            user_id: UID del usuario en Firebase Auth
            notification: Objeto PushNotification

        Returns:
            Número de notificaciones enviadas exitosamente
        """
        if not self.is_available():
            return 0

        # Rate limiting
        if not self._check_rate_limit(user_id):
            logger.debug(f"Rate limit activo para usuario {user_id}")
            return 0

        # Obtener tokens del usuario
        tokens = self._get_user_tokens(user_id)
        if not tokens:
            logger.debug(f"Usuario {user_id} no tiene tokens FCM registrados")
            return 0

        sent_count = 0
        invalid_tokens = []

        for token_data in tokens:
            token = token_data.get("token")
            if not token:
                continue

            if self.send_to_token(token, notification):
                sent_count += 1
                # Actualizar lastUsed
                self._update_token_last_used(user_id, token_data.get("token_id"))
            else:
                # Marcar token como inválido para limpieza posterior
                invalid_tokens.append(token_data.get("token_id"))

        # Limpiar tokens inválidos
        for token_id in invalid_tokens:
            self._remove_invalid_token(user_id, token_id)

        self._last_notification_time[user_id] = time.time()
        logger.info(f"Enviadas {sent_count}/{len(tokens)} notificaciones a usuario {user_id}")

        return sent_count

    def send_to_device_users(self, device_id: str, notification: PushNotification) -> int:
        """
        Envía notificación a todos los usuarios autorizados de un dispositivo.

        Args:
            device_id: ID del dispositivo ESP32
            notification: Objeto PushNotification

        Returns:
            Total de notificaciones enviadas
        """
        if not self.is_available() or not self.firebase_manager.is_available():
            return 0

        # Obtener usuarios que tienen este dispositivo
        user_ids = self._get_users_for_device(device_id)
        if not user_ids:
            logger.debug(f"No hay usuarios asociados al dispositivo {device_id}")
            return 0

        total_sent = 0
        for user_id in user_ids:
            # Verificar si el usuario tiene push habilitado
            if self._is_push_enabled(user_id):
                total_sent += self.send_to_user(user_id, notification)

        return total_sent

    # ========================================
    # Métodos para crear notificaciones
    # ========================================

    def create_alarm_notification(
        self,
        device_location: str,
        sensor_name: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de alarma disparada"""
        return PushNotification(
            title="🚨 ALARMA ACTIVADA",
            body=f"Sensor {sensor_name} activado en {device_location}",
            data={
                "device_id": device_id,
                "sensor": sensor_name,
                "location": device_location,
                "action": "view_alarm",
            },
            notification_type=NotificationType.ALARM_TRIGGERED,
            priority="high"
        )

    def create_armed_notification(
        self,
        device_location: str,
        source: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de sistema armado"""
        return PushNotification(
            title="🔒 Sistema Armado",
            body=f"{device_location} armado desde {source}",
            data={
                "device_id": device_id,
                "source": source,
                "location": device_location,
                "action": "view_status",
            },
            notification_type=NotificationType.SYSTEM_ARMED,
            priority="high"
        )

    def create_disarmed_notification(
        self,
        device_location: str,
        source: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de sistema desarmado"""
        return PushNotification(
            title="🔓 Sistema Desarmado",
            body=f"{device_location} desarmado desde {source}",
            data={
                "device_id": device_id,
                "source": source,
                "location": device_location,
                "action": "view_status",
            },
            notification_type=NotificationType.SYSTEM_DISARMED,
            priority="high"
        )

    def create_bengala_notification(
        self,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de bengala disparada"""
        return PushNotification(
            title="🔥 BENGALA DISPARADA",
            body=f"Bengala activada en {device_location}",
            data={
                "device_id": device_id,
                "location": device_location,
                "action": "view_alarm",
            },
            notification_type=NotificationType.BENGALA_ACTIVATED,
            priority="high"
        )

    def create_sensor_offline_notification(
        self,
        sensor_name: str,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de sensor offline"""
        return PushNotification(
            title="⚠️ Sensor Offline",
            body=f"{sensor_name} perdió conexión en {device_location}",
            data={
                "device_id": device_id,
                "sensor": sensor_name,
                "location": device_location,
                "action": "view_sensors",
            },
            notification_type=NotificationType.SENSOR_OFFLINE,
            priority="high"
        )

    def create_device_offline_notification(
        self,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de dispositivo offline"""
        return PushNotification(
            title="⚠️ Dispositivo Sin Conexión",
            body=f"{device_location} perdió conexión",
            data={
                "device_id": device_id,
                "location": device_location,
                "action": "view_devices",
            },
            notification_type=NotificationType.DEVICE_OFFLINE,
            priority="high"
        )

    def create_movement_notification(
        self,
        sensor_name: str,
        sensor_location: str,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de movimiento detectado (cuando sistema desarmado)"""
        return PushNotification(
            title="👁️ Movimiento Detectado",
            body=f"{sensor_name} en {sensor_location or device_location}",
            data={
                "device_id": device_id,
                "sensor": sensor_name,
                "location": device_location,
                "action": "view_activity",
            },
            notification_type=NotificationType.MOVEMENT_DETECTED,
            priority="high"
        )

    def create_door_notification(
        self,
        sensor_name: str,
        sensor_location: str,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Crea notificación de puerta/ventana abierta"""
        return PushNotification(
            title="🚪 Puerta/Ventana Abierta",
            body=f"{sensor_name} en {sensor_location or device_location}",
            data={
                "device_id": device_id,
                "sensor": sensor_name,
                "location": device_location,
                "action": "view_activity",
            },
            notification_type=NotificationType.DOOR_OPEN,
            priority="high"
        )

    # ========================================
    # Métodos auxiliares para Firebase
    # ========================================

    def _get_user_tokens(self, user_id: str) -> List[Dict[str, Any]]:
        """Obtiene los tokens FCM de un usuario desde Firebase"""
        if not self.firebase_manager.is_available():
            return []

        try:
            path = f"Usuarios/{user_id}/fcm_tokens"
            ref = self.firebase_manager.db.reference(path)
            tokens_data = ref.get()

            if not tokens_data:
                return []

            tokens = []
            for token_id, data in tokens_data.items():
                if isinstance(data, dict) and data.get("token"):
                    tokens.append({
                        "token_id": token_id,
                        "token": data.get("token"),
                        "platform": data.get("platform", "unknown"),
                        "lastUsed": data.get("lastUsed", 0),
                    })

            return tokens

        except Exception as e:
            logger.error(f"Error obteniendo tokens de usuario {user_id}: {e}")
            return []

    def _get_users_for_device(self, device_id: str) -> List[str]:
        """Obtiene los user_ids que tienen acceso a un dispositivo"""
        if not self.firebase_manager.is_available():
            return []

        try:
            # Buscar en Usuarios todos los que tengan este dispositivo
            ref = self.firebase_manager.db.reference("Usuarios")
            all_users = ref.get()

            if not all_users:
                return []

            user_ids = []
            # Truncar device_id para comparación
            device_id_truncated = device_id.rstrip('_0123456789ABCDEF')[:17] if len(device_id) > 17 else device_id

            for uid, user_data in all_users.items():
                if not isinstance(user_data, dict):
                    continue

                dispositivos = user_data.get("Dispositivos", [])
                if isinstance(dispositivos, str):
                    dispositivos = [dispositivos]

                # Verificar si alguno de los dispositivos coincide
                for dev in dispositivos:
                    if dev == device_id or dev.startswith(device_id_truncated) or device_id.startswith(dev):
                        user_ids.append(uid)
                        break

            return user_ids

        except Exception as e:
            logger.error(f"Error obteniendo usuarios del dispositivo {device_id}: {e}")
            return []

    def _is_push_enabled(self, user_id: str) -> bool:
        """Verifica si el usuario tiene push notifications habilitadas"""
        if not self.firebase_manager.is_available():
            return True  # Por defecto habilitado

        try:
            path = f"Usuarios/{user_id}/push_enabled"
            ref = self.firebase_manager.db.reference(path)
            value = ref.get()

            # Si no existe el campo, por defecto está habilitado
            return value is None or value is True

        except Exception as e:
            logger.error(f"Error verificando push_enabled para {user_id}: {e}")
            return True

    def _update_token_last_used(self, user_id: str, token_id: str):
        """Actualiza el timestamp de último uso de un token"""
        if not token_id or not self.firebase_manager.is_available():
            return

        try:
            path = f"Usuarios/{user_id}/fcm_tokens/{token_id}/lastUsed"
            ref = self.firebase_manager.db.reference(path)
            ref.set(int(time.time()))
        except Exception as e:
            logger.debug(f"Error actualizando lastUsed: {e}")

    def _remove_invalid_token(self, user_id: str, token_id: str):
        """Elimina un token inválido de Firebase"""
        if not token_id or not self.firebase_manager.is_available():
            return

        try:
            path = f"Usuarios/{user_id}/fcm_tokens/{token_id}"
            ref = self.firebase_manager.db.reference(path)
            ref.delete()
            logger.info(f"Token inválido eliminado: {token_id}")
        except Exception as e:
            logger.error(f"Error eliminando token inválido: {e}")

    def _check_rate_limit(self, user_id: str) -> bool:
        """Verifica si se puede enviar notificación (rate limiting)"""
        last_time = self._last_notification_time.get(user_id, 0)
        return (time.time() - last_time) >= self.MIN_NOTIFICATION_INTERVAL

    # ========================================
    # Método para registrar token desde la App
    # ========================================

    def register_token(
        self,
        user_id: str,
        token: str,
        platform: str = "android"
    ) -> bool:
        """
        Registra un nuevo token FCM para un usuario.
        Llamado desde la App cuando obtiene un token.

        Args:
            user_id: UID del usuario
            token: Token FCM
            platform: "android" o "ios"

        Returns:
            True si se registró correctamente
        """
        if not self.firebase_manager.is_available():
            return False

        try:
            # Usar hash del token como ID para evitar duplicados
            token_id = str(hash(token))[-10:]

            path = f"Usuarios/{user_id}/fcm_tokens/{token_id}"
            data = {
                "token": token,
                "platform": platform,
                "registeredAt": int(time.time()),
                "lastUsed": int(time.time()),
            }

            ref = self.firebase_manager.db.reference(path)
            ref.set(data)

            logger.info(f"Token FCM registrado para usuario {user_id} ({platform})")
            return True

        except Exception as e:
            logger.error(f"Error registrando token FCM: {e}")
            return False

    def unregister_token(self, user_id: str, token: str) -> bool:
        """
        Elimina un token FCM de un usuario (logout).

        Args:
            user_id: UID del usuario
            token: Token FCM a eliminar

        Returns:
            True si se eliminó correctamente
        """
        if not self.firebase_manager.is_available():
            return False

        try:
            token_id = str(hash(token))[-10:]
            path = f"Usuarios/{user_id}/fcm_tokens/{token_id}"

            ref = self.firebase_manager.db.reference(path)
            ref.delete()

            logger.info(f"Token FCM eliminado para usuario {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error eliminando token FCM: {e}")
            return False
