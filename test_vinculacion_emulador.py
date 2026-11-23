#!/usr/bin/env python3
"""
Vinculación de punta a punta SIN teléfonos, tratando de romperla.

Dos vinculaciones:
- **Alta de la central** (BLE → home.page.ts `registrarDispositivo`): la app lee
  `ESP32/{mac}`; si no existe la crea con su `ownerUid`; si es suya actualiza;
  si es ajena (o las reglas le niegan leer) llama a `/equipos/reclamar`, que
  solo traspasa con prueba física (botón largo o arranque en los últimos 15 min).
- **Telegram** (`/start <uid>` → `vincular_chat_id`).

Contra el emulador con las reglas reales y la API y el FirebaseManager reales;
la app escribe por REST con su token. Las pruebas de siempre (test_retro_banco,
test_vinculacion_app) usan una RTDB de mentira: fue la que dejó pasar el 503
del 23-nov (transacción con None).

    FIREBASE_DATABASE_EMULATOR_HOST=127.0.0.1:9001 python test_vinculacion_emulador.py
"""
import asyncio
import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

if not os.environ.get("FIREBASE_DATABASE_EMULATOR_HOST"):
    print("SALTADA: sin FIREBASE_DATABASE_EMULATOR_HOST (usa firebase emulators:exec)")
    sys.exit(0)

from test_familia_emulador import db, fm, _esperar          # montaje compartido (emulador + FirebaseManager)
from test_reglas_emulador import _cargar_reglas, _pedir
from api_server import VENTANA_PRUEBA_FISICA
from mqtt_protocol import Command, normalizar_mac

MAC = "AC_15_18_D5_2D"
OTRA = "08_D1_F9_29_E4"
LEGACY = "AC_15_18_D4_47_4"          # clave vieja de 16 que sigue en /ESP32
A, B, C = "uidAnaA", "uidBetoB", "uidCarlaC"

en_mano = {}                          # mac -> instante de la prueba física (lo que llena mqtt_handler)


def _sembrar(extra=None):
    db.reference("/").set({
        "Usuarios": {A: {"userName": "Ana", "email": "ana@x.mx"},
                     B: {"userName": "Beto", "email": "beto@x.mx"},
                     C: {"userName": "Carla"}},
        **(extra or {}),
    })
    en_mano.clear()
    fm.mqtt_handler.reset_mock()


def _api(peticiones, en_paralelo=False):
    """[(uid, ruta, cuerpo)] contra la API real; la prueba física sale de `en_mano`."""
    from test_api_server import con_api, pedir
    fcm, bot = MagicMock(), MagicMock()
    salida = []

    async def p(url, api):
        api._uid_del_token = lambda t: t if t and t.startswith("uid") else None
        api._fcm = fcm
        api._bot.mqtt_handler = SimpleNamespace(prueba_fisica=en_mano, send_command=bot)
        api._bot.send_message = MagicMock(side_effect=lambda *a, **k: asyncio.sleep(0))
        llamadas = [pedir(url, token=u, cuerpo=c, ruta=r) for u, r, c in peticiones]
        if en_paralelo:
            salida.extend(await asyncio.gather(*llamadas))
        else:
            for ll in llamadas:
                salida.append(await ll)
    asyncio.run(con_api(fm, "nadie", p))
    return salida, fcm, bot


def _alta_como_la_app(uid, mac, nombre="Casa", telegram="", grupo=""):
    """registrarDispositivo() de home.page.ts, paso a paso. Devuelve qué camino tomó."""
    nodo_ok = _pedir(uid, "GET", f"ESP32/{mac}")
    existente = db.reference(f"ESP32/{mac}").get() if nodo_ok else None
    if not nodo_ok or (existente and existente.get("ownerUid") != uid):
        (r,), _, _ = _api([(uid, "/equipos/reclamar",
                            {"mac": mac, "nombre": nombre, "telegram_id": telegram, "group_id": grupo})])
        return "reclamar", r
    if existente:
        ok = _pedir(uid, "PATCH", f"ESP32/{mac}", {"Nombre": nombre, "Telegram_ID": telegram, "Group_ID": grupo})
        camino = "actualizar"
    else:
        ok = _pedir(uid, "PUT", f"ESP32/{mac}", {
            "Nombre": nombre, "Telegram_ID": telegram, "Group_ID": grupo, "Answer": False, "Estado": False,
            "Tiempo_Bomba": 60, "Tiempo_pre": 60, "DisparoApp": False, "DisparoESP": False, "ownerUid": uid})
        camino = "crear"
    lista = db.reference(f"Usuarios/{uid}/Dispositivos").get() or []
    if ok and mac not in lista:
        ok = _pedir(uid, "PUT", f"Usuarios/{uid}/Dispositivos", lista + [mac])
    return camino, (200 if ok else 403, None)


