"""
Apagar los avisos de armado no apaga los de alarma.

`push_enabled` era un si/no para TODO. En la practica -reportado por los
usuarios en la reunion del 3-sep- armar y desarmar notificaba cada vez, incluso
cuando lo habias hecho tu desde la propia app, y la unica forma de callarlo era
apagar tambien los avisos de alarma. Entre ruido y quedarse sin la notificacion
que importa, la gente elige quedarse sin ella. Eso es una alarma que no avisa.

    python test_avisos_opcionales.py

Lo que se vigila: que ALARM_TRIGGERED y BENGALA_ACTIVATED no sean apagables por
ninguna via, y que lo ausente siga significando "si" -o un usuario que nunca
toco los ajustes se quedaria sin avisos de golpe-.
"""
import sys
import types


class FirebaseFalso:
    def __init__(self, nodos=None):
        self.nodos = nodos or {}
        self.db = self

    def is_available(self):
        return True

    def reference(self, path):
        nodos = self.nodos

        class Ref:
            def get(_):
                return nodos.get(path)

        return Ref()


def _fcm(nodos=None):
    from fcm_handler import FCMHandler

    h = types.SimpleNamespace()
    h.firebase_manager = FirebaseFalso(nodos)
    h.OPCIONALES = FCMHandler.OPCIONALES
    h._is_push_enabled = types.MethodType(FCMHandler._is_push_enabled, h)
    h._quiere_aviso = types.MethodType(FCMHandler._quiere_aviso, h)
    return h


def test_la_alarma_no_se_puede_apagar_por_categoria():
    """Aunque el usuario apague todo lo apagable."""
    from fcm_handler import NotificationType

    h = _fcm({
        "Usuarios/U1/alertas/armado": False,
        "Usuarios/U1/alertas/conexion": False,
    })
    assert h._quiere_aviso("U1", NotificationType.ALARM_TRIGGERED)
    assert h._quiere_aviso("U1", NotificationType.BENGALA_ACTIVATED)


def test_apagar_armado_calla_armado_y_desarmado():
    from fcm_handler import NotificationType

    h = _fcm({"Usuarios/U1/alertas/armado": False})
    assert not h._quiere_aviso("U1", NotificationType.SYSTEM_ARMED)
    assert not h._quiere_aviso("U1", NotificationType.SYSTEM_DISARMED)
    # y no se lleva por delante a los vecinos
    assert h._quiere_aviso("U1", NotificationType.DEVICE_OFFLINE)


def test_sin_ajustes_se_recibe_todo():
    """Nadie se queda sin avisos por no haber entrado nunca a la pantalla."""
    from fcm_handler import NotificationType

    h = _fcm({})
    for tipo in NotificationType:
        assert h._quiere_aviso("U1", tipo), tipo


def test_push_enabled_en_falso_lo_apaga_todo():
    """El interruptor general sigue mandando; esto solo lo afina."""
    from fcm_handler import NotificationType

    h = _fcm({"Usuarios/U1/push_enabled": False})
    assert not h._quiere_aviso("U1", NotificationType.ALARM_TRIGGERED)


def test_telegram_lee_su_propio_nodo_por_chat_id():
    """
    `Avisos/{chat_id}` y no `Usuarios/{uid}/alertas`: en el camino de Telegram
    solo se tiene el chat_id, y llegar al uid obligaria a recorrer `Usuarios`
    entero en cada evento.
    """
    from firebase_manager import FirebaseManager

    fb = FirebaseFalso({"Avisos/555/armado": False})
    fb.quiere_aviso_telegram = types.MethodType(
        FirebaseManager.quiere_aviso_telegram, fb
    )
    assert not fb.quiere_aviso_telegram("555", "armado")
    assert fb.quiere_aviso_telegram("555", "conexion")
    assert fb.quiere_aviso_telegram("999", "armado"), "otro chat no queda afectado"


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}", flush=True)
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}", flush=True)
        except Exception as e:
            fallos += 1
            print(f"ERROR  {t.__name__}: {type(e).__name__}: {e}", flush=True)
    print(f"{chr(10)}{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
