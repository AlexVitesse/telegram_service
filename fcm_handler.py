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

from mqtt_protocol import normalizar_mac

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
    DEVICE_TRANSFERRED = "device_transferred"


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
                    }
                }
            }
        }


class FCMHandler:
    """Manejador de Firebase Cloud Messaging para notificaciones push"""

    #: Avisos que nunca frena el rate limit: son el motivo de tener una alarma.
    NUNCA_SE_DESCARTAN = {NotificationType.ALARM_TRIGGERED, NotificationType.BENGALA_ACTIVATED}

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

    #: Lo que puede pasarle a un envio. Se distingue "el token esta muerto" de
    #: "el envio fallo" porque solo lo primero justifica BORRAR el token, y
    #: confundirlos sale caro: el 2026-09-08 un `data` con un booleano dentro
    #: hizo fallar el envio, se tomo por token invalido y se borro el unico
    #: token de Eric. Un error nuestro dejaba al usuario sin avisos.
    ENVIO_OK = "ok"
    ENVIO_TOKEN_MUERTO = "token_muerto"
    ENVIO_FALLO = "fallo"

    def send_to_token(self, token: str, notification: PushNotification) -> str:
        """
        Envía una notificación push a un token específico.

        Args:
            token: Token FCM del dispositivo
            notification: Objeto PushNotification con los datos

        Returns:
            ENVIO_OK, ENVIO_TOKEN_MUERTO (y solo entonces se puede borrar) o
            ENVIO_FALLO.
        """
        if not self.is_available():
            logger.warning("FCM no disponible")
            return self.ENVIO_FALLO

        try:
            message = self._messaging.Message(
                token=token,
                notification=self._messaging.Notification(
                    title=notification.title,
                    body=notification.body,
                ),
                # FCM exige que TODO el `data` sean cadenas, y revienta el envio
                # entero si algo no lo es. Se convierte aqui, en la frontera, y
                # no en cada `create_*`: asi ninguna plantilla futura puede
                # volver a tirar los avisos por meter un bool o un int.
                data={
                    **{k: str(v) for k, v in notification.data.items()},
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
                            # Sin badge: la app no lo borra y el "1" se quedaba fijo en el icono.
                            sound="default",
                        )
                    )
                )
            )

            response = self._messaging.send(message)
            logger.debug(f"Notificación enviada: {response}")
            return self.ENVIO_OK

        except self._messaging.UnregisteredError:
            # Este es el UNICO caso en que el token esta muerto de verdad: la
            # app se desinstalo o FCM lo revoco. Cualquier otro fallo puede ser
            # nuestro, y borrar por el deja al usuario sin avisos sin que nadie
            # se entere.
            logger.warning(f"Token no registrado, debe eliminarse: {token[:20]}...")
            return self.ENVIO_TOKEN_MUERTO
        except Exception as e:
            logger.error(f"Error enviando notificación (el token NO se toca): {e}")
            return self.ENVIO_FALLO

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

        # Rate limiting. La alarma y la bengala lo saltan: si `movement_detected`
        # llegaba justo antes, `alarm_triggered` se descartaba sin rastro.
        if notification.notification_type not in self.NUNCA_SE_DESCARTAN and not self._check_rate_limit(user_id):
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

            resultado = self.send_to_token(token, notification)
            if resultado == self.ENVIO_OK:
                sent_count += 1
                # Actualizar lastUsed
                self._update_token_last_used(user_id, token_data.get("token_id"))
            elif resultado == self.ENVIO_TOKEN_MUERTO:
                # Solo si FCM dijo que ese token ya no existe. Un fallo nuestro
                # no puede costarle al usuario su unico canal de aviso.
                invalid_tokens.append(token_data.get("token_id"))

        # Limpiar tokens inválidos
        for token_id in invalid_tokens:
            self._remove_invalid_token(user_id, token_id)

        # Solo cuenta como "ya se le aviso" si de verdad le llego algo; si no, un
        # envio fallido bloqueaba el siguiente aviso 5 s.
        if sent_count:
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
            if self._quiere_aviso(user_id, notification.notification_type):
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

    #: Los dos momentos del armado remoto. La central publica `system_armed`
    #: DOS veces por una sola orden: al recibirla -`source: "remote"`, arranca
    #: el tiempo de salida- y al vencer ese tiempo -`source: "local"`-. Son dos
    #: hechos distintos y los dos ciertos, asi que no se calla ninguno: se les
    #: da el texto que les toca.
    #:
    #: El aviso viejo decia "Sistema Armado" en los dos, y en el primero eso es
    #: falso: durante esos segundos el usuario esta saliendo y la casa NO esta
    #: protegida. Visto en produccion el 2026-09-08, 60,58 s entre uno y otro.
    def create_arming_notification(
        self,
        device_location: str,
        segundos: Optional[int],
        device_id: str
    ) -> PushNotification:
        """El tiempo de salida acaba de empezar. Todavia no esta protegida."""
        cuenta = f"Tienes {segundos} s para salir." if segundos else "Tienes unos segundos para salir."
        return PushNotification(
            title="⏳ Armando",
            body=f"{cuenta} {device_location} aún no está protegida.",
            data={
                "device_id": device_id,
                "source": "remote",
                "location": device_location,
                "action": "view_status",
            },
            # El mismo tipo que el armado: quien apaga los avisos de armado
            # apaga los dos momentos, que es lo que espera.
            notification_type=NotificationType.SYSTEM_ARMED,
            priority="high"
        )

    def create_protected_notification(
        self,
        device_location: str,
        device_id: str
    ) -> PushNotification:
        """Vencio el tiempo de salida: ahora si esta protegida."""
        return PushNotification(
            title="🔒 Protegida",
            body=f"{device_location} está protegida.",
            data={
                "device_id": device_id,
                "source": "local",
                "location": device_location,
                "action": "view_status",
            },
            notification_type=NotificationType.SYSTEM_ARMED,
            priority="high"
        )

    def create_reinicio_notification(
        self,
        device_location: str,
        armado: bool,
        device_id: str
    ) -> PushNotification:
        """
        La central arranco y anuncia como quedo. No es que alguien haya armado.

        Llega con `source: "boot"` en `system_armed` o en `system_disarmed`, y
        el texto tiene que dejar claro que el reinicio no cambio nada: "armado
        desde Reinicio" se lee como que el reinicio armo la casa, que es al
        reves de lo que paso.

        Existe porque hasta ahora nadie anunciaba el estado tras un arranque: la
        RTDB se quedaba con lo ultimo que supo y la app lo pintaba como actual.
        La mitad peligrosa es esta: un corte de luz con la central desarmada y
        la base diciendo "armado" enseña protegida una casa que no lo esta.
        """
        estado = "protegida" if armado else "desarmada"
        return PushNotification(
            title="🔄 Reinicio",
            body=f"{device_location} se reinició y sigue {estado}.",
            data={
                "device_id": device_id,
                "source": "boot",
                "location": device_location,
                "armed": "true" if armado else "false",
                "action": "view_status",
            },
            # Misma familia que el resto del armado: quien apaga esos avisos
            # apaga tambien este. Si se decide que un reinicio merece su propio
            # interruptor, hace falta una clave nueva EN LA APP antes -sin ella,
            # ausente = encendido y nadie podria apagarlo-.
            notification_type=NotificationType.SYSTEM_ARMED,
            priority="high"
        )

    def create_cambio_sin_conexion_notification(
        self,
        device_location: str,
        armado: bool,
        device_id: str,
        hora_horario: Optional[str] = None,
    ) -> PushNotification:
        """
        La central volvio con otro estado del que tenia al perder la red.

        El horario arma aunque no haya internet, y su aviso se pierde porque no
        hay MQTT: el 30-sep C8_2E_18_26_60 se armo a las 07:00 sin red y nadie
        se entero hasta que empezo a pitar.
        """
        if armado:
            motivo = f", seguramente por su horario de las {hora_horario}" if hora_horario else ""
            titulo, cuerpo = "🔒 Se armó sin conexión", f"{device_location} se armó mientras estaba sin internet{motivo}."
        else:
            titulo, cuerpo = "🔓 Se desarmó sin conexión", f"{device_location} se desarmó mientras estaba sin internet."
        return PushNotification(
            title=titulo,
            body=cuerpo,
            data={
                "device_id": device_id,
                "source": "offline",
                "location": device_location,
                "armed": "true" if armado else "false",
                "action": "view_status",
            },
            notification_type=NotificationType.SYSTEM_ARMED if armado else NotificationType.SYSTEM_DISARMED,
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
            # Igualdad exacta tras normalizar. Antes se comparaba por prefijo en
            # los dos sentidos, y con un id de mas de 17 caracteres el prefijo
            # quedaba vacio: la alarma de un equipo le llegaba a TODOS.
            objetivo = normalizar_mac(device_id)

            for uid, user_data in all_users.items():
                if not isinstance(user_data, dict):
                    continue

                dispositivos = user_data.get("Dispositivos", [])
                if isinstance(dispositivos, str):
                    dispositivos = dispositivos.split(",")

                # Verificar si alguno de los dispositivos coincide
                for dev in dispositivos:
                    if not isinstance(dev, str) or not dev.strip():
                        continue
                    dev = normalizar_mac(dev)
                    # dev[:-1]: listas viejas con un caracter de mas, el mismo
                    # caso que la app corrige al cargar (dispositivos.service.ts).
                    if dev == objetivo or dev[:-1] == objetivo:
                        user_ids.append(uid)
                        break

            return user_ids

        except Exception as e:
            logger.error(f"Error obteniendo usuarios del dispositivo {device_id}: {e}")
            return []

    #: Avisos que el usuario puede apagar, y el campo que los apaga.
    #:
    #: ALARM_TRIGGERED y BENGALA_ACTIVATED NO estan aqui a proposito: son el
    #: motivo de tener una alarma. Un interruptor para "no avisarme de que ha
    #: entrado alguien" es una funcion que solo puede acabar mal.
    OPCIONALES = {
        NotificationType.SYSTEM_ARMED: "armado",
        NotificationType.SYSTEM_DISARMED: "armado",
        NotificationType.DEVICE_OFFLINE: "conexion",
        NotificationType.DEVICE_ONLINE: "conexion",
        NotificationType.SENSOR_OFFLINE: "conexion",
    }

    def _quiere_aviso(self, user_id: str, tipo: NotificationType) -> bool:
        """
        Si este usuario quiere ESTE aviso.

        Antes solo se miraba `push_enabled`, un si/no para todo. El resultado
        practico -reportado por los usuarios- era que armar y desarmar te
        notificaba cada vez, incluido cuando lo habias hecho tu mismo desde la
        propia app, y la unica salida era apagar TAMBIEN los avisos de alarma.
        Entre ruido y quedarse sin la notificacion que importa, la gente elegia
        quedarse sin ella.

        Ahora `Usuarios/{uid}/alertas/{clave}` apaga una familia. Ausente =
        encendido, para no cambiarle nada a quien ya lo tiene funcionando.
        """
        if not self._is_push_enabled(user_id):
            return False

        clave = self.OPCIONALES.get(tipo)
        if not clave:
            return True

        if not self.firebase_manager.is_available():
            return True

        try:
            valor = self.firebase_manager.db.reference(
                f"Usuarios/{user_id}/alertas/{clave}"
            ).get()
        except Exception as e:
            logger.error(f"Error leyendo alertas/{clave} de {user_id}: {e}")
            return True

        return valor is not False

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