def _lista(uid):
    return db.reference(f"Usuarios/{uid}/Dispositivos").get() or []


# --------------------------------------------------------------------------
# Alta, re-alta y traspaso
# --------------------------------------------------------------------------

def v01_alta_nueva_nace_con_dueno():
    camino, r = _alta_como_la_app(A, MAC, telegram="111")
    assert (camino, r[0]) == ("crear", 200), (camino, r)
    nodo = db.reference(f"ESP32/{MAC}").get()
    assert nodo["ownerUid"] == A and nodo["Telegram_ID"] == "111", nodo
    assert _lista(A) == [MAC]
    assert not _pedir(B, "GET", f"ESP32/{MAC}"), "otra cuenta lee la central recién dada de alta"


def v02_re_alta_del_mismo_dueno_no_toca_su_config():
    _alta_como_la_app(A, MAC, telegram="111")
    db.reference(f"ESP32/{MAC}").update({"Tiempo_Bomba": 30, "BengalaHab": True, "Telegram_ID_2": "222"})
    db.reference(f"Horarios/{A}/devices/{MAC}").set({"activationTime": "22:00", "enabled": True})
    camino, r = _alta_como_la_app(A, MAC, nombre="Casa nueva", telegram="111")
    assert (camino, r[0]) == ("actualizar", 200), (camino, r)
    nodo = db.reference(f"ESP32/{MAC}").get()
    assert nodo["Nombre"] == "Casa nueva" and nodo["Tiempo_Bomba"] == 30 and nodo["Telegram_ID_2"] == "222", nodo
    assert db.reference(f"Horarios/{A}/devices/{MAC}").get(), "la re-alta borró el horario"
    assert _lista(A) == [MAC], _lista(A)


def v03_otra_cuenta_sin_la_central_en_la_mano_no_se_la_queda():
    _alta_como_la_app(A, MAC)
    camino, r = _alta_como_la_app(B, MAC)
    assert (camino, r[0]) == ("reclamar", 409), (camino, r)
    assert db.reference(f"ESP32/{MAC}/ownerUid").get() == A
    assert not _pedir(B, "PUT", f"ESP32/{MAC}", {"ownerUid": B, "Nombre": "mía"}), "las reglas dejan pisar el nodo"
    assert not _pedir(B, "PATCH", f"ESP32/{MAC}", {"ownerUid": B}), "las reglas dejan cambiar el dueño"


def v04_traspaso_con_la_central_en_la_mano_cuando_era_su_unica_central():
    """El caso del 503 del 23-nov: al dueño anterior se le queda la lista vacía."""
    _alta_como_la_app(A, MAC, telegram="111")
    db.reference(f"ESP32/{MAC}").update({"Telegram_ID_2": "222", "Group_ID": "-100123", "Tiempo_Bomba": 45})
    db.reference(f"Horarios/{A}/devices/{MAC}").set({"activationTime": "22:00", "enabled": True})
    en_mano[MAC] = time.time()
    (r,), fcm, bot = _api([(B, "/equipos/reclamar", {"mac": "ac:15:18:d5:2d", "nombre": "Mía", "telegram_id": "333"})])
    assert r == (200, {"ok": True, "traspaso": True}), r
    nodo = db.reference(f"ESP32/{MAC}").get()
    assert nodo["ownerUid"] == B and nodo["Telegram_ID"] == "333", nodo
    assert "Telegram_ID_2" not in nodo and not nodo.get("Group_ID"), "el Telegram del dueño anterior sigue mandando"
    assert nodo["Tiempo_Bomba"] == 45, "el traspaso borró la configuración de la central"
    assert _lista(A) == [] and _lista(B) == [MAC], (_lista(A), _lista(B))
    assert not db.reference(f"Horarios/{A}/devices/{MAC}").get(), "el horario del anterior sigue armándola"
    assert not _pedir(A, "GET", f"ESP32/{MAC}"), "el dueño anterior sigue leyendo"
    assert fcm.send_to_user.call_args.args[0] == A, "no se avisó al dueño anterior"
    assert bot.call_args.args[0] == Command.LOCAL_ROTATE.value, "no se pidió llave local nueva"
    sched = fm.mqtt_handler.send_set_schedule.call_args
    assert sched and sched.kwargs["enabled"] is False, "no se apagó el horario de la central"


