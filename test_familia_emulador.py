#!/usr/bin/env python3
"""
Familia (#124) de punta a punta SIN teléfonos, tratando de romperlo.

Junta las tres piezas reales contra el emulador de la RTDB:
- las reglas de APP/database.rules.json (se suben al emulador);
- el listener del VPS (FirebaseManager._app_command_listener), escuchando de verdad;
- la API (/equipos/invitar, /unirse, /miembros/quitar, /borrar, /reclamar).
Los clientes escriben por REST con su propio token, como la app: lo que las
reglas niegan, se niega aquí también.

    FIREBASE_DATABASE_EMULATOR_HOST=127.0.0.1:9001 python test_familia_emulador.py

Sin FIREBASE_DATABASE_EMULATOR_HOST se salta: nunca toca la base real.
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

import logging
logging.basicConfig(handlers=[logging.NullHandler()])

import firebase_admin
from firebase_admin import credentials, db

import fcm_handler as fcm_mod
from firebase_manager import FirebaseManager
from mqtt_protocol import Command
from test_reglas_emulador import HOST, NS, _cargar_reglas, _pedir

MAC = "AC_15_18_D5_2D"
A, B, C, D = "uidDuenoA", "uidBetoB", "uidCarlaC", "uidDaniD"


class _SinCredenciales(credentials.Base):
    def get_credential(self):
        return MagicMock(token="owner", valid=True, expired=False)


def _esperar(cond, seg=5.0):
    fin = time.time() + seg
    while time.time() < fin:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


# --------------------------------------------------------------------------
# Montaje
# --------------------------------------------------------------------------

firebase_admin.initialize_app(_SinCredenciales(), {"databaseURL": f"http://{HOST}?ns={NS}"})


def _sembrar():
    db.reference("/").set({
        "ESP32": {MAC: {"ownerUid": A, "Nombre": "Casa", "Answer": False, "Estado": False,
                        "Telegram_ID": "111", "Telegram_ID_2": "222", "Tiempo_Bomba": 60}},
        "Usuarios": {A: {"Dispositivos": [MAC], "userName": "Ana Dueña", "telegram_id": "111"},
                     B: {"userName": "Beto", "telegram_id": "222"},
                     C: {"userName": "Carla"},
                     D: {"email": "dani@x.mx"}},
        "Horarios": {A: {"devices": {MAC: {"activationTime": "22:00", "enabled": True}}}},
    })


fm = FirebaseManager()
fm.db = db
fm.initialized = True
fm.is_available = lambda: True
fm.mqtt_handler = MagicMock()
fm._get_all_devices = lambda: db.reference("ESP32").get() or {}
fm.on_sos = MagicMock()
avisos = []
fm.on_orden_miembro = lambda *a: avisos.append(a)
mqtt = fm.mqtt_handler


def _enviados(cmd=None):
    return [c for c in mqtt.send_command.call_args_list
            if cmd is None or c.kwargs.get("cmd", c.args[0] if c.args else None) == cmd]


def _api(peticiones, en_paralelo=False):
    """[(uid, ruta, cuerpo)] contra la API real. El token ES el uid."""
    from test_api_server import con_api, pedir
    fcm = MagicMock()
    salida = []

    async def p(url, api):
        api._uid_del_token = lambda t: t if t and t.startswith("uid") else None
        api._fcm = fcm
        api._bot.mqtt_handler = SimpleNamespace(prueba_fisica={MAC: time.time()}, exige_codigo_alta=lambda m: False,
                                                send_command=MagicMock())
        llamadas = [pedir(url, token=u, cuerpo=c, ruta=r) for u, r, c in peticiones]
        if en_paralelo:
            salida.extend(await asyncio.gather(*llamadas))
        else:
            for ll in llamadas:
                salida.append(await ll)
    asyncio.run(con_api(fm, "nadie", p))
    return salida, fcm


def _invitar(remoto=False):
    (r,), _ = _api([(A, "/equipos/invitar", {"mac": MAC, "remoto": remoto})])
    assert r[0] == 200, r
    return r[1]["codigo"]


def _unir(uid):
    (r,), _ = _api([(uid, "/equipos/unirse", {"codigo": _invitar()})])
    assert r[0] == 200, r


def _orden(uid, accion, ts=None, **extra):
    return _pedir(uid, "PUT", f"ESP32/{MAC}/Orden",
                  {"accion": accion, "por": uid, "ts": ts or int(time.time() * 1000), **extra})


# --------------------------------------------------------------------------
# Escenarios
# --------------------------------------------------------------------------

def e01_alta_completa_y_lo_que_ve_cada_uno():
    codigo = _invitar()
    (r,), fcm = _api([(B, "/equipos/unirse", {"codigo": f" {codigo[:4].lower()}-{codigo[4:]} "})])
    assert r == (200, {"ok": True, "mac": MAC, "nombre": "Casa"}), r
    assert fcm.send_to_user.call_args.args[0] == A
    assert _pedir(B, "GET", f"ESP32/{MAC}"), "el miembro no lee la central"
    assert _pedir(B, "GET", f"Horarios/{A}/devices/{MAC}"), "el miembro no lee los horarios"
    assert not _pedir(B, "GET", f"Miembros/{MAC}"), "el miembro lee los nombres"
    assert not _pedir(C, "GET", f"ESP32/{MAC}"), "un ajeno lee la central"
    assert db.reference(f"Miembros/{MAC}/{B}/nombre").get() == "Beto"
    assert db.reference(f"Usuarios/{B}/Dispositivos").get() == [MAC]


def e02_dos_canjean_el_mismo_codigo_a_la_vez():
    codigo = _invitar()
    rs, _ = _api([(C, "/equipos/unirse", {"codigo": codigo}),
                  (D, "/equipos/unirse", {"codigo": codigo})], en_paralelo=True)
    assert sorted(r[0] for r in rs) == [200, 404], rs
    miembros = db.reference(f"ESP32/{MAC}/miembros").get() or {}
    assert len({C, D} & set(miembros)) == 1, miembros


def e03_dos_invitaciones_a_la_vez_dejan_un_solo_codigo():
    _api([(A, "/equipos/invitar", {"mac": MAC})] * 3, en_paralelo=True)
    vivas = [c for c, i in (db.reference("Invitaciones").get() or {}).items() if i.get("mac") == MAC]
    assert len(vivas) == 1, vivas


def e04_el_miembro_arma_y_al_dueno_le_llega_su_nombre():
    _unir(B)
    avisos.clear()
    ts = int(time.time() * 1000)
    assert _orden(B, "arm", ts), "las reglas negaron la Orden del miembro"
    assert _esperar(lambda: _enviados(Command.ARM.value)), "no llegó el ARM a la central"
    assert _esperar(lambda: db.reference(f"ESP32/{MAC}/Answer").get() is True), "Answer no se sincronizó"
    assert _esperar(lambda: avisos), "no se avisó al dueño"
    assert avisos[-1] == (MAC, A, "Beto", "arm", ts, False), avisos


def e05_el_miembro_no_puede_saltarse_orden():
    _unir(B)
    assert not _pedir(B, "PUT", f"ESP32/{MAC}/Answer", True)
    assert not _pedir(B, "PUT", f"ESP32/{MAC}/DisparoApp", {"x": True})
    assert not _pedir(B, "PUT", f"ESP32/{MAC}/Orden", {"accion": "arm", "por": A, "ts": 1})
    assert not _pedir(B, "PATCH", f"ESP32/{MAC}", {"ownerUid": B})
    assert not _pedir(B, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia"})
    assert not _pedir(C, "PUT", f"ESP32/{MAC}/Orden", {"accion": "disarm", "por": C, "ts": 1})
    time.sleep(0.5)
    assert not _enviados(), _enviados()


def e06_reloj_adelantado_de_un_miembro_no_bloquea_a_otro():
    _unir(B)
    _unir(C)
    ahora = int(time.time() * 1000)
    assert _orden(C, "arm", ahora + 10 * 60 * 1000)          # el teléfono de Carla va 10 min adelantado
    assert _esperar(lambda: _enviados(Command.ARM.value))
    assert _orden(B, "disarm", ahora)
    assert _esperar(lambda: _enviados(Command.DISARM.value)), \
        "la orden de Beto se perdió por el reloj del teléfono de Carla"


def e07_el_mismo_miembro_con_el_reloj_mal_no_se_bloquea_a_si_mismo():
    _unir(B)
    assert _orden(B, "arm", 4 * 10 ** 12)                     # año 2096 (las reglas cortan en 2100)
    assert _esperar(lambda: _enviados(Command.ARM.value))
    assert _orden(B, "disarm")                                # ya con la hora bien
    assert _esperar(lambda: _enviados(Command.DISARM.value)), \
        "un ts absurdo dejó al miembro sin poder mandar hasta reiniciar el VPS"


def e08_orden_escrita_con_update_del_nodo():
    _unir(B)
    ok = _pedir(B, "PATCH", f"ESP32/{MAC}",
                {"Orden": {"accion": "arm", "por": B, "ts": int(time.time() * 1000)}})
    if ok:   # si las reglas la dejan pasar, el VPS tiene que atenderla
        assert _esperar(lambda: _enviados(Command.ARM.value)), "Orden por update(): las reglas la aceptan y el VPS la ignora"


def e09_basura_en_orden_no_tumba_el_listener():
    _unir(B)
    for basura in ["x", [1, 2], {"accion": "arm"}, {"accion": "arm", "por": B, "ts": "1"},
                   {"accion": None, "por": B, "ts": 1}, {"accion": "arm", "por": 123, "ts": 1},
                   {"accion": "arm", "por": C, "ts": 5}, None]:
        ref = db.reference(f"ESP32/{MAC}/Orden")               # admin: sin reglas
        ref.delete() if basura is None else ref.set(basura)
        time.sleep(0.15)
    time.sleep(0.5)
    assert not _enviados(), f"la basura mandó comandos: {_enviados()}"
    assert _orden(B, "disarm")
    assert _esperar(lambda: _enviados(Command.DISARM.value)), "el listener murió con la basura"


def e10_panico_del_miembro():
    _unir(B)
    assert _orden(B, "panic")
    assert _esperar(lambda: _enviados(Command.TRIGGER_ALARM.value))
    assert _esperar(lambda: fm.on_sos.called)


def e11_orden_local_solo_avisa():
    _unir(B)
    avisos.clear()
    assert _orden(B, "arm", local=True)
    assert _esperar(lambda: avisos), "no avisó al dueño"
    time.sleep(0.3)
    assert not _enviados(Command.ARM.value), "repitió por MQTT lo que ya salió por la LAN"
    assert avisos[-1][-1] is True


def e12_quitar_corta_todo_al_momento():
    _unir(B)
    db.reference(f"Usuarios/{B}/telegram_id").set("222")
    (r,), fcm = _api([(A, "/equipos/miembros/quitar", {"mac": MAC, "uid": B})])
    assert r[0] == 200, r
    assert not _pedir(B, "GET", f"ESP32/{MAC}"), "el quitado sigue leyendo"
    assert not _pedir(B, "GET", f"Horarios/{A}/devices/{MAC}"), "el quitado sigue leyendo horarios"
    assert not _orden(B, "disarm"), "el quitado sigue mandando"
    assert db.reference(f"ESP32/{MAC}/Telegram_ID_2").get() is None, "sigue de Usuario 2 en Telegram"
    assert not db.reference(f"Usuarios/{B}/Dispositivos").get()
    assert _enviados(Command.LOCAL_ROTATE.value), "no se rotó la llave local"
    assert fcm.send_to_user.call_args.args[0] == B


def e13_el_quitado_vuelve_y_luego_sale_solo():
    _unir(B)
    _api([(A, "/equipos/miembros/quitar", {"mac": MAC, "uid": B})])
    _unir(B)
    (r,), _ = _api([(B, "/equipos/borrar", {"mac": MAC})])
    assert r == (200, {"ok": True, "quitado": True}), r
    assert db.reference(f"ESP32/{MAC}/ownerUid").get() == A, "salir borró la central del dueño"
    assert not _pedir(B, "GET", f"ESP32/{MAC}")
    (otra,), _ = _api([(B, "/equipos/borrar", {"mac": MAC})])
    assert otra[0] == 403, otra


def e14_traspaso_con_miembros_y_codigo_pendiente():
    _unir(B)
    pendiente = _invitar(remoto=True)
    (r,), _ = _api([(D, "/equipos/reclamar", {"mac": MAC})])
    assert r[0] == 200 and r[1]["traspaso"], r
    assert not _pedir(B, "GET", f"ESP32/{MAC}"), "el miembro del dueño anterior sigue dentro"
    assert not _pedir(A, "GET", f"ESP32/{MAC}"), "el dueño anterior sigue dentro"
    assert not db.reference(f"Miembros/{MAC}").get()
    (u,), _ = _api([(C, "/equipos/unirse", {"codigo": pendiente})])
    assert u[0] == 404, f"el código del dueño anterior sigue valiendo: {u}"


def e15_borrar_la_central_con_miembros():
    _unir(B)
    (r,), _ = _api([(A, "/equipos/borrar", {"mac": MAC})])
    assert r == (200, {"ok": True, "quitado": False}), r
    assert db.reference(f"ESP32/{MAC}").get() is None
    assert db.reference(f"Miembros/{MAC}").get() is None
    assert not db.reference(f"Usuarios/{B}/Dispositivos").get()


def e16_fuerza_bruta():
    codigo = _invitar()
    rs, _ = _api([(C, "/equipos/unirse", {"codigo": "ZZZZZZZZ"})] * 5 + [(C, "/equipos/unirse", {"codigo": codigo})])
    assert [r[0] for r in rs] == [404] * 5 + [429], rs
    rs, _ = _api([(f"uidBot{i}", "/equipos/unirse", {"codigo": "ZZZZZZZZ"}) for i in range(31)])
    assert rs[-1][0] == 429, f"sin tope global: {rs[-1]}"


def e17_tope_de_10():
    codigo = _invitar(remoto=True)
    db.reference(f"ESP32/{MAC}/miembros").set({f"uidM{i}": {"rol": "familia"} for i in range(10)})
    (r,), _ = _api([(B, "/equipos/unirse", {"codigo": codigo})])
    assert r[0] == 409, r
    (i,), _ = _api([(A, "/equipos/invitar", {"mac": MAC})])
    assert i[0] == 409, i


def e18_invitar_lo_ajeno_o_raro():
    rs, _ = _api([(B, "/equipos/invitar", {"mac": MAC}),
                  (A, "/equipos/invitar", {"mac": "00_00_00_00_00"}),
                  (A, "/equipos/invitar", {"mac": "../Usuarios"}),
                  (A, "/equipos/miembros/quitar", {"mac": MAC, "uid": "a/b"})])
    assert [r[0] for r in rs] == [403, 403, 400, 400], rs


def e19_nombre_malicioso():
    db.reference(f"Usuarios/{C}/userName").set("*_[x](http://mal)`" + "A" * 500)
    _unir(C)
    nombre = db.reference(f"Miembros/{MAC}/{C}/nombre").get()
    assert len(nombre) <= 60, len(nombre)


def e20_push_solo_a_dueno_y_miembros_con_la_mac():
    _unir(B)
    db.reference(f"Usuarios/{C}/Dispositivos").set([MAC])     # sabe la MAC, no es nadie
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    h.firebase_manager, h.initialized, h._messaging = fm, True, MagicMock()
    assert h._get_users_for_device(MAC) == [A, B], h._get_users_for_device(MAC)


def e21_central_borrada_despues_de_invitar():
    codigo = _invitar()
    db.reference(f"ESP32/{MAC}").delete()
    (r,), _ = _api([(B, "/equipos/unirse", {"codigo": codigo})])
    assert r[0] == 404, r
    assert not db.reference(f"Invitaciones/{codigo}").get(), "el código quedó vivo"


def e22_cuenta_sin_nodo_de_usuario():
    db.reference(f"Usuarios/{D}").delete()
    _unir(D)
    assert db.reference(f"Usuarios/{D}/Dispositivos").get() == [MAC]
    assert db.reference(f"Miembros/{MAC}/{D}/nombre").get() == "Sin nombre"


def e23_un_miembro_da_de_alta_la_central_de_la_familia_por_ble():
    """Resetea la central del dueño y la configura con su cuenta: con la central
    en la mano se la queda (decisión del plan). El dueño y los demás miembros la pierden."""
    _unir(B)
    _unir(C)
    assert _pedir(B, "GET", f"ESP32/{MAC}")                   # la app ve ownerUid ajeno → reclamar
    (r,), fcm = _api([(B, "/equipos/reclamar", {"mac": MAC, "nombre": "Mía"})])
    assert r == (200, {"ok": True, "traspaso": True}), r
    nodo = db.reference(f"ESP32/{MAC}").get()
    assert nodo["ownerUid"] == B and "miembros" not in nodo, nodo
    assert not db.reference(f"Miembros/{MAC}").get()
    assert not _pedir(A, "GET", f"ESP32/{MAC}") and not _pedir(C, "GET", f"ESP32/{MAC}")
    assert db.reference(f"Usuarios/{B}/Dispositivos").get() == [MAC]
    assert {c.args[0] for c in fcm.send_to_user.call_args_list} == {A, C}, "no se avisó al dueño y a Carla"


def e24_un_miembro_da_de_alta_una_central_nueva_suya():
    """Sigue siendo miembro de la de la familia y además es dueño de la suya."""
    _unir(B)
    nueva = "11_22_33_44_55"           # claves de 5 bloques, como las da la central
    assert _pedir(B, "GET", f"ESP32/{nueva}")                 # no existe: la crea con su ownerUid
    assert _pedir(B, "PUT", f"ESP32/{nueva}", {"Nombre": "Oficina", "ownerUid": B, "Answer": False})
    assert _pedir(B, "PUT", f"Usuarios/{B}/Dispositivos", [MAC, nueva])
    assert db.reference(f"ESP32/{MAC}/miembros/{B}").get() == {"rol": "familia"}
    assert not _pedir(A, "GET", f"ESP32/{nueva}"), "el dueño de la familia ve la central de Beto"
    (r,), _ = _api([(B, "/equipos/invitar", {"mac": MAC})])  # no puede invitar a la de Ana
    assert r[0] == 403, r
    (r,), _ = _api([(B, "/equipos/invitar", {"mac": nueva})])   # pero sí a la suya
    assert r[0] == 200, r


def e25_la_vendo_o_la_regalo_con_familia_y_olvido_borrarla():
    """Ana la vende con Beto de familia y un código de WhatsApp pendiente. Dani
    (ni familia ni plan) la resetea y la configura: se la queda, y no le llega
    nada de Ana ni de su familia; a ellos se les corta todo."""
    _unir(B)
    db.reference(f"Usuarios/{B}/telegram_id").set("222")
    _orden(B, "arm")                                          # deja su uid en Orden
    assert _esperar(lambda: _enviados(Command.ARM.value))
    pendiente = _invitar(remoto=True)
    assert not _pedir(D, "GET", f"ESP32/{MAC}")               # Dani no la puede leer → reclamar
    (r,), fcm = _api([(D, "/equipos/reclamar", {"mac": MAC, "nombre": "Casa de Dani", "telegram_id": "444"})])
    assert r == (200, {"ok": True, "traspaso": True}), r
    nodo = db.reference(f"ESP32/{MAC}").get()
    assert nodo["ownerUid"] == D and nodo["Telegram_ID"] == "444", nodo
    # A Dani no le queda nada de Ana ni de su familia.
    sobra = {k: nodo.get(k) for k in ("miembros", "Telegram_ID_2", "Orden") if nodo.get(k)}
    assert not sobra, f"a Dani le quedaron datos de la familia anterior: {sobra}"
    assert not _pedir(D, "GET", f"Miembros/{MAC}") or not db.reference(f"Miembros/{MAC}").get()
    assert not _pedir(D, "GET", f"Horarios/{A}/devices/{MAC}")
    # A Ana y a Beto se les corta todo.
    for uid in (A, B):
        assert not _pedir(uid, "GET", f"ESP32/{MAC}"), f"{uid} sigue leyendo la central vendida"
        assert not _orden(uid, "disarm"), f"{uid} sigue mandando a la central vendida"
        assert MAC not in (db.reference(f"Usuarios/{uid}/Dispositivos").get() or [])
    assert not db.reference(f"Horarios/{A}/devices/{MAC}").get(), "el horario de Ana seguiría armando la casa de Dani"
    (u,), _ = _api([(C, "/equipos/unirse", {"codigo": pendiente})])
    assert u[0] == 404, "el código de WhatsApp de Ana sigue metiendo gente a la central de Dani"
    assert {c.args[0] for c in fcm.send_to_user.call_args_list} >= {A, B}, "no se avisó a Ana y a Beto"


# --------------------------------------------------------------------------

def main() -> int:
    _cargar_reglas()
    _sembrar()
    listener = db.reference("ESP32").listen(fm._app_command_listener)
    time.sleep(1)   # primer evento: la foto completa
    fallos = 0
    try:
        for nombre, fn in sorted((k, v) for k, v in globals().items() if k[:1] == "e" and k[1:3].isdigit()):
            _sembrar()
            time.sleep(0.4)          # que el listener vea el árbol nuevo
            mqtt.reset_mock()
            fm.on_sos.reset_mock()
            fm._ultima_orden = {}
            try:
                fn()
                print(f"  ok     {nombre}")
            except Exception as e:
                fallos += 1
                print(f"  FALLA  {nombre}: {type(e).__name__}: {e}")
    finally:
        listener.close()
    total = sum(1 for k in globals() if k[:1] == "e" and k[1:3].isdigit())
    print(f"\n{total - fallos}/{total} escenarios aguantan")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
