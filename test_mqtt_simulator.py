#!/usr/bin/env python3
"""
Simulador de ESP32 para pruebas del servicio Telegram Bridge
============================================================
Nueva arquitectura: Simula eventos y telemetria que publica el ESP32.

Uso:
    python test_mqtt_simulator.py [comando]

Comandos:
    boot        - Simula evento system_boot
    armed       - Simula evento system_armed
    disarmed    - Simula evento system_disarmed
    alarm       - Simula alarma disparada
    stopped     - Simula alarma detenida
    movement    - Simula movimiento detectado
    door        - Simula puerta abierta
    telemetry   - Publica telemetria
    status      - Publica status_response
    menu        - Modo interactivo con menu
"""
import json
import sys
import time
import ssl
import io
import os
import paho.mqtt.client as mqtt
from datetime import datetime

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Cargar configuracion desde .env si existe
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

load_env()

# Configuracion
MQTT_BROKER = os.getenv("MQTT_BROKER", "9f6abf617b8b46d2a7ac1a975daceb9f.s1.eu.hivemq.cloud")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER = os.getenv("MQTT_USER", "prueba1")
MQTT_PASS = os.getenv("MQTT_PASS", "pedroCandy1")
MQTT_USE_TLS = os.getenv("MQTT_USE_TLS", "true").lower() == "true"
DEVICE_ID = os.getenv("DEVICE_ID", "esp32_test")
DEVICE_LOCATION = "Casa Test"

# Topics (nueva arquitectura)
TOPIC_EVENTOS = "dispositivos/eventos"
TOPIC_TELEMETRIA = "dispositivos/estado_telemetria"
TOPIC_COMANDOS = f"dispositivos/comandos/{DEVICE_ID}"


def get_timestamp():
    return int(time.time())


def publish_event(client, event_type, data=None):
    """Publica un evento al topic de eventos"""
    payload = {
        "deviceId": DEVICE_ID,
        "timestamp": get_timestamp(),
        "eventType": event_type,
        "data": data or {}
    }
    client.publish(TOPIC_EVENTOS, json.dumps(payload), qos=1)
    print(f"[OK] Evento publicado: {event_type}")


def publish_telemetry(client, armed=True):
    """Publica telemetria periodica"""
    payload = {
        "deviceId": DEVICE_ID,
        "timestamp": get_timestamp(),
        "armed": armed,
        "alarm_active": False,
        "bengala_enabled": True,
        "wifi_rssi": -55,
        "heap_free": 180000,
        "uptime_sec": 3600,
        "lora_sensors_active": 3,
        "auto_schedule_enabled": True
    }
    client.publish(TOPIC_TELEMETRIA, json.dumps(payload), qos=0)
    print(f"[OK] Telemetria publicada: armed={armed}")


def publish_system_boot(client):
    """Simula evento de inicio del sistema"""
    publish_event(client, "system_boot", {
        "version": "2.0",
        "location": DEVICE_LOCATION,
        "heap_free": 180000
    })


def publish_system_armed(client, source="remote"):
    """Simula evento de sistema armado"""
    publish_event(client, "system_armed", {"source": source})


def publish_system_disarmed(client, source="remote"):
    """Simula evento de sistema desarmado"""
    publish_event(client, "system_disarmed", {"source": source})


def publish_alarm_triggered(client, sensor_name="Sensor Test"):
    """Simula alarma disparada"""
    publish_event(client, "alarm_triggered", {
        "sensorId": "sensor_001",
        "sensorName": sensor_name
    })


def publish_alarm_stopped(client):
    """Simula alarma detenida"""
    publish_event(client, "alarm_stopped", {})


def publish_movement_detected(client, sensor_name="PIR Sala", location="Sala"):
    """Simula movimiento detectado"""
    publish_event(client, "movement_detected", {
        "sensorId": "pir_001",
        "sensorName": sensor_name,
        "location": location
    })


def publish_door_open(client, sensor_name="Puerta Principal", location="Entrada"):
    """Simula puerta abierta"""
    publish_event(client, "door_open", {
        "sensorId": "door_001",
        "sensorName": sensor_name,
        "location": location
    })


def publish_bengala_activated(client):
    """Simula bengala activada"""
    publish_event(client, "bengala_activated", {})


def publish_bengala_deactivated(client):
    """Simula bengala desactivada"""
    publish_event(client, "bengala_deactivated", {})


