#!/usr/bin/env python3
"""
Fallos de las pruebas en el banco del 24/09 (PLAN_RETRO_BANCO_2026-09-24.md).

  - La push de alarma se descartaba por el rate limit de 5 s.
  - La push iba a usuarios ajenos: se comparaba la MAC por prefijo.
  - Un `_` sin escapar hacia que Telegram rechazara el aviso entero.
  - El armado decia lo mismo al empezar y al terminar la cuenta atras.

    python test_retro_banco.py
"""
import sys
import time
from unittest.mock import MagicMock

import fcm_handler as fcm_mod
from mqtt_protocol import EventType, MqttEvent, TelegramFormatter, escape_md


def _fcm(usuarios):
    fm = MagicMock()
    fm.is_available.return_value = True
    fm.db.reference.return_value.get.return_value = usuarios
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    h.firebase_manager = fm
    h.initialized = True
    h._messaging = MagicMock()
    h._messaging.UnregisteredError = type("UnregisteredError", (Exception,), {})
    h._last_notification_time = {}
    h.MIN_NOTIFICATION_INTERVAL = 5
    return h


def test_la_push_solo_va_a_quien_tiene_esa_mac():
    h = _fcm({
        "pedrito": {"Dispositivos": ["A0_A3_B3_2F_A2"]},
        "jose": {"Dispositivos": ["6C_C8_40_4F_C7"]},
        "legado": {"Dispositivos": "6C_C8_40_4F_C7X,11_22_33_44_55"},
        "completa": {"Dispositivos": ["6c:c8:40:4f:c7:99"]},
        "vacia": {"Dispositivos": ["", None]},
    })
    assert sorted(h._get_users_for_device("6C_C8_40_4F_C7")) == ["completa", "jose", "legado"]


def test_un_id_largo_ya_no_le_llega_a_todos():
    # Antes: id de mas de 17 caracteres -> prefijo vacio -> todos coincidian.
    h = _fcm({"a": {"Dispositivos": ["6C_C8_40_4F_C7"]}, "b": {"Dispositivos": ["11_22_33_44_55"]}})
    assert h._get_users_for_device("6C_C8_40_4F_C7_AB_CD") == []


def test_la_alarma_salta_el_rate_limit():
    h = _fcm(None)
    h._get_user_tokens = lambda uid: [{"token": "t", "token_id": "1"}]
    h._update_token_last_used = lambda *a: None
    h._last_notification_time["u"] = time.time()   # justo se le aviso de movimiento
    alarma = h.create_alarm_notification(device_location="Casa", sensor_name="PIR", device_id="D1")
    assert h.send_to_user("u", alarma) == 1
    armado = h.create_protected_notification(device_location="Casa", device_id="D1")
    assert h.send_to_user("u", armado) == 0   # el resto si respeta el limite


def test_un_envio_fallido_no_bloquea_el_siguiente():
    h = _fcm(None)
    h._get_user_tokens = lambda uid: [{"token": "t", "token_id": "1"}]
    h._messaging.send.side_effect = RuntimeError("fcm caido")
    h.send_to_user("u", h.create_protected_notification(device_location="C", device_id="D1"))
    assert "u" not in h._last_notification_time


def test_escape_md():
    assert escape_md("mi_casa *1* [x] `y`") == r"mi\_casa \*1\* \[x] \`y\`"


def test_evento_generico_con_guiones_bajos_va_escapado():
    ev = MqttEvent(event_type="watchdog_lora_reboot", device_id="6C_C8_40_4F_C7", data={})
    msg = TelegramFormatter.format_event(ev)
    assert r"watchdog\_lora\_reboot" in msg and r"6C\_C8\_40\_4F\_C7" in msg, msg


def test_armado_distingue_inicio_y_fin_de_la_cuenta():
    inicio = TelegramFormatter.format_event(
        MqttEvent(event_type=EventType.SYSTEM_ARMED, device_id="D1", data={"source": "schedule"}), "josu2")
    fin = TelegramFormatter.format_event(
        MqttEvent(event_type=EventType.SYSTEM_ARMED, device_id="D1", data={"source": "local"}), "josu2")
    assert "Armando" in inicio and "Protección activa" in fin, (inicio, fin)


# --------------------------------------------------------------------------
# Propiedad del equipo, horarios por dueno, migracion y eventos tecnicos
# --------------------------------------------------------------------------

import asyncio
import copy
from types import SimpleNamespace

MAC = "6C_C8_40_4F_C7"


class _Arbol:
    """Una RTDB de mentira: reference(ruta).get/set/update/delete sobre un dict."""

    def __init__(self, datos):
        self.datos = datos

    def reference(self, ruta):
        return _Ref(self, [p for p in ruta.strip("/").split("/") if p])


