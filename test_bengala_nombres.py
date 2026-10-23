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
