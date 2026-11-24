#!/usr/bin/env python3
"""
Familia (#124 F1): invitar, unirse, quitar, salir, traspaso, push y Orden.

Casos de §7 de docs/PLAN_FAMILIA_PARTICIPANTES_2026-11-18.md, con las
correcciones de Codex (C1-C7). Sin framework, sobre la RTDB de mentira de
test_retro_banco.py.

    python test_familia.py
"""
import asyncio
import copy
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import fcm_handler as fcm_mod
from mqtt_protocol import Command
from test_retro_banco import MAC, _fm

OTRA = "AA_AA_AA_AA_AA"


def _arbol():
    """Central de Jose con Ana de familia; Pedro no tiene nada que ver."""
    return {
        "ESP32": {MAC: {"ownerUid": "jose", "Nombre": "Casa", "Telegram_ID": "111", "Telegram_ID_2": "222",
                        "Answer": False, "miembros": {"ana": {"rol": "familia"}}}},
        "Miembros": {MAC: {"ana": {"nombre": "Ana", "alta": 1, "invitadoPor": "jose"}}},
        "Usuarios": {"jose": {"Dispositivos": [MAC, OTRA], "telegram_id": "111", "userName": "Jose"},
                     "ana": {"Dispositivos": [MAC], "telegram_id": "222", "userName": "Ana"},
                     "pedro": {"userName": "Pedro", "email": "pedro@x.mx"}},
        "Horarios": {"jose": {"devices": {MAC: {"activationTime": "22:00", "enabled": True}}}},
    }


def _llamar(fm, uid, peticiones):
    """La API de verdad sobre el FirebaseManager falso. Devuelve (respuestas, fcm)."""
    from test_api_server import con_api, pedir
    fcm = MagicMock()
    respuestas = []

    async def p(url, api):
        api._fcm = fcm
        for ruta, cuerpo in peticiones:
            respuestas.append(await pedir(url, token="bueno", cuerpo=cuerpo, ruta=ruta))
    asyncio.run(con_api(fm, uid, p))
    return respuestas, fcm


def _invitar(fm, remoto=False):
    (r,), _ = _llamar(fm, "jose", [("/equipos/invitar", {"mac": MAC, "remoto": remoto})])
    assert r[0] == 200, r
    return r[1]["codigo"]


# 1. Invitar ---------------------------------------------------------------

def test_invitar_solo_el_dueno_y_otro_codigo_anula_el_anterior():
    fm = _fm(_arbol())
    (r,), _ = _llamar(fm, "ana", [("/equipos/invitar", {"mac": MAC})])
    assert r[0] == 403, r                       # un miembro no invita
    primero = _invitar(fm)
    segundo = _invitar(fm, remoto=True)
    inv = fm.db.datos["Invitaciones"]
    assert primero not in inv and segundo in inv, inv
    assert len(segundo) == 8 and set(segundo) <= set(fm.ALFABETO_CODIGO)
    vence = inv[segundo]["expira"] - time.time()
    assert 24 * 3600 - 60 < vence <= 24 * 3600, vence     # remoto: 24 h
    _invitar(fm)
    (c,) = fm.db.datos["Invitaciones"].values()
    assert c["expira"] - time.time() <= 15 * 60           # QR: 15 min


# 2. Unirse ----------------------------------------------------------------

def test_unirse_escribe_membresia_lista_y_nombre_y_borra_el_codigo():
    fm = _fm(_arbol())
    fm.db.datos["ESP32"][MAC]["Local"] = {"key": "ab" * 32}   # copia de apps < 8.2
    codigo = _invitar(fm)
    (r, otra), fcm = _llamar(fm, "pedro", [("/equipos/unirse", {"codigo": codigo[:4].lower() + "-" + codigo[4:]}),
                                           ("/equipos/unirse", {"codigo": codigo})])
    assert r == (200, {"ok": True, "mac": MAC, "nombre": "Casa"}), r
    assert otra[0] == 404, otra                               # un solo uso
    d = fm.db.datos
    assert d["ESP32"][MAC]["miembros"]["pedro"] == {"rol": "familia"}   # solo rol (C3)
    assert "Local" not in d["ESP32"][MAC], d["ESP32"][MAC]          # la llave no queda al alcance (#274)
    assert d["Miembros"][MAC]["pedro"]["nombre"] == "Pedro"
    assert d["Usuarios"]["pedro"]["Dispositivos"] == [MAC]
    assert not d.get("Invitaciones"), d.get("Invitaciones")
    (uid, aviso), _ = fcm.send_to_user.call_args
    assert uid == "jose" and "Pedro se unió a Casa" in aviso.body, aviso
    assert aviso.notification_type == fcm_mod.NotificationType.ACCESS_CHANGED


