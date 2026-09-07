"""
/start con el uid de la app vincula la cuenta, y no vincula nada mas.

El enlace de ayuda de la app mandaba `?start=app`: un payload que no identifica
a nadie. El bot leia el chat_id de quien escribia y no tenia con que cuenta
emparejarlo, asi que solo reconocia a quien YA tenia equipos -por
get_authorized_devices- y al recien registrado le contestaba "Usuario no
registrado, pidele al administrador un codigo de invitacion". Justo al que
acababa de darse de alta en la app.

    python test_vinculacion_app.py

Lo que se vigila aqui es sobre todo lo que NO debe pasar: el uid llega de un
enlace que cualquiera puede teclear, asi que un uid inventado no puede crear
una cuenta, y un chat_id ajeno no puede pisar el de una cuenta que ya vinculo
el suyo -eso movería sus avisos a otro telefono y dejaria sus Horarios, que se
indexan por telegram_id, apuntando a una clave que ya no es la suya-.
"""
import asyncio
import sys
import types


class FirebaseFalso:
    """Solo lo que toca vincular_chat_id: leer una cuenta y actualizarla."""

    def __init__(self, cuentas=None):
        self.cuentas = cuentas if cuentas is not None else {}
        self.escrituras = []
        self.initialized = True
        self.db = self

    # --- lo que usa vincular_chat_id ---
    def is_available(self):
        return True

    def reference(self, path):
        cuentas = self.cuentas

        class Ref:
            def get(_):
                if path.startswith("Usuarios/"):
                    return cuentas.get(path.split("/")[1])
                return None

        return Ref()

    def update_data(self, path, data):
        self.escrituras.append((path, data))
        uid = path.split("/")[1]
        self.cuentas.setdefault(uid, {}).update(data)
        return True


def _fm(cuentas=None):
    from firebase_manager import FirebaseManager

    fb = FirebaseFalso(cuentas)
    fb.vincular_chat_id = types.MethodType(
        FirebaseManager.vincular_chat_id, fb
    )
    return fb


def test_una_cuenta_sin_telegram_se_vincula():
    fb = _fm({"UID_DE_ERIC": {"email": "e@x.com"}})
    assert fb.vincular_chat_id("UID_DE_ERIC", "6679241035") == "vinculado"
    assert fb.cuentas["UID_DE_ERIC"]["telegram_id"] == "6679241035"


def test_repetir_el_start_no_es_un_error():
    """El usuario toca el enlace dos veces. No pasa nada y se lo decimos."""
    fb = _fm({"U1": {"telegram_id": "555"}})
    assert fb.vincular_chat_id("U1", "555") == "ya_estaba"
    assert fb.escrituras == []


def test_no_se_pisa_un_telegram_ya_vinculado():
    """
    Lo peor que podia hacer esto. `Horarios` se indexa por telegram_id: pisarlo
    manda los avisos a otro telefono y deja los horarios en una clave huerfana.
    """
    fb = _fm({"U1": {"telegram_id": "555"}})
    assert fb.vincular_chat_id("U1", "999") == "otro"
    assert fb.cuentas["U1"]["telegram_id"] == "555"
    assert fb.escrituras == []


def test_un_uid_inventado_no_crea_cuenta():
    """El payload viene de un enlace que cualquiera puede teclear a mano."""
    fb = _fm({})
    assert fb.vincular_chat_id("LO_QUE_SEA", "555") == "sin_cuenta"
    assert fb.escrituras == []
    assert fb.cuentas == {}


# ----------------------------------------------------------------------
# El handler: que /start llame a esto solo cuando toca
# ----------------------------------------------------------------------

class MensajeFalso:
    def __init__(self):
        self.respuestas = []

    async def reply_text(self, texto, **kwargs):
        self.respuestas.append(texto)


class UpdateFalso:
    def __init__(self, chat_id):
        self.message = MensajeFalso()
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(first_name="Eric")


def _correr_start(args, cuentas=None, autorizados=()):
    """El handler suelto, sin construir el bot -abriria MQTT, Firebase y red-."""
    from telegram_bot import TelegramBot

    fb = _fm(cuentas)
    fb.get_authorized_devices = lambda cid: list(autorizados)
    fb.has_any_admin = lambda: True

    b = types.SimpleNamespace()
    b.firebase_manager = fb
    b.mqtt_handler = None
    b._get_keyboard = lambda: None
    b.handler = types.MethodType(TelegramBot._cmd_start, b)

    upd = UpdateFalso("6679241035")
    ctx = types.SimpleNamespace(args=args)
    asyncio.get_event_loop().run_until_complete(b.handler(upd, ctx))
    return fb, upd


def test_start_con_uid_vincula_y_lo_dice():
    fb, upd = _correr_start(["UID_DE_ERIC"], {"UID_DE_ERIC": {}})
    assert fb.cuentas["UID_DE_ERIC"]["telegram_id"] == "6679241035"
    assert "vinculado" in upd.message.respuestas[0]


def test_el_payload_viejo_no_se_toma_por_un_uid():
    """`?start=app` seguia en enlaces ya repartidos; no puede crear nada."""
    fb, upd = _correr_start(["app"], {})
    assert fb.escrituras == []


def test_un_start_a_secas_sigue_funcionando():
    """Quien escribe /start en Telegram, sin venir de la app."""
    fb, upd = _correr_start([], {}, autorizados=["EQUIPO_1"])
    assert fb.escrituras == []
    assert "Hola de nuevo" in upd.message.respuestas[0]


def test_al_no_registrado_no_se_le_pide_un_codigo_de_entrada():
    """
    Por aqui pasa quien acaba de registrarse en la app: su cuenta existe, lo
    que le falta es vincularla. "Usuario no registrado / pide un codigo de
    invitacion" era la respuesta equivocada para el.
    """
    fb, upd = _correr_start([], {})
    texto = upd.message.respuestas[0]
    assert "Usuario no registrado" not in texto
    assert "6679241035" in texto, "no le dice su Chat ID, que es lo que necesita"
    assert "app" in texto


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
