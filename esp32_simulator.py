"""
Simulador de Dispositivo ESP32 para Pruebas
=============================================
Este script simula el comportamiento de un dispositivo ESP32 para probar
el servicio Python (telegram_service) de forma aislada.

Funcionalidades:
- Se conecta al mismo broker MQTT que el servicio principal.
- Se suscribe al topic de comandos para un deviceId específico.
- Imprime en consola cualquier comando recibido.
- Permite enviar eventos simulados al servicio escribiendo en la terminal.
"""
import json
import logging
import time
import paho.mqtt.client as mqtt
from config import config
from mqtt_protocol import Command, EventType

# --- CONFIGURACIÓN DEL SIMULADOR ---
# Usa un deviceId que exista en tu base de datos de Firebase
DEVICE_ID = "E4_65_B8_11_89_E7" 
LOCATION = "Oficina de Pruebas"
# -----------------------------------

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- DEFINICIÓN DE TOPICS ---
TOPIC_EVENTOS = "dispositivos/eventos"
TOPIC_TELEMETRIA = "dispositivos/estado_telemetria"
TOPIC_COMANDOS = f"dispositivos/comandos/{DEVICE_ID}"

def get_timestamp():
    return int(time.time())

# --- CALLBACKS DE MQTT ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logging.info(f"Simulador ESP32 ({DEVICE_ID}) conectado al Broker MQTT.")
        # Suscribirse al topic de comandos
        client.subscribe(TOPIC_COMANDOS)
        logging.info(f"Suscrito a comandos en: {TOPIC_COMANDOS}")
        
        # Publicar estado inicial para que el backend nos conozca
        logging.info("Publicando telemetría inicial...")
        publish_telemetry(client, armed_status=False, wifi_rssi=-50)
    else:
        logging.error(f"Error de conexión, código: {rc}")

def on_message(client, userdata, msg):
    logging.info("="*50)
    logging.info(f"Comando recibido en topic: {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        command = payload.get("command", "").lower()
        
        logging.info("Payload del comando:")
        logging.info(json.dumps(payload, indent=2))

        # Responder a comandos especificos para que el backend no de timeout
        if command == Command.GET_STATUS:
            logging.info("Comando de estado detectado. Respondiendo con telemetria...")
            publish_telemetry(client, armed_status=True, wifi_rssi=-55)
        elif command == Command.ARM:
            logging.info("Comando de ARMADO detectado. Respondiendo con evento 'system_armed'...")
            publish_event(client, EventType.SYSTEM_ARMED, data={"source": "simulator"})
        elif command == Command.DISARM:
            logging.info("Comando de DESARMADO detectado. Respondiendo con evento 'system_disarmed'...")
            publish_event(client, EventType.SYSTEM_DISARMED, data={"source": "simulator"})

    except json.JSONDecodeError:
        logging.error(f"Error decodificando JSON: {msg.payload.decode('utf-8')}")
    except Exception as e:
        logging.error(f"Error procesando mensaje: {e}")
    logging.info("="*50)

# --- PUBLICACIÓN DE EVENTOS Y TELEMETRIA ---
def publish_event(client, event_type, data=None):
    event = {
        "deviceId": DEVICE_ID,
        "timestamp": get_timestamp(),
        "eventType": event_type,
        "data": data or {}
    }
    payload = json.dumps(event)
    logging.info(f"Payload de evento publicado: {payload}") # Added logging
    client.publish(TOPIC_EVENTOS, payload, qos=1)
    logging.info(f"-> Evento publicado en '{TOPIC_EVENTOS}': {event_type}")

def publish_telemetry(client, armed_status, wifi_rssi):
    telemetry = {
        "deviceId": DEVICE_ID,
        "timestamp": get_timestamp(),
        "armed": armed_status,
        "alarm_active": False,
        "bengala_enabled": False,
        "wifi_rssi": wifi_rssi,
        "heap_free": 150000,
        "uptime_sec": 60,
        "lora_sensors_active": 0,
        "auto_schedule_enabled": False
    }
    payload = json.dumps(telemetry)
    client.publish(TOPIC_TELEMETRIA, payload, qos=0)
    logging.info(f"-> Telemetria publicada en '{TOPIC_TELEMETRIA}'")

# --- FUNCIÓN PRINCIPAL DEL SIMULADOR ---
def main():
    # Configurar cliente MQTT
    client = mqtt.Client(client_id=f"esp32-sim-{DEVICE_ID}")
    client.on_connect = on_connect
    client.on_message = on_message

    if config.mqtt.username:
        client.username_pw_set(config.mqtt.username, config.mqtt.password)
    
    if config.mqtt.use_tls:
        client.tls_set()

    try:
        logging.info(f"Conectando simulador a {config.mqtt.broker}:{config.mqtt.port}...")
        client.connect(config.mqtt.broker, config.mqtt.port, config.mqtt.keepalive)
    except Exception as e:
        logging.error(f"No se pudo conectar al broker MQTT: {e}")
        logging.error("Verifica la dirección del broker, el puerto y tu conexión a internet.")
        return

    client.loop_start()
    logging.info("Loop de MQTT iniciado en segundo plano.")

    print("\n--- Simulador ESP32 Interactivo ---")
    print("Escribe un tipo de evento y presiona Enter para enviarlo.")
    print("Ejemplos: 'boot', 'movimiento', 'puerta', 'armado', 'desarmado', 'alarma'")
    print("Escribe 'exit' para salir.")
    print("-" * 20)

    # Bucle principal interactivo
    while True:
        try:
            event_type = input("-> ").strip().lower()
            if not event_type:
                continue

            if event_type == 'exit':
                break

            data = {}
            if event_type == "movimiento":
                data = {"sensorId": "pir_001", "sensorName": "PIR Sala", "location": "Sala"}
            elif event_type == "puerta":
                 data = {"sensorId": "door_001", "sensorName": "Puerta Principal", "location": "Entrada"}
            elif event_type == "boot":
                event_type = "system_boot"
                data = {"version": "sim_1.0", "location": LOCATION}
            elif event_type == "armado":
                event_type = "system_armed"
                data = {"source": "simulator"}
            elif event_type == "desarmado":
                event_type = "system_disarmed"
                data = {"source": "simulator"}
            elif event_type == "alarma":
                event_type = "alarm_triggered"
                data = {"sensorId": "sim_001", "sensorName": "Simulador"}
            
            publish_event(client, event_type, data)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logging.error(f"Error en el loop principal: {e}")

    client.loop_stop()
    logging.info("Simulador detenido.")


if __name__ == "__main__":
    main()