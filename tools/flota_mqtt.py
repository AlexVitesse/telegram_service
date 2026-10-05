import json, re, ssl, sys, time, uuid
import paho.mqtt.client as mqtt
from pathlib import Path

# Credenciales leidas de config.h del firmware (2do argumento, o el clon de ARCHIVO). Solo suscripcion, no se publica nada.
cfg = open(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[2] / "ARCHIVO/Sentinel-guard-2v/config.h",
           encoding="utf-8", errors="replace").read()
g = lambda k: re.search(r'#define\s+%s\s+"([^"]+)"' % k, cfg).group(1)
BROKER, USER, PASS = g("MQTT_BROKER"), g("MQTT_USER"), g("MQTT_PASS")

seen, events = {}, []
# clientId unico: un id repetido desconectaria a otro cliente del broker
cid = "claude-observer-" + uuid.uuid4().hex[:8]

def on_connect(c, u, f, rc, props=None):
    print(f"conectado rc={rc} como {cid}", flush=True)
    c.subscribe([("dispositivos/estado_telemetria", 0), ("dispositivos/eventos", 0)])

def on_message(c, u, msg):
    try:
        d = json.loads(msg.payload.decode("utf-8", "replace"))
    except Exception:
        return
    if msg.topic.endswith("eventos"):
        events.append((time.strftime("%H:%M:%S"), d.get("deviceId", "?"), d.get("eventType", "?")))
    else:
        d["_visto"] = time.strftime("%H:%M:%S")
        seen[d.get("deviceId", "?")] = d

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
c.username_pw_set(USER, PASS)
c.tls_set(cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
c.on_connect, c.on_message = on_connect, on_message
c.connect(BROKER, 8883, 60)
c.loop_start()
time.sleep(int(sys.argv[1]) if len(sys.argv) > 1 else 40)          # 2.5 ciclos de telemetria
c.loop_stop(); c.disconnect()

print(f"\n===== {len(seen)} central(es) reportando en 75 s =====")
for did, d in seen.items():
    nuevo = "lora_task_age_sec" in d
    print(f"\n--- {did}  (visto {d['_visto']}) ---")
    print(f"  firmware        : {'NUEVO' if nuevo else 'VIEJO (sin lora_task_age_sec)'}")
    print(f"  lora_ok         : {d.get('lora_ok', 'campo ausente')}")
    print(f"  lora_task_age   : {d.get('lora_task_age_sec', 'campo ausente')} s")
    print(f"  sensores LoRa   : {d.get('lora_sensors_active')}")
    print(f"  armado / alarma : {d.get('armed')} / {d.get('alarm_active')}")
    print(f"  uptime          : {d.get('uptime_sec')} s")
    print(f"  heap libre      : {d.get('heap_free')} B")
    print(f"  wifi rssi       : {d.get('wifi_rssi')} dBm")

print(f"\n===== eventos ({len(events)}) =====")
for t, did, ev in events[-15:]:
    print(f"  {t}  {did}  {ev}")
if not events:
    print("  (ninguno en la ventana)")