def v05_traspaso_conserva_las_otras_centrales_del_anterior():
    _alta_como_la_app(A, OTRA)
    _alta_como_la_app(A, MAC)
    en_mano[MAC] = time.time()
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 200, r
    assert _lista(A) == [OTRA], _lista(A)
    assert db.reference(f"ESP32/{OTRA}/ownerUid").get() == A


def v06_prueba_fisica_vencida():
    _alta_como_la_app(A, MAC)
    en_mano[MAC] = time.time() - VENTANA_PRUEBA_FISICA - 5
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 409, r
    en_mano[MAC] = time.time()
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 200, r


def v07_la_prueba_fisica_es_de_esa_central():
    _alta_como_la_app(A, MAC)
    en_mano[OTRA] = time.time()                      # otra central en la mano, no esta
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 409, r


def v08_dos_cuentas_reclaman_a_la_vez():
    _alta_como_la_app(A, MAC)
    en_mano[MAC] = time.time()
    rs, _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC}), (C, "/equipos/reclamar", {"mac": MAC})], en_paralelo=True)
    assert all(r[0] == 200 for r in rs), rs
    dueno = db.reference(f"ESP32/{MAC}/ownerUid").get()
    tienen = [u for u in (A, B, C) if MAC in _lista(u)]
    assert tienen == [dueno], f"dueño {dueno} pero la tienen en su lista: {tienen}"


def v09_reclamar_y_borrar_a_la_vez():
    _alta_como_la_app(A, MAC)
    en_mano[MAC] = time.time()
    rs, _, _ = _api([(A, "/equipos/borrar", {"mac": MAC}), (B, "/equipos/reclamar", {"mac": MAC})], en_paralelo=True)
    nodo = db.reference(f"ESP32/{MAC}").get()
    if nodo:   # ganó el reclamo después del borrado
        assert nodo["ownerUid"] == B and _lista(B) == [MAC] and MAC not in _lista(A), (nodo, rs)
    else:      # ganó el borrado después del reclamo
        assert MAC not in _lista(A) and MAC not in _lista(B), rs


def v10_nodo_sin_dueno_de_antes_de_la_migracion():
    _sembrar({"ESP32": {MAC: {"Nombre": "vieja", "Telegram_ID": "999"}},
              "Usuarios": {A: {"userName": "Ana"}, B: {"Dispositivos": [MAC]}, C: {}}})
    assert not _pedir(A, "GET", f"ESP32/{MAC}"), "un nodo sin dueño se lee: la app no sabría que debe reclamarlo"
    en_mano[MAC] = time.time()
    camino, r = _alta_como_la_app(A, MAC, telegram="111")
    assert (camino, r[0]) == ("reclamar", 200), (camino, r)
    assert db.reference(f"ESP32/{MAC}/ownerUid").get() == A
    assert db.reference(f"ESP32/{MAC}/Telegram_ID").get() == "111", "el Telegram viejo sigue mandando"
    assert _lista(B) == [], "la cuenta vieja sigue teniéndola"


def v11_clave_legacy_de_16():
    _sembrar({"ESP32": {LEGACY: {"ownerUid": A, "Nombre": "legacy"}},
              "Usuarios": {A: {"Dispositivos": [LEGACY]}, B: {}, C: {}}})
    en_mano[LEGACY] = time.time()
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": LEGACY})])
    assert r[0] == 200, r
    assert _lista(A) == [] and _lista(B) == [LEGACY], (_lista(A), _lista(B))
    (r,), _, _ = _api([(B, "/equipos/borrar", {"mac": LEGACY})])
    assert r == (200, {"ok": True, "quitado": False}), r
    assert db.reference(f"ESP32/{LEGACY}").get() is None


def v12_datos_raros_en_el_reclamo():
    en_mano[MAC] = time.time()
    rs, _, _ = _api([(A, "/equipos/reclamar", {"mac": "../Usuarios"}),
                     (A, "/equipos/reclamar", {"mac": MAC, "telegram_id": "abc"}),
                     (A, "/equipos/reclamar", {"mac": MAC, "group_id": "-1; drop"}),
                     ("malo", "/equipos/reclamar", {"mac": MAC}),
                     (A, "/equipos/reclamar", {"mac": MAC, "nombre": "x" * 500})])
    assert [r[0] for r in rs] == [400, 400, 400, 401, 200], rs
    assert len(db.reference(f"ESP32/{MAC}/Nombre").get()) <= 60


