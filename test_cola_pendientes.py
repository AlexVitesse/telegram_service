#!/usr/bin/env python3
"""
La cola de comandos para centrales offline: sobrevive y se envia.

Los fallos que vigila:
  - La cola vivia solo en memoria: un reinicio del VPS perdia el horario que
    una central offline tenia pendiente (o el "apaga tu horario" de una
    central borrada).
  - Solo se vaciaba al "reconectar", que se marca a los 90 s sin telemetria,
    mientras que se encola a partir de 60 s: un corte de 60-90 s, o un
    reinicio del VPS, dejaba la cola sin enviar.
  - Caducaba a las 24 h incluso para el horario, que gana el ultimo.

Sin red ni broker: el cliente MQTT es un MagicMock.

    python test_cola_pendientes.py
"""
import json
import logging
import os
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

logging.basicConfig(level=logging.CRITICAL)

from device_manager import DeviceManager
from mqtt_handler import MqttHandler

MAC = "6C_C8_40_4F_C7"
HORARIO = {"enabled": False, "on_hour": 0, "on_minute": 0, "off_hour": 0, "off_minute": 0}


def _handler(archivo):
    h = MqttHandler.__new__(MqttHandler)
    h.device_manager = DeviceManager(None)
    h.firebase_manager = MagicMock()
    h.firebase_manager.is_available.return_value = False
    h.client = MagicMock()
    h.client.publish.return_value = SimpleNamespace(rc=0)
    h.device_id = None
    h.device_location = ""
    h.LORA_EDAD_SOSPECHOSA = 30
    h.last_telemetry, h.last_telemetry_time = {}, {}
    h.last_arm_event_time, h.device_exit_time = {}, {}
    h.sensors_list, h.sensors_list_time = {}, {}
    h._on_event_callback = h._on_telemetry_callback = None
    h._on_reconnect_callback = h._on_sensors_list_callback = None
    h.prueba_fisica = {}
    h._pending_commands = {}
    h.pending_file = archivo
    h._load_pending()
    return h


def _archivo():
    return os.path.join(tempfile.mkdtemp(), "pending_commands.json")


def _publicados(h):
    return [json.loads(c.args[1])["command"] for c in h.client.publish.call_args_list]


def _telemetria(h, mac=MAC):
    h._handle_telemetry(json.dumps({"deviceId": mac, "armed": False}))


def test_encolar_offline_guarda_en_disco_y_otra_instancia_lo_carga():
    f = _archivo()
    h = _handler(f)
    h.send_command("set_schedule", HORARIO, device_id=MAC, queue_if_offline=True)
    assert _publicados(h) == [], "estaba offline: no tenia que publicar"
    assert os.path.exists(f)

    otra = _handler(f)  # "reinicio del VPS"
    assert otra.get_pending_commands_count(MAC) == 1


def test_la_primera_telemetria_vacia_la_cola_aunque_no_se_marcase_offline():
    """El hueco de 60-90 s y el del reinicio: no hay 'reconexion' que valga."""
    h = _handler(_archivo())
    h.send_command("set_schedule", HORARIO, device_id=MAC, queue_if_offline=True)
    assert not h.device_manager.devices_state.get(MAC, {}).get("offline_notified")

    _telemetria(h)

    assert _publicados(h).count("set_schedule") >= 1, _publicados(h)
    assert h.get_pending_commands_count(MAC) == 0


def test_tras_reiniciar_el_vps_la_cola_se_envia_con_la_primera_telemetria():
    f = _archivo()
    _handler(f).send_command("set_schedule", HORARIO, device_id=MAC, queue_if_offline=True)
    h = _handler(f)
    _telemetria(h)
    assert "set_schedule" in _publicados(h)
    assert json.load(open(f))["devices"] == {}, "la cola enviada seguia en disco"


def test_system_boot_vacia_la_cola_antes_de_la_telemetria():
    h = _handler(_archivo())
    h.send_command("set_schedule", HORARIO, device_id=MAC, queue_if_offline=True)
    h._handle_event(json.dumps({"deviceId": MAC, "eventType": "system_boot", "data": {}}))
    assert "set_schedule" in _publicados(h)