class _Ref:
    def __init__(self, arbol, partes):
        self.arbol, self.partes = arbol, partes

    def get(self):
        d = self.arbol.datos
        for p in self.partes:
            if not isinstance(d, dict) or p not in d:
                return None
            d = d[p]
        return copy.deepcopy(d)

    def set(self, valor):
        if valor is None:
            return self.delete()
        d = self.arbol.datos
        for p in self.partes[:-1]:
            d = d.setdefault(p, {})
        d[self.partes[-1]] = copy.deepcopy(valor)

    def transaction(self, fn):
        """Como la de firebase_admin: aplica fn al valor actual; None borra."""
        nuevo = fn(self.get())
        self.set(nuevo)
        return nuevo

    def update(self, cambios):
        for k, v in cambios.items():
            _Ref(self.arbol, self.partes + k.split("/")).set(v)

    def delete(self):
        d = self.arbol.datos
        for p in self.partes[:-1]:
            if not isinstance(d, dict) or p not in d:
                return
            d = d[p]
        d.pop(self.partes[-1], None)


def _fm(datos):
    from firebase_manager import FirebaseManager
    fm = FirebaseManager.__new__(FirebaseManager)
    fm.db = _Arbol(datos)
    fm.is_available = lambda: True
    fm._get_all_devices = lambda: fm.db.datos.get("ESP32", {})
    fm.invalidate_cache = lambda: None
    fm.mqtt_handler = MagicMock()
    return fm


def _arbol_jose():
    """La central de Jose, tal como la dejo el banco: Pedrito tambien la tenia."""
    return {
        "ESP32": {MAC: {"ownerUid": "jose", "Nombre": "josu2", "Telegram_ID": "111",
                        "Telegram_ID_2": "222", "ModoBengala": 1, "Tiempo_Bomba": 5}},
        "Usuarios": {"jose": {"Dispositivos": [MAC, "AA_AA_AA_AA_AA"], "telegram_id": "111"},
                     "pedro": {"Dispositivos": [MAC]}},
        "Horarios": {"jose": {"devices": {MAC: {"activationTime": "07:00", "deactivationTime": "18:00", "enabled": True}}},
                     "111": {"devices": {MAC: {"activationTime": "22:00", "deactivationTime": "07:00", "enabled": True}}}},
    }


def _api(fm, uid, peticiones, en_mano=True):
    """
    Levanta la API de verdad (con_api de test_api_server) sobre el
    FirebaseManager falso y hace las peticiones: [(ruta, cuerpo), ...].
    """
    from test_api_server import con_api, pedir
    respuestas = []

    async def p(url, api):
        if en_mano:
            api._bot.mqtt_handler = SimpleNamespace(prueba_fisica={MAC: time.time()})
        for ruta, cuerpo in peticiones:
            respuestas.append(await pedir(url, token="bueno", cuerpo=cuerpo, ruta=ruta))
    asyncio.run(con_api(fm, uid, p))
    return respuestas


def test_reclamar_sin_la_central_en_la_mano_es_409():
    fm = _fm(_arbol_jose())
    antes = copy.deepcopy(fm.db.datos)
    (r,) = _api(fm, "pedro", [("/equipos/reclamar", {"mac": MAC})], en_mano=False)
    assert r[0] == 409, r
    assert fm.db.datos == antes   # conocer la MAC no basta


def test_reclamar_con_la_central_en_la_mano_traspasa_y_limpia():
    fm = _fm(_arbol_jose())
    (r,) = _api(fm, "pedro", [("/equipos/reclamar",
                               {"mac": "6c:c8:40:4f:c7:99", "nombre": "casa", "telegram_id": "333"})])
    assert r == (200, {"ok": True, "traspaso": True}), r
    d = fm.db.datos
    nodo = d["ESP32"][MAC]
    assert nodo["ownerUid"] == "pedro" and nodo["Telegram_ID"] == "333", nodo
    assert "Telegram_ID_2" not in nodo                              # el Telegram del anterior fuera
    assert nodo["ModoBengala"] == 1 and nodo["Tiempo_Bomba"] == 5   # la config se conserva
    assert d["Usuarios"]["jose"]["Dispositivos"] == ["AA_AA_AA_AA_AA"]
    assert d["Usuarios"]["pedro"]["Dispositivos"] == [MAC]
    assert all(MAC not in h["devices"] for h in d["Horarios"].values()), d["Horarios"]
    args = fm.mqtt_handler.send_set_schedule.call_args.kwargs
    assert args["enabled"] is False and args["queue_if_offline"] is True