def v13_lista_vieja_en_texto_con_comas():
    _sembrar({"ESP32": {MAC: {"ownerUid": A, "Nombre": "Casa"}},
              "Usuarios": {A: {"Dispositivos": f"{OTRA},{MAC}"}, B: {}, C: {}}})
    en_mano[MAC] = time.time()
    (r,), _, _ = _api([(B, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 200, r
    assert _lista(A) == [OTRA], _lista(A)


# --------------------------------------------------------------------------
# Borrado
# --------------------------------------------------------------------------

def v14_borrar_limpia_todo_y_deja_dar_de_alta_de_nuevo():
    _alta_como_la_app(A, MAC)
    db.reference(f"Usuarios/{B}/Dispositivos").set([MAC])         # resto de un traspaso viejo
    db.reference(f"Horarios/{A}/devices/{MAC}").set({"activationTime": "22:00"})
    (r,), _, _ = _api([(A, "/equipos/borrar", {"mac": MAC})])
    assert r == (200, {"ok": True, "quitado": False}), r
    assert db.reference(f"ESP32/{MAC}").get() is None
    assert _lista(A) == [] and _lista(B) == []
    assert not db.reference(f"Horarios/{A}/devices/{MAC}").get()
    camino, r = _alta_como_la_app(C, MAC)
    assert (camino, r[0]) == ("crear", 200), "tras borrarla no se puede volver a dar de alta"


def v15_nadie_borra_desde_el_cliente():
    _alta_como_la_app(A, MAC)
    assert not _pedir(A, "DELETE", f"ESP32/{MAC}"), "las reglas dejan borrar el nodo desde la app"
    assert not _pedir(B, "DELETE", f"ESP32/{MAC}")


def v16_borrar_lo_que_no_es_tuyo_ni_esta_en_tu_lista():
    _alta_como_la_app(A, MAC)
    (r,), _, _ = _api([(B, "/equipos/borrar", {"mac": MAC})])
    assert r[0] == 403, r                                         # antes del 23-nov: 503
    assert db.reference(f"ESP32/{MAC}/ownerUid").get() == A


# --------------------------------------------------------------------------
# Telegram: /start <uid>
# --------------------------------------------------------------------------

def v17_vincular_telegram_propaga_solo_a_lo_suyo():
    _alta_como_la_app(A, MAC)                                     # Telegram_ID vacío
    db.reference(f"ESP32/{OTRA}").set({"ownerUid": B, "Telegram_ID": ""})
    db.reference(f"Usuarios/{A}/Dispositivos").set([MAC, OTRA])   # OTRA en su lista pero es de Beto
    assert fm.vincular_chat_id(A, "555") == "vinculado"
    assert db.reference(f"Usuarios/{A}/telegram_id").get() == "555"
    assert db.reference(f"ESP32/{MAC}/Telegram_ID").get() == "555"
    assert db.reference(f"ESP32/{OTRA}/Telegram_ID").get() == "", "se escribió el Telegram en una central ajena"
    assert fm.vincular_chat_id(A, "555") == "ya_estaba"
    assert fm.vincular_chat_id(A, "666") == "otro"
    assert db.reference(f"Usuarios/{A}/telegram_id").get() == "555", "otro /start pisó el Telegram"


def v18_vincular_con_uid_inventado():
    assert fm.vincular_chat_id("uidNoExiste", "555") == "sin_cuenta"
    assert db.reference("Usuarios/uidNoExiste").get() is None, "un uid inventado creó una cuenta"


def v19_el_telegram_vinculado_no_pisa_el_de_la_central():
    _alta_como_la_app(A, MAC, telegram="111")
    assert fm.vincular_chat_id(A, "555") == "vinculado"
    assert db.reference(f"ESP32/{MAC}/Telegram_ID").get() == "111"


# --------------------------------------------------------------------------

def main() -> int:
    _cargar_reglas()
    pruebas = sorted((k, v) for k, v in globals().items() if k[:1] == "v" and k[1:3].isdigit())
    fallos = 0
    for nombre, fn in pruebas:
        _sembrar()
        try:
            fn()
            print(f"  ok     {nombre}")
        except Exception as e:
            fallos += 1
            print(f"  FALLA  {nombre}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} escenarios aguantan")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