def publish_status_response(client):
    """Simula respuesta de status"""
    publish_event(client, "status_response", {
        "armed": True,
        "bengala_enabled": True,
        "sensors_count": 3,
        "auto_schedule_enabled": True,
        "auto_on_time": "22:00",
        "auto_off_time": "06:00"
    })


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[OK] Conectado a MQTT broker: {MQTT_BROKER}")
        # Suscribirse a comandos para ver lo que llega
        client.subscribe(TOPIC_COMANDOS)
        print(f"[OK] Suscrito a: {TOPIC_COMANDOS}")
    else:
        print(f"[ERROR] Error de conexion: {rc}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"\n[COMANDO RECIBIDO]")
        print(f"   Topic: {msg.topic}")
        print(f"   Comando: {payload.get('command', 'N/A')}")
        print(f"   Args: {payload.get('args', {})}")
        print(f"   Timestamp: {payload.get('timestamp', 'N/A')}")

        # Responder automaticamente segun el comando
        cmd = payload.get('command', '')

        if cmd == 'arm':
            publish_system_armed(client, "remote")
        elif cmd == 'disarm':
            publish_system_disarmed(client, "remote")
        elif cmd == 'trigger_alarm':
            publish_alarm_triggered(client, "Manual")
        elif cmd == 'stop_alarm':
            publish_alarm_stopped(client)
        elif cmd == 'activate_bengala':
            publish_bengala_activated(client)
        elif cmd == 'deactivate_bengala':
            publish_bengala_deactivated(client)
        elif cmd == 'get_status':
            publish_status_response(client)
        elif cmd == 'beep':
            print("   [BEEP] Simulando beep...")

    except Exception as e:
        print(f"[ERROR] Error procesando mensaje: {e}")


def interactive_menu(client):
    """Menu interactivo para pruebas"""
    while True:
        print("\n" + "="*50)
        print("SIMULADOR ESP32 - MENU DE PRUEBAS")
        print("="*50)
        print("1. Evento: System Boot")
        print("2. Evento: Sistema Armado")
        print("3. Evento: Sistema Desarmado")
        print("4. Evento: Alarma Disparada")
        print("5. Evento: Alarma Detenida")
        print("6. Evento: Movimiento Detectado")
        print("7. Evento: Puerta Abierta")
        print("8. Evento: Bengala Activada")
        print("9. Evento: Bengala Desactivada")
        print("10. Publicar Telemetria (armado)")
        print("11. Publicar Telemetria (desarmado)")
        print("12. Publicar Status Response")
        print("0. Salir")
        print("-"*50)

        try:
            choice = input("Selecciona una opcion: ").strip()

            if choice == "1":
                publish_system_boot(client)
            elif choice == "2":
                publish_system_armed(client)
            elif choice == "3":
                publish_system_disarmed(client)
            elif choice == "4":
                publish_alarm_triggered(client)
            elif choice == "5":
                publish_alarm_stopped(client)
            elif choice == "6":
                publish_movement_detected(client)
            elif choice == "7":
                publish_door_open(client)
            elif choice == "8":
                publish_bengala_activated(client)
            elif choice == "9":
                publish_bengala_deactivated(client)
            elif choice == "10":
                publish_telemetry(client, armed=True)
            elif choice == "11":
                publish_telemetry(client, armed=False)
            elif choice == "12":
                publish_status_response(client)
            elif choice == "0":
                print("Saliendo...")
                break
            else:
                print("[ERROR] Opcion no valida")

        except KeyboardInterrupt:
            print("\nInterrupcion recibida, saliendo...")
            break


def main():
    print("="*60)
    print("SIMULADOR ESP32 - MQTT Test Tool (Nueva Arquitectura)")
    print("="*60)
    print(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f"TLS: {'Si' if MQTT_USE_TLS else 'No'}")
    print(f"Device ID: {DEVICE_ID}")
    print(f"Topic eventos: {TOPIC_EVENTOS}")
    print(f"Topic telemetria: {TOPIC_TELEMETRIA}")
    print(f"Topic comandos: {TOPIC_COMANDOS}")
    print("-"*60)

    # Crear cliente MQTT
    client = mqtt.Client(client_id=f"esp32_simulator_{int(time.time())}")
    client.on_connect = on_connect
    client.on_message = on_message

    # Configurar autenticacion
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)

    # Configurar TLS
    if MQTT_USE_TLS:
        client.tls_set(tls_version=ssl.PROTOCOL_TLS)
        print("[OK] TLS configurado")

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()

        # Esperar conexion
        time.sleep(2)

        if len(sys.argv) > 1:
            cmd = sys.argv[1].lower()

            if cmd == "boot":
                publish_system_boot(client)
            elif cmd == "armed":
                publish_system_armed(client)
            elif cmd == "disarmed":
                publish_system_disarmed(client)
            elif cmd == "alarm":
                publish_alarm_triggered(client)
            elif cmd == "stopped":
                publish_alarm_stopped(client)
            elif cmd == "movement":
                publish_movement_detected(client)
            elif cmd == "door":
                publish_door_open(client)
            elif cmd == "telemetry":
                publish_telemetry(client)
            elif cmd == "status":
                publish_status_response(client)
            elif cmd == "menu":
                interactive_menu(client)
            else:
                print(f"[ERROR] Comando desconocido: {cmd}")
                print(__doc__)

            time.sleep(1)
        else:
            # Modo interactivo por defecto
            interactive_menu(client)

    except KeyboardInterrupt:
        print("\nInterrumpido por usuario")
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("[OK] Desconectado de MQTT")


if __name__ == "__main__":
    main()