def test_canje_que_fallo_en_la_lista_se_puede_reintentar_con_el_mismo_codigo():
    fm = _fm(_arbol())
    codigo = _invitar(fm)
    real = fm._agregar_a_mi_lista
    fm._agregar_a_mi_lista = MagicMock(side_effect=RuntimeError("red"))
    try:
        fm.unirse("pedro", codigo)
    except RuntimeError:
        pass
    fm._agregar_a_mi_lista = real
    assert fm.unirse("maria", codigo) == "no_existe"       # ya es de Pedro
    r = fm.unirse("pedro", codigo)
    assert isinstance(r, dict) and fm.db.datos["Usuarios"]["pedro"]["Dispositivos"] == [MAC], r


# 3. Códigos malos ----------------------------------------------------------

def test_codigo_vencido_raro_o_de_otro_dueno_no_toca_nada():
    fm = _fm(_arbol())
    vencido = _invitar(fm)
    fm.db.datos["Invitaciones"][vencido]["expira"] = int(time.time()) - 1
    antes = copy.deepcopy(fm.db.datos)
    rs, _ = _llamar(fm, "pedro", [("/equipos/unirse", {"codigo": vencido}),
                                  ("/equipos/unirse", {"codigo": "../Usuarios"}),
                                  ("/equipos/unirse", {"codigo": 123})])
    assert [r[0] for r in rs] == [404, 404, 404], rs
    assert len({r[1]["error"] for r in rs}) == 1            # indistinguibles (C7)
    assert fm.db.datos == antes

    viejo = _invitar(fm)
    fm.db.datos["ESP32"][MAC]["ownerUid"] = "maria"          # cambió de dueño
    assert fm.unirse("pedro", viejo) == "no_existe"
    assert "pedro" not in fm.db.datos["ESP32"][MAC]["miembros"]


def test_cinco_fallos_bloquean_al_que_adivina():
    fm = _fm(_arbol())
    codigo = _invitar(fm)
    rs, _ = _llamar(fm, "pedro", [("/equipos/unirse", {"codigo": "ZZZZZZZZ"})] * 5
                    + [("/equipos/unirse", {"codigo": codigo})])
    assert [r[0] for r in rs] == [404] * 5 + [429], rs
    assert "pedro" not in fm.db.datos["ESP32"][MAC]["miembros"]


# 4. Dueño y tope -----------------------------------------------------------

def test_el_dueno_no_se_une_y_tope_de_10():
    fm = _fm(_arbol())
    codigo = _invitar(fm)
    assert fm.unirse("jose", codigo) == "es_dueno"
    fm.db.datos["ESP32"][MAC]["miembros"] = {f"m{i}": {"rol": "familia"} for i in range(10)}
    assert fm.unirse("pedro", codigo) == "tope"
    (r,), _ = _llamar(fm, "jose", [("/equipos/invitar", {"mac": MAC})])
    assert r[0] == 409, r


# 5. Quitar ------------------------------------------------------------------