def test_el_horario_no_caduca_y_el_ultimo_gana():
    h = _handler(_archivo())
    viejo = dict(HORARIO, on_hour=7)
    nuevo = dict(HORARIO, on_hour=22)
    h._pending_commands[MAC] = [("set_schedule", viejo, time.time() - 3 * 86400)]
    h.send_command("set_schedule", nuevo, device_id=MAC, queue_if_offline=True)
    assert h.get_pending_commands_count(MAC) == 1

    _telemetria(h)

    enviados = [json.loads(c.args[1]) for c in h.client.publish.call_args_list]
    horas = [e["args"]["on_hour"] for e in enviados if e["command"] == "set_schedule"]
    assert horas and set(horas) == {22}, horas


def test_lo_que_no_es_configuracion_sigue_caducando():
    h = _handler(_archivo())
    h._pending_commands[MAC] = [("beep", {}, time.time() - 2 * 86400)]
    _telemetria(h)
    assert "beep" not in _publicados(h)


def test_un_envio_directo_descarta_el_pendiente_viejo():
    """Si no, al vaciar la cola el viejo pisaria al que se acaba de mandar."""
    h = _handler(_archivo())
    h._pending_commands[MAC + "_B2"] = [("set_schedule", dict(HORARIO, on_hour=7), time.time())]
    h.last_telemetry_time[MAC] = time.time()  # ahora esta online
    h.send_command("set_schedule", dict(HORARIO, on_hour=22), device_id=MAC)
    assert h.get_pending_commands_count() == 0


def test_archivo_roto_no_tumba_el_arranque():
    f = _archivo()
    open(f, "w").write("{esto no es json")
    h = _handler(f)
    assert h.get_pending_commands_count() == 0



def test_si_mqtt_no_acepta_la_publicacion_se_queda_en_la_cola():
    """Antes se sacaba de la cola ANTES de publicar: un fallo la perdia."""
    f = _archivo()
    h = _handler(f)
    h.send_command("set_schedule", HORARIO, device_id=MAC, queue_if_offline=True)
    h.client.publish.return_value = SimpleNamespace(rc=4)  # MQTT_ERR_NO_CONN
    _telemetria(h)
    assert h.get_pending_commands_count(MAC) == 1
    assert _handler(f).get_pending_commands_count(MAC) == 1, "no quedo en disco"


def test_con_variantes_de_id_gana_la_mas_reciente():
    h = _handler(_archivo())
    ahora = time.time()
    h._pending_commands = {
        MAC + "_B2": [("set_schedule", dict(HORARIO, on_hour=22), ahora)],
        MAC: [("set_schedule", dict(HORARIO, on_hour=7), ahora - 60)],
    }
    _telemetria(h)
    enviados = [json.loads(c.args[1]) for c in h.client.publish.call_args_list]
    horas = {e["args"]["on_hour"] for e in enviados if e["command"] == "set_schedule"}
    assert horas == {22}, horas
    assert h.get_pending_commands_count() == 0


def test_hilos_a_la_vez_no_rompen_la_cola_ni_el_archivo():
    """Paho (telemetria) y asyncio/API (send_command) tocan la cola a la vez."""
    import threading
    f = _archivo()
    h = _handler(f)
    errores = []

    def encolar(i):
        try:
            for n in range(30):
                h.send_command("set_schedule", dict(HORARIO, on_hour=n % 24),
                               device_id=f"AA_BB_CC_DD_{i:02d}", queue_if_offline=True)
        except Exception as e:
            errores.append(e)

    def vaciar(i):
        try:
            for _ in range(30):
                h.process_pending_commands(f"AA_BB_CC_DD_{i:02d}")
        except Exception as e:
            errores.append(e)

    hilos = [threading.Thread(target=fn, args=(i,)) for i in range(4) for fn in (encolar, vaciar)]
    for t in hilos:
        t.start()
    for t in hilos:
        t.join(10)
    assert not errores, errores
    json.load(open(f))  # el archivo sigue siendo JSON valido


def test_el_archivo_no_depende_del_directorio_de_trabajo():
    import mqtt_handler
    assert os.path.isabs(mqtt_handler.PENDING_FILE)


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except Exception as e:  # no solo AssertionError: un error no corta la suite
            fallos += 1
            print(f"FALLO  {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
