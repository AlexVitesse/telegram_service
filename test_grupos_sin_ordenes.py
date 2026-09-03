"""
Un grupo de Telegram no ejecuta ordenes, tampoco en lenguaje natural.

§10 del plan de comandos: `require_auth` bloquea los grupos en los comandos con
barra, pero `_handle_unknown_message` no llevaba el decorador. Solo miraba
`get_authorized_devices`, que SI acepta un Group_ID. Asi que /on desde un grupo
se rechazaba y "arma la alarma" escrito en ese mismo grupo se ejecutaba.

La puerta estaba cerrada y tenia una ventana al lado.

    python test_grupos_sin_ordenes.py

No se aplica @require_auth entero a proposito, y hay una prueba que lo vigila:
ese decorador contesta "acceso no autorizado" a quien no tiene equipos, y se
llevaria por delante el modo vendedor, que es un camino de producto para
usuarios que todavia no son clientes.
"""
import asyncio
import sys
import types


class FirebaseFalso:
    def __init__(self, grupos=(), autorizados=()):
        self._grupos = set(grupos)
        self._autorizados = dict(autorizados)

    def is_group_chat(self, chat_id):
        return str(chat_id) in self._grupos

    def get_authorized_devices(self, chat_id):
        return self._autorizados.get(str(chat_id), [])


class MensajeFalso:
    def __init__(self, texto):
        self.text = texto
        self.respuestas = []

    async def reply_text(self, texto, **kwargs):
        self.respuestas.append(texto)


class UpdateFalso:
    def __init__(self, chat_id, texto):
        self.message = MensajeFalso(texto)
        self.effective_chat = types.SimpleNamespace(id=chat_id)
        self.effective_user = types.SimpleNamespace(first_name="Quien sea")


def _bot(firebase):
    """
    El handler suelto, sin construir el bot entero -que abriria MQTT, Firebase y
    la red-. Se le cuelga a un objeto vacio junto a lo poco que usa.
    """
    from telegram_bot import TelegramBot

    b = types.SimpleNamespace()
    b.firebase_manager = firebase
    b.ai_handler = object()  # con IA: si llegara, intentaria ejecutar
    b.llamo_a_la_ia = False
    b.llamo_al_vendedor = False

    async def _ia(update, chat_id, text, devices):
        b.llamo_a_la_ia = True

    async def _vendedor(update, text):
        b.llamo_al_vendedor = True

    b._handle_ai_message = _ia
    b._handle_sales_chat = _vendedor
    b._get_keyboard = lambda: None
    b.handler = types.MethodType(TelegramBot._handle_unknown_message, b)
    return b


def _correr(firebase, chat_id, texto):
    b = _bot(firebase)
    upd = UpdateFalso(chat_id, texto)
    asyncio.get_event_loop().run_until_complete(b.handler(upd, None))
    return b, upd


def test_un_grupo_no_arma_aunque_tenga_equipos():
    """El caso del §10: Group_ID registrado, asi que get_authorized_devices
    devuelve equipos y antes se ejecutaba la orden."""
    fb = FirebaseFalso(grupos={"-1001"}, autorizados={"-1001": ["EQUIPO_1"]})
    b, upd = _correr(fb, "-1001", "arma la alarma")

    assert not b.llamo_a_la_ia, "un grupo llego a la IA: puede ejecutar ordenes"
    assert upd.message.respuestas, "no se le contesto nada al grupo"
    assert "solo recibe notificaciones" in upd.message.respuestas[0]


def test_un_grupo_tampoco_pregunta():
    """Misma politica que los comandos con barra: en grupo, nada."""
    fb = FirebaseFalso(grupos={"-1001"}, autorizados={"-1001": ["EQUIPO_1"]})
    b, _ = _correr(fb, "-1001", "como configuro la bengala")
    assert not b.llamo_a_la_ia


def test_un_usuario_normal_sigue_pasando():
    """El arreglo no puede cerrar la puerta de quien si debe entrar."""
    fb = FirebaseFalso(grupos=set(), autorizados={"555": ["EQUIPO_1"]})
    b, _ = _correr(fb, "555", "arma la alarma")
    assert b.llamo_a_la_ia, "un usuario autorizado dejo de llegar a la IA"
    assert not b.llamo_al_vendedor


def test_el_modo_vendedor_sobrevive():
    """
    Por esto NO se puso @require_auth entero: contestaria "acceso no
    autorizado" a un posible cliente en vez de atenderlo.
    """
    fb = FirebaseFalso(grupos=set(), autorizados={})
    b, _ = _correr(fb, "999", "cuanto cuesta el sistema")
    assert b.llamo_al_vendedor, "se rompio el modo vendedor"
    assert not b.llamo_a_la_ia


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
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