def test_quitar_solo_el_dueno_y_limpia_todo():
    fm = _fm(_arbol())
    (r,), _ = _llamar(fm, "ana", [("/equipos/miembros/quitar", {"mac": MAC, "uid": "ana"})])
    assert r[0] == 403, r
    (mal, r, otra), fcm = _llamar(fm, "jose", [
        ("/equipos/miembros/quitar", {"mac": MAC, "uid": "../x"}),
        ("/equipos/miembros/quitar", {"mac": MAC, "uid": "ana"}),
        ("/equipos/miembros/quitar", {"mac": MAC, "uid": "ana"})])
    assert (mal[0], r, otra[0]) == (400, (200, {"ok": True}), 404), (mal, r, otra)
    d = fm.db.datos
    assert "ana" not in d["ESP32"][MAC].get("miembros", {})
    assert "ana" not in d["Miembros"].get(MAC, {})
    assert "Dispositivos" not in d["Usuarios"]["ana"]
    assert "Telegram_ID_2" not in d["ESP32"][MAC]                 # era Ana: fuera
    assert d["ESP32"][MAC]["Telegram_ID"] == "111"
    fm.mqtt_handler.send_command.assert_called_once_with(
        Command.LOCAL_ROTATE.value, device_id=MAC, queue_if_offline=True)
    (uid, aviso), _ = fcm.send_to_user.call_args
    assert uid == "ana" and "Ya no tienes acceso a Casa" in aviso.body


def test_quitar_no_toca_el_usuario_2_si_es_de_otro():
    fm = _fm(_arbol())
    fm.db.datos["ESP32"][MAC]["Telegram_ID_2"] = "999"
    fm.quitar_miembro("jose", MAC, "ana")
    assert fm.db.datos["ESP32"][MAC]["Telegram_ID_2"] == "999"


def test_quitar_que_falla_a_medias_se_termina_al_reintentar():
    # #275: antes la membresia se borraba primero y el reintento daba
    # "no_es_miembro" con Telegram_ID_2 y la llave vieja aun vivos.
    fm = _fm(_arbol())
    real = fm._quitar_de_mi_lista
    fm._quitar_de_mi_lista = MagicMock(side_effect=RuntimeError("red"))
    try:
        fm.quitar_miembro("jose", MAC, "ana")
    except RuntimeError:
        pass
    fm._quitar_de_mi_lista = real
    assert "ana" in fm.db.datos["ESP32"][MAC]["miembros"]       # sigue: se puede reintentar
    assert isinstance(fm.quitar_miembro("jose", MAC, "ana"), dict)
    d = fm.db.datos
    assert "ana" not in d["ESP32"][MAC].get("miembros", {}) and "Telegram_ID_2" not in d["ESP32"][MAC]
    assert "Dispositivos" not in d["Usuarios"]["ana"]


def test_quitar_limpia_el_usuario_2_aunque_haya_cambiado_su_telegram():
    fm = _fm(_arbol())
    fm.db.datos["Miembros"][MAC]["ana"]["telegram"] = "222"     # el que tenia al unirse
    fm.db.datos["Usuarios"]["ana"]["telegram_id"] = "777"      # lo cambia antes de que la quiten
    fm.quitar_miembro("jose", MAC, "ana")
    assert "Telegram_ID_2" not in fm.db.datos["ESP32"][MAC]


def test_unirse_guarda_su_telegram_para_poder_quitarselo():
    fm = _fm(_arbol())
    fm.db.datos["Usuarios"]["pedro"]["telegram_id"] = "333"
    assert isinstance(fm.unirse("pedro", _invitar(fm)), dict)
    assert fm.db.datos["Miembros"][MAC]["pedro"]["telegram"] == "333"


def test_codigo_a_medio_canjear_no_sirve_para_volver_tras_ser_quitado():
    fm = _fm(_arbol())
    codigo = _invitar(fm)
    real = fm._agregar_a_mi_lista
    fm._agregar_a_mi_lista = MagicMock(side_effect=RuntimeError("red"))
    try:
        fm.unirse("pedro", codigo)                              # membresia hecha, lista no
    except RuntimeError:
        pass
    fm._agregar_a_mi_lista = real
    fm.quitar_miembro("jose", MAC, "pedro")
    assert fm.unirse("pedro", codigo) == "no_existe"
    assert "pedro" not in fm.db.datos["ESP32"][MAC]["miembros"]


