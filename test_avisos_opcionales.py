"""
Que avisos quiere cada quien: por categoria en el push, y por canal en Telegram.

`push_enabled` era un si/no para TODO. En la practica -reportado por los
usuarios en la reunion del 3-sep- armar y desarmar notificaba cada vez, incluso
cuando lo habias hecho tu desde la propia app, y la unica forma de callarlo era
apagar tambien los avisos de alarma. Entre ruido y quedarse sin la notificacion
que importa, la gente elige quedarse sin ella. Eso es una alarma que no avisa.

    python test_avisos_opcionales.py

DOS EJES, Y NO SON LO MISMO:

- La CATEGORIA (`alertas/armado`, `alertas/conexion`) dice DE QUE avisar. Las
  alarmas no estan ahi y no se pueden quitar.
- El CANAL (`alertas/telegram`) dice DONDE avisar. Ese si se lleva las alarmas
  por delante, a proposito: quien lo apaga esta diciendo "por Telegram no", y
  seguir escribiendole ahi seria ignorarlo. La app avisa antes de guardarlo si
  el usuario ademas tiene el push apagado.

Todo vive en `Usuarios/{uid}/alertas`, un solo sitio. Hubo un dia un segundo
nodo indexado por chat_id para que el bot no tuviera que resolver el uid; era
duplicar estado para ahorrarse una consulta.
"""
import sys
import types


class FirebaseFalso:
    def __init__(self, nodos=None, usuarios=None):
        self.nodos = nodos or {}
        #: uid -> telegram_id, lo que resuelve la consulta indexada
        self.usuarios = usuarios or {}
        self.consultas = 0
        self.db = self

    def is_available(self):
        return True

    def reference(self, path):
        padre = self

        class Ref:
            def get(_):
                return padre.nodos.get(path)

            def order_by_child(_, campo):
                assert path == "Usuarios", f"consulta sobre {path}"
                assert campo == "telegram_id"

                class Query:
                    def equal_to(__, valor):
                        padre.consultas += 1

                        class Res:
                            def get(___):
                                return {
                                    uid: {"telegram_id": tid}
                                    for uid, tid in padre.usuarios.items()
                                    if tid == valor
                                }

                        return Res()

                return Query()

        return Ref()


# ----------------------------------------------------------------------
# Push: por categoria
# ----------------------------------------------------------------------

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


def test_apagar_telegram_no_toca_el_push():
    """Son dos canales. Silenciar uno no puede silenciar el otro."""
    from fcm_handler import NotificationType

    h = _fcm({"Usuarios/U1/alertas/telegram": False})
    assert h._quiere_aviso("U1", NotificationType.ALARM_TRIGGERED)
    assert h._quiere_aviso("U1", NotificationType.SYSTEM_ARMED)


def test_push_enabled_en_falso_lo_apaga_todo():
    """El interruptor general del canal push sigue mandando."""
    from fcm_handler import NotificationType

    h = _fcm({"Usuarios/U1/push_enabled": False})
    assert not h._quiere_aviso("U1", NotificationType.ALARM_TRIGGERED)


# ----------------------------------------------------------------------
# Telegram: por canal, resolviendo el uid desde el chat_id
# ----------------------------------------------------------------------

def _fb(nodos=None, usuarios=None):
    from firebase_manager import FirebaseManager

    fb = FirebaseFalso(nodos, usuarios)
    fb._cache_uid = {}
    fb._CACHE_UID_TTL = FirebaseManager._CACHE_UID_TTL
    fb._uid_por_chat_id = types.MethodType(FirebaseManager._uid_por_chat_id, fb)
    fb.quiere_aviso_telegram = types.MethodType(
        FirebaseManager.quiere_aviso_telegram, fb
    )
    return fb


def test_resuelve_el_uid_desde_el_chat_id():
    """Sin nodo duplicado: una consulta indexada sobre Usuarios."""
    fb = _fb({"Usuarios/U1/alertas": {"armado": False}}, {"U1": "555"})
    assert not fb.quiere_aviso_telegram("555", "armado")
    assert fb.quiere_aviso_telegram("555", "conexion")


def test_apagar_el_canal_calla_tambien_las_alarmas():
    """
    La diferencia con el push, y es deliberada. `clave=None` es una alarma: aun
    asi se respeta el interruptor de canal, porque el usuario esta diciendo
    DONDE quiere que le avisen, no de que.
    """
    fb = _fb({"Usuarios/U1/alertas": {"telegram": False}}, {"U1": "555"})
    assert not fb.quiere_aviso_telegram("555", None)
    assert not fb.quiere_aviso_telegram("555", "armado")


def test_un_chat_sin_cuenta_recibe_todo():
    """
    Un grupo, o alguien que solo usa Telegram. No tiene preferencias que
    respetar, y callarse ante la duda es lo que no puede hacer una alarma.
    """
    fb = _fb({}, {"U1": "555"})
    assert fb.quiere_aviso_telegram("-1001", None)
    assert fb.quiere_aviso_telegram("999", "armado")


def test_apagar_lo_mio_no_calla_al_grupo():
    """Las preferencias son por chat, no por dispositivo."""
    fb = _fb({"Usuarios/U1/alertas": {"telegram": False}}, {"U1": "555"})
    assert not fb.quiere_aviso_telegram("555", None)
    assert fb.quiere_aviso_telegram("-1001", None), "el grupo quedo silenciado"


def test_la_resolucion_se_cachea():
    """Esto corre por cada notificacion y por cada destinatario."""
    fb = _fb({"Usuarios/U1/alertas": {}}, {"U1": "555"})
    for _ in range(5):
        fb.quiere_aviso_telegram("555", "armado")
    assert fb.consultas == 1, f"{fb.consultas} consultas en vez de 1"


def test_la_cache_caduca():
    """Si no, revincular Telegram no surtiria efecto hasta reiniciar el bot."""
    fb = _fb({"Usuarios/U1/alertas": {}}, {"U1": "555"})
    fb.quiere_aviso_telegram("555", "armado")
    fb._CACHE_UID_TTL = -1
    fb.quiere_aviso_telegram("555", "armado")
    assert fb.consultas == 2


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
