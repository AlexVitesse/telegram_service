#!/usr/bin/env python3
"""
Test de componentes del servicio Telegram Bridge
================================================
Verifica que todos los modulos se importen y funcionen correctamente.
Nueva arquitectura: ESP32 publica eventos, Python maneja usuarios.

Uso:
    python test_components.py
"""
import sys
import asyncio
import io

# Fix encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


def test_imports():
    """Prueba que todos los modulos se importen correctamente"""
    print("="*60)
    print("PRUEBA DE IMPORTS")
    print("="*60)

    modules = [
        ("config", "Configuracion"),
        ("mqtt_protocol", "Protocolo MQTT"),
        ("mqtt_handler", "Handler MQTT"),
        ("scheduler", "Programador automatico"),
        ("telegram_bot", "Bot de Telegram"),
    ]

    all_ok = True
    for module_name, description in modules:
        try:
            module = __import__(module_name)
            print(f"  [OK] {description}")
        except Exception as e:
            print(f"  [ERROR] {description}: {e}")
            all_ok = False

    return all_ok


def test_config():
    """Prueba la configuracion"""
    print("\n" + "="*60)
    print("PRUEBA DE CONFIGURACION")
    print("="*60)

    try:
        from config import config

        print(f"   MQTT Broker: {config.mqtt.broker}")
        print(f"   MQTT Port: {config.mqtt.port}")
        print(f"   MQTT TLS: {config.mqtt.use_tls}")
        print(f"   Device ID: {config.device_id or '(auto)'}")
        print(f"   Debug: {config.debug}")

        if config.telegram.bot_token and config.telegram.bot_token != "tu_token_aqui":
            print(f"   Bot Token: {config.telegram.bot_token[:20]}...")
        else:
            print("   [WARN] Bot Token NO configurado")

        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        return False


def test_mqtt_protocol():
    """Prueba las estructuras del protocolo MQTT"""
    print("\n" + "="*60)
    print("PRUEBA DE PROTOCOLO MQTT")
    print("="*60)

    try:
        from mqtt_protocol import (
            Topics, Command, EventType,
            MqttCommand, MqttEvent, MqttTelemetry, TelegramFormatter
        )

        # Test Topics
        device_id = "test_device"
        print(f"   Topic eventos: {Topics.EVENTOS}")
        print(f"   Topic telemetria: {Topics.TELEMETRIA}")
        print(f"   Topic comandos: {Topics.comandos(device_id)}")
        print(f"   Topic config: {Topics.configuracion(device_id)}")

        # Test Command enum
        print(f"   Comando ARM: {Command.ARM.value}")
        print(f"   Comando GET_STATUS: {Command.GET_STATUS.value}")

        # Test EventType enum
        print(f"   Evento SYSTEM_ARMED: {EventType.SYSTEM_ARMED.value}")

        # Test crear comando
        cmd = MqttCommand(
            command="arm",
            args={"prealarma_sec": 60}
        )
        print(f"   MqttCommand JSON: {cmd.to_json()[:60]}...")

        # Test parsear evento
        event_json = '{"deviceId":"DEV001","eventType":"system_armed","data":{"source":"remote"},"timestamp":1703000000}'
        event = MqttEvent.from_json(event_json)
        print(f"   MqttEvent parsed: device={event.device_id}, type={event.event_type}")

        # Test TelegramFormatter
        message = TelegramFormatter.format_event(event, "Casa")
        print(f"   Formatted message: {message[:40]}...")

        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False





def test_scheduler():
    """Prueba el programador automatico"""
    print("\n" + "="*60)
    print("PRUEBA DE SCHEDULER")
    print("="*60)

    try:
        from scheduler import Scheduler, ScheduleConfig

        import tempfile
        import os
        temp_dir = tempfile.mkdtemp()

        sched = Scheduler(data_dir=temp_dir)

        # Probar configuracion
        print(f"   Enabled: {sched.is_enabled()}")
        print(f"   On time: {sched.config.format_on_time()}")
        print(f"   Off time: {sched.config.format_off_time()}")

        # Probar setters
        sched.set_on_time(23, 30)
        print(f"   New on time: {sched.config.format_on_time()}")

        # Probar parser
        result = sched.parse_time_string("14:30")
        print(f"   Parse '14:30': {result}")

        # Probar formato
        status = sched.format_status()
        print(f"   Format status: {len(status)} chars")

        # Limpiar
        os.remove(os.path.join(temp_dir, "schedule_config.json"))
        os.rmdir(temp_dir)

        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_mqtt_handler():
    """Prueba el handler MQTT (sin conexion real)"""
    print("\n" + "="*60)
    print("PRUEBA DE MQTT HANDLER")
    print("="*60)

    try:
        from mqtt_handler import MqttHandler
        from mqtt_protocol import MqttEvent, MqttTelemetry

        handler = MqttHandler()

        # Registrar callbacks de prueba
        callback_called = {}

        def on_event(event: MqttEvent):
            callback_called['event'] = True

        def on_telemetry(telemetry: MqttTelemetry):
            callback_called['telemetry'] = True

        handler.on_event(on_event)
        handler.on_telemetry(on_telemetry)

        print(f"   Callbacks registrados: OK")
        print(f"   Device ID: {handler.device_id or '(auto)'}")

        # Probar metodos de comandos
        print(f"   Metodo send_arm existe: {hasattr(handler, 'send_arm')}")
        print(f"   Metodo send_disarm existe: {hasattr(handler, 'send_disarm')}")
        print(f"   Metodo send_get_status existe: {hasattr(handler, 'send_get_status')}")

        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_telegram_bot_init():
    """Prueba la inicializacion del bot de Telegram"""
    print("\n" + "="*60)
    print("PRUEBA DE TELEGRAM BOT (init only)")
    print("="*60)

    try:
        from telegram_bot import TelegramBot
        from config import config

        if not config.telegram.bot_token or config.telegram.bot_token == "tu_token_aqui":
            print("   [WARN] Bot token no configurado, saltando prueba de conexion")
            print("   Para probar: configura TELEGRAM_BOT_TOKEN en .env")
            return True

        bot = TelegramBot()
        print(f"   Bot inicializado: OK")
        print(f"   Running: {bot.is_running()}")
        print(f"   Metodo handle_mqtt_event existe: {hasattr(bot, 'handle_mqtt_event')}")

        return True
    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("\n" + "="*60)
    print("INICIANDO PRUEBAS DE COMPONENTES")
    print("="*60 + "\n")

    results = {
        "Imports": test_imports(),
        "Config": test_config(),
        "MQTT Protocol": test_mqtt_protocol(),
        "Scheduler": test_scheduler(),
        "MQTT Handler": test_mqtt_handler(),
    }

    # Test async
    loop = asyncio.get_event_loop()
    results["Telegram Bot"] = loop.run_until_complete(test_telegram_bot_init())

    # Resumen
    print("\n" + "="*60)
    print("RESUMEN DE PRUEBAS")
    print("="*60)

    all_passed = True
    for name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"   {name}: {status}")
        if not passed:
            all_passed = False

    print("="*60)
    if all_passed:
        print("TODAS LAS PRUEBAS PASARON")
    else:
        print("ALGUNAS PRUEBAS FALLARON")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