# 6. Salir --------------------------------------------------------------------

def test_un_miembro_que_borra_sale_y_la_central_sigue():
    fm = _fm(_arbol())
    del fm.db.datos["Usuarios"]["ana"]["Dispositivos"]       # aunque ya no la tenga en su lista
    assert fm.borrar_equipo("ana", MAC) == "quitado"
    d = fm.db.datos
    assert MAC in d["ESP32"] and "ana" not in d["ESP32"][MAC].get("miembros", {})
    assert "ana" not in d["Miembros"].get(MAC, {})
    fm.mqtt_handler.send_command.assert_called_once()        # llave local nueva
    fm.mqtt_handler.reset_mock()
    assert fm.borrar_equipo("ana", MAC) == "no_es_dueno"     # ya sin acceso: nada
    fm.mqtt_handler.send_command.assert_not_called()


# 7. Traspaso -------------------------------------------------------------------

def test_traspaso_deja_la_central_sin_miembros():
    fm = _fm(_arbol())
    r = fm.reclamar_equipo("pedro", MAC)
    d = fm.db.datos
    assert r["traspaso"] and "ana" in r["anteriores"], r
    assert "miembros" not in d["ESP32"][MAC] and MAC not in d.get("Miembros", {})
    assert "Dispositivos" not in d["Usuarios"]["ana"]


# 8. Re-reclamo del dueño ----------------------------------------------------------

def test_reclamo_del_propio_dueno_con_miembros_no_es_traspaso():
    fm = _fm(_arbol())
    r = fm.reclamar_equipo("jose", MAC)
    d = fm.db.datos
    assert not r["traspaso"], r
    assert d["ESP32"][MAC]["miembros"] == {"ana": {"rol": "familia"}}
    assert d["ESP32"][MAC]["Telegram_ID_2"] == "222" and d["Horarios"]["jose"]["devices"][MAC]
    assert d["Usuarios"]["ana"]["Dispositivos"] == [MAC] and "ana" in d["Miembros"][MAC]


def test_borrar_la_central_borra_tambien_los_nombres():
    fm = _fm(_arbol())
    assert fm.borrar_equipo("jose", MAC) == "ok"
    assert MAC not in fm.db.datos.get("Miembros", {})


# 9-10. Push -------------------------------------------------------------------------

def _fcm(fm):
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    h.firebase_manager = fm
    h.initialized, h._messaging = True, MagicMock()
    h._last_notification_time, h.MIN_NOTIFICATION_INTERVAL = {}, 5
    return h


def test_push_autoritativo():
    datos = _arbol()
    datos["Usuarios"]["pedro"]["Dispositivos"] = [MAC]            # sabe la MAC, no es nadie
    datos["ESP32"][MAC]["miembros"]["luis"] = {"rol": "familia"}  # miembro sin ella en su lista
    datos["Usuarios"]["luis"] = {}
    h = _fcm(_fm(datos))
    assert h._get_users_for_device("6c:c8:40:4f:c7") == ["jose", "ana"]
    # Sin ownerUid (sin migrar): como antes, por lista.
    del datos["ESP32"][MAC]["ownerUid"]
    assert sorted(h._get_users_for_device(MAC)) == ["ana", "jose", "pedro"]


def test_solo_dueno():
    h = _fcm(_fm(_arbol()))
    h._quiere_aviso = lambda uid, tipo: True
    h.send_to_user = MagicMock(return_value=1)
    aviso = h.create_sensor_pending_notification("S1", "Casa", MAC)
    h.send_to_device_users(MAC, aviso, solo_dueno=True)
    assert [c.args[0] for c in h.send_to_user.call_args_list] == ["jose"]
    h.send_to_user.reset_mock()
    h.send_to_device_users(MAC, aviso)
    assert [c.args[0] for c in h.send_to_user.call_args_list] == ["jose", "ana"]


