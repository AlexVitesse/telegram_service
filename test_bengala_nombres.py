#!/usr/bin/env python3
"""
Habilitar la bengala no es dispararla (22-oct): el firmware nuevo manda
bengala_habilitada/deshabilitada; bengala_activated sigue siendo «ACTIVADA»
porque tambien es el disparo de verdad.

    python test_bengala_nombres.py
"""
from mqtt_protocol import EventType, MqttEvent, TelegramFormatter, es_evento_tecnico


def texto(tipo: str) -> str:
    return TelegramFormatter.format_event(MqttEvent(device_id="AA", event_type=tipo, data={}), "Casa")


assert "habilitada" in texto("bengala_habilitada")
assert "ACTIVADA" not in texto("bengala_habilitada")
assert "deshabilitada" in texto("bengala_deshabilitada")
assert "deshabilitada" in texto("bengala_deactivated")   # firmware de antes
assert "ACTIVADA" in texto("bengala_activated")          # el disparo no se suaviza
assert not es_evento_tecnico(EventType.BENGALA_HABILITADA)
assert not es_evento_tecnico(EventType.BENGALA_DESHABILITADA)
print("ok")


# 27-oct: el estado de la bengala en el VPS sale de lo que confirma la central,
# no solo de los botones de Telegram (desde la app se quedaba en False).
from collections import OrderedDict
from unittest.mock import MagicMock
from device_manager import DeviceManager
from mqtt_handler import MqttHandler
from mqtt_protocol import Command

MAC = "08_D1_F9_29_E4"
h = MqttHandler.__new__(MqttHandler)
h.device_id, h.device_location = MAC, ""
h.firebase_manager = MagicMock()
h.firebase_manager.get_device_location.return_value = ""
h.device_manager = DeviceManager()
h.last_arm_event_time, h.prueba_fisica = {}, {}
h._ids_vistos, h._arranques_por_confirmar = OrderedDict(), {}
h._on_event_callback = None
h._modo_bengala_pedido = {}
evento = lambda tipo, data="{}": h._handle_event('{"deviceId": "%s", "eventType": "%s", "data": %s}' % (MAC, tipo, data))

evento("bengala_deshabilitada")
assert h.device_manager.is_bengala_enabled(MAC) is False
evento("bengala_habilitada")
assert h.device_manager.is_bengala_enabled(MAC) is True

h.device_manager.set_bengala_mode(MAC, 1, save_to_firebase=False)
h._modo_bengala_pedido[MAC] = 0                      # lo que send_command apunta
evento("cmd_ack", '{"cmd": "set_schedule", "ok": true}')
assert h.device_manager.get_bengala_mode(MAC) == 1   # otro ack no lo toca
evento("cmd_ack", '{"cmd": "%s", "ok": true}' % Command.SET_BENGALA_MODE.value)
assert h.device_manager.get_bengala_mode(MAC) == 0
print("ok estado de la bengala")