def test_borrar_solo_el_dueno_y_limpia_todo():
    fm = _fm(_arbol_jose())
    # Pedro la tiene en su lista pero es de Jose: se le quita a el y nada mas.
    assert fm.borrar_equipo("pedro", MAC) == "quitado"
    assert MAC in fm.db.datos["ESP32"]
    assert "Dispositivos" not in fm.db.datos["Usuarios"]["pedro"]
    assert MAC in fm.db.datos["Usuarios"]["jose"]["Dispositivos"]
    # Ya sin ella en su lista, otro intento si es "no es tuya".
    assert fm.borrar_equipo("pedro", MAC) == "no_es_dueno"

    assert fm.borrar_equipo("jose", MAC) == "ok"
    d = fm.db.datos
    assert MAC not in d["ESP32"]
    assert "Dispositivos" not in d["Usuarios"]["pedro"]
    assert d["Usuarios"]["jose"]["Dispositivos"] == ["AA_AA_AA_AA_AA"]
    assert all(MAC not in h["devices"] for h in d["Horarios"].values())


def test_endpoint_borrar_no_dueno_es_403_y_mac_rara_400():
    fm = _fm(_arbol_jose())
    del fm.db.datos["Usuarios"]["pedro"]["Dispositivos"]  # ni dueno ni en su lista
    r, mala = _api(fm, "pedro", [("/equipos/borrar", {"mac": MAC}),
                                 ("/equipos/borrar", {"mac": "../Usuarios"})])
    assert r[0] == 403 and mala[0] == 400, (r, mala)
    assert MAC in fm.db.datos["ESP32"]


def test_endpoint_borrar_la_ajena_de_mi_lista_es_ok_y_no_toca_la_central():
    """
    La tarjeta "Error al cargar" de la app: central de otra cuenta que sigue en
    mi lista. Antes daba 403 y no habia forma de quitarla.
    """
    fm = _fm(_arbol_jose())
    (r,) = _api(fm, "pedro", [("/equipos/borrar", {"mac": MAC})])
    assert r[0] == 200 and r[1] == {"ok": True, "quitado": True}, r
    d = fm.db.datos
    assert MAC in d["ESP32"] and d["ESP32"][MAC]["ownerUid"] == "jose"
    assert "Dispositivos" not in d["Usuarios"]["pedro"]
    assert MAC in d["Usuarios"]["jose"]["Dispositivos"]


def test_quitar_la_ajena_no_toca_horarios_ni_central_del_dueno():
    fm = _fm(_arbol_jose())
    horarios_antes = fm.db.datos["Horarios"]
    assert fm.borrar_equipo("pedro", MAC) == "quitado"
    assert fm.db.datos["Horarios"] == horarios_antes
    fm.mqtt_handler.send_set_schedule.assert_not_called()


def test_si_el_nodo_no_existe_solo_se_limpia_mi_lista():
    """
    Estar en una lista que escribe el cliente no autoriza a tocar las de otros:
    cualquiera puede meterse una MAC en su propia lista.
    """
    datos = _arbol_jose()
    del datos["ESP32"][MAC]
    fm = _fm(datos)
    assert fm.borrar_equipo("pedro", MAC) == "quitado"
    d = fm.db.datos
    assert "Dispositivos" not in d["Usuarios"]["pedro"]
    assert MAC in d["Usuarios"]["jose"]["Dispositivos"]
    assert MAC in d["Horarios"]["jose"]["devices"]
    fm.mqtt_handler.send_set_schedule.assert_not_called()


def test_quitar_la_ajena_conserva_las_otras_de_mi_lista():
    datos = _arbol_jose()
    datos["Usuarios"]["pedro"]["Dispositivos"] = [MAC, "BB_BB_BB_BB_BB"]
    fm = _fm(datos)
    assert fm.borrar_equipo("pedro", MAC) == "quitado"
    assert fm.db.datos["Usuarios"]["pedro"]["Dispositivos"] == ["BB_BB_BB_BB_BB"]


def test_reclamar_y_borrar_no_se_pisan():
    """Los dos pasan por el mismo lock: un borrado no corre con la foto vieja."""
    import threading
    from firebase_manager import FirebaseManager
    fm = _fm(_arbol_jose())
    dentro = threading.Event()
    soltar = threading.Event()
    original = fm._borrar_equipo

    def borrar_lento(uid, mac):
        dentro.set()
        soltar.wait(5)
        return original(uid, mac)

    fm._borrar_equipo = borrar_lento
    hilo = threading.Thread(target=fm.borrar_equipo, args=("jose", MAC))
    hilo.start()
    dentro.wait(5)
    assert FirebaseManager._lock_propiedad.locked(), "el borrado tenia que tener el lock"
    soltar.set()
    hilo.join(5)
    assert not FirebaseManager._lock_propiedad.locked()