def test_aviso_de_miembro_salta_el_rate_limit():
    h = _fcm(_fm(_arbol()))
    h._get_user_tokens = lambda uid: [{"token": "t", "token_id": "1"}]
    h._update_token_last_used = lambda *a: None
    h._last_notification_time["jose"] = time.time()
    aviso = fcm_mod.PushNotification("Casa", "Ana armó Casa", {}, fcm_mod.NotificationType.MIEMBRO_ACCION)
    assert h.send_to_user("jose", aviso) == 1


# Orden (C1, C2) ----------------------------------------------------------------------

def _evento(mac, datos, ruta="Orden"):
    return SimpleNamespace(event_type="put", path=f"/{mac}/{ruta}", data=datos)


def test_orden_de_miembro_sin_broker_no_se_da_por_hecha():
    # #278: con la publicacion fallida se escribia Answer=True y se avisaba al
    # dueno de que Ana armo; la dedup impedia el reintento.
    fm = _fm(_arbol())
    fm._last_listener_event_time, fm._all_devices_cache = 0, None
    fm._update_cache_from_event = lambda e: None
    fm._ultima_orden, fm.on_sos, fm.on_orden_miembro = {}, MagicMock(), MagicMock()
    fm.mqtt_handler.send_command.return_value = False
    fm._app_command_listener(_evento(MAC, {"accion": "arm", "por": "ana", "ts": 1000}))
    assert fm.db.datos["ESP32"][MAC]["Answer"] is False
    fm.on_orden_miembro.assert_not_called()
    fm.mqtt_handler.send_command.return_value = True          # vuelve el broker
    fm._app_command_listener(_evento(MAC, {"accion": "arm", "por": "ana", "ts": 1000}))
    assert fm.db.datos["ESP32"][MAC]["Answer"] is True       # la reentrega si pasa
    fm.on_orden_miembro.assert_called_once()


def test_orden_de_miembro_manda_sincroniza_y_avisa_al_dueno():
    fm = _fm(_arbol())
    fm._last_listener_event_time, fm._all_devices_cache = 0, None
    fm._update_cache_from_event = lambda e: None
    fm._ultima_orden, fm.on_sos = {}, MagicMock()
    fm.on_orden_miembro = MagicMock()
    fm._app_command_listener(_evento(MAC, {"accion": "arm", "por": "ana", "ts": 1000}))
    fm.mqtt_handler.send_command.assert_called_once_with(cmd=Command.ARM.value, device_id=MAC)
    assert fm.db.datos["ESP32"][MAC]["Answer"] is True
    fm.on_orden_miembro.assert_called_once_with(MAC, "jose", "Ana", "arm", 1000, False)

    # Repetida (reconexión del listener): nada.
    fm._app_command_listener(_evento(MAC, {"accion": "arm", "por": "ana", "ts": 1000}))
    assert fm.mqtt_handler.send_command.call_count == 1

    # Local: ya salió por la LAN; solo sincroniza y avisa.
    fm._app_command_listener(_evento(MAC, {"accion": "disarm", "por": "ana", "ts": 2000, "local": True}))
    assert fm.mqtt_handler.send_command.call_count == 1
    assert fm.db.datos["ESP32"][MAC]["Answer"] is False
    assert fm.on_orden_miembro.call_args.args[-1] is True

    # Pánico: sirena y aviso al grupo.
    fm._app_command_listener(_evento(MAC, {"accion": "panic", "por": "ana", "ts": 3000}))
    fm.mqtt_handler.send_command.assert_called_with(cmd=Command.TRIGGER_ALARM.value, device_id=MAC)
    fm.on_sos.assert_called_once_with(MAC)

    # De alguien que no es miembro, o con acción rara: se ignora.
    fm._app_command_listener(_evento(MAC, {"accion": "disarm", "por": "pedro", "ts": 4000}))
    fm._app_command_listener(_evento(MAC, {"accion": "abrir", "por": "ana", "ts": 5000}))
    assert fm.mqtt_handler.send_command.call_count == 2


def _correr():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:
            print(f"  FALLO  {fn.__name__}: {type(e).__name__}: {e}")
            fallos += 1
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if _correr() else 0)