def test_horario_de_quien_no_es_el_dueno_no_cuenta():
    """El caso de los recordatorios cruzados: la entrada de otro no arma la central."""
    import scheduler as sch
    datos = _arbol_jose()
    datos["Horarios"] = {"pedro": {"devices": {MAC: {"activationTime": "07:00", "deactivationTime": "18:00", "enabled": True}}}}
    fm = _fm(datos)
    guardadas, sch.scheduler.configs = sch.scheduler.configs, {MAC: sch.ScheduleConfig(enabled=True)}
    guardar, sch.scheduler._save_configs = sch.scheduler._save_configs, lambda: None
    try:
        fm._recalcular_horarios()
        assert MAC not in sch.scheduler.configs        # huerfano: fuera
        assert fm.mqtt_handler.send_set_schedule.call_args.kwargs["enabled"] is False

        datos["Horarios"]["jose"] = {"devices": {MAC: {"activationTime": "07:00", "deactivationTime": "18:00", "enabled": True}}}
        fm._recalcular_horarios()
        assert sch.scheduler.configs[MAC].on_hour == 7   # la del dueno si
    finally:
        sch.scheduler.configs, sch.scheduler._save_configs = guardadas, guardar


def test_vincular_propaga_el_chat_id_a_sus_equipos():
    datos = {"ESP32": {MAC: {"ownerUid": "jose", "Telegram_ID": ""},
                       "BB_BB_BB_BB_BB": {"ownerUid": "otro", "Telegram_ID": ""}},
             "Usuarios": {"jose": {"Dispositivos": [MAC, "BB_BB_BB_BB_BB"]}}}
    fm = _fm(datos)
    fm.update_data = lambda ruta, v: fm.db.reference(ruta).update(v) or True
    assert fm.vincular_chat_id("jose", "555") == "vinculado"
    assert datos["ESP32"][MAC]["Telegram_ID"] == "555"
    assert datos["ESP32"]["BB_BB_BB_BB_BB"]["Telegram_ID"] == ""   # no es suyo


def test_migracion_en_modo_informe():
    from migrar_retro_banco import planificar
    arbol = _arbol_jose()
    del arbol["ESP32"][MAC]["ownerUid"]
    arbol["Horarios"]["111"]["devices"]["system"] = {"activationTime": "06:00", "deactivationTime": "08:00",
                                                     "enabled": True, "lastUpdated": "2026-09-20T00:00:00Z"}
    arbol["Horarios"]["111"]["devices"]["ZZ_ZZ_ZZ_ZZ_ZZ"] = {"activationTime": "01:00", "deactivationTime": "02:00"}
    antes = copy.deepcopy(arbol)
    cambios, informe = planificar(arbol)
    assert arbol == antes                              # planificar no escribe
    assert cambios[f"ESP32/{MAC}/ownerUid"] == "jose"  # decide el Telegram_ID
    assert cambios["Usuarios/pedro/Dispositivos"] is None
    assert cambios[f"Horarios/jose/devices/{MAC}"]["activationTime"] == "06:00"   # el mas reciente
    assert cambios[f"Horarios/111/devices/{MAC}"] is None
    assert cambios["Horarios/111/devices/system"] is None
    assert cambios["Horarios/111/devices/ZZ_ZZ_ZZ_ZZ_ZZ"] is None  # equipo que no existe


def test_migracion_no_decide_un_conflicto():
    from migrar_retro_banco import planificar
    arbol = _arbol_jose()
    del arbol["ESP32"][MAC]["ownerUid"]
    arbol["ESP32"][MAC]["Telegram_ID"] = "999"         # no coincide con nadie
    cambios, informe = planificar(arbol)
    assert f"ESP32/{MAC}/ownerUid" not in cambios
    assert any("CONFLICTO" in l for l in informe)


def test_eventos_tecnicos_solo_al_admin():
    from mqtt_protocol import es_evento_tecnico
    for tipo in ("system_boot", "watchdog_lora_reboot", "config_mode_started", "wifi_disconnected"):
        assert es_evento_tecnico(tipo), tipo
    for tipo in ("system_armed", "alarm_triggered", "movement_detected"):
        assert not es_evento_tecnico(tipo), tipo
    msg = TelegramFormatter.format_event(
        MqttEvent(event_type=EventType.SYSTEM_ARMED, device_id="D1", data={"source": "boot"}), "josu2")
    assert "reinici" in msg and "ARMADA" in msg, msg


def test_mac_valida_acepta_claves_antiguas_de_16_y_nada_mas():
    from api_server import _MAC_VALIDA
    for mac in ("6C_C8_40_4F_C7", "AC_15_18_D4_47_4"):
        assert _MAC_VALIDA.fullmatch(mac), mac
    for mac in ("../Usuarios", "AC_15_18_D4_47_", "AC_15_18_D4_47_4Z"):
        assert not _MAC_VALIDA.fullmatch(mac), mac


def _correr():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            print(f"  FALLO  {fn.__name__}: {e}")
            fallos += 1
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if _correr() else 0)
