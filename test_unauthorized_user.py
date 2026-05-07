#!/usr/bin/env python3
"""
Test: aislamiento del modo vendedor para usuarios no registrados.

Garantiza que:
  1. Un usuario NO registrado entra al modo vendedor (chat_sales)
     y NUNCA toca el flujo de control de dispositivos (parse_intent).
  2. Un usuario registrado SI llega al flujo normal (parse_intent).
  3. El rate limit funciona: tras N mensajes en la ventana, se bloquea.
  4. Mensajes triviales (saludo) se atajan sin gastar LLM.

Uso:
    python test_unauthorized_user.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.CRITICAL)


def _make_mock_update(chat_id: str, text: str):
    """Construye un Update fake con la estructura minima que usa el handler."""
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.send_action = AsyncMock()
    update.effective_user.first_name = "Mallory"
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_bot(authorized_devices=None, sales_answer="Demo: SentinelGuard es un sistema..."):
    """Construye un TelegramBot parcial con dependencias mockeadas."""
    from telegram_bot import TelegramBot

    firebase_manager = MagicMock()
    firebase_manager.get_authorized_devices = MagicMock(return_value=authorized_devices or [])
    firebase_manager.is_user_admin = MagicMock(return_value=False)
    firebase_manager.get_device_location = MagicMock(return_value="Casa")

    device_manager = MagicMock()
    device_manager.get_device_info = MagicMock(return_value={"is_armed": False, "is_online": True})

    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager = firebase_manager
    bot.device_manager = device_manager

    bot.ai_handler = MagicMock()
    bot.ai_handler.parse_intent = AsyncMock(return_value=None)
    bot.ai_handler.chat_sales = AsyncMock(return_value=sales_answer)
    bot.ai_handler._backend = "ollama"

    bot.knowledge_base = MagicMock()
    bot.knowledge_base.search = MagicMock(return_value=[])

    bot.interaction_logger = MagicMock()
    bot._get_keyboard = MagicMock(return_value=None)

    # Estado del rate limit (atributos que el constructor real setea)
    bot._unauth_rate_limits = {}
    bot.UNAUTH_RATE_LIMIT_MAX = 3
    bot.UNAUTH_RATE_LIMIT_WINDOW = 300
    bot._unauth_welcomed = set()
    # Lead capture state (agregado en feature de captura de leads)
    bot._lead_states = {}
    bot.send_message = AsyncMock()
    return bot


async def test_unauthorized_routes_to_sales_not_control():
    """Usuario no registrado: chat_sales se llama, parse_intent NO."""
    bot = _make_bot(authorized_devices=[])
    update = _make_mock_update(chat_id="999888777", text="como funciona el sistema?")

    await bot._handle_unknown_message(update, MagicMock())

    assert bot.ai_handler.chat_sales.called, "Modo vendedor deberia haber respondido"
    assert not bot.ai_handler.parse_intent.called, \
        "❌ FALLO DE SEGURIDAD: parse_intent (control) se llamo con usuario NO autorizado"
    assert update.message.reply_text.called
    print("  [OK] No autorizado: chat_sales SI, parse_intent NO")


async def test_authorized_routes_to_normal_ai():
    """Usuario registrado: parse_intent se llama (flujo de control normal)."""
    bot = _make_bot(authorized_devices=["DEVICE_001"])
    update = _make_mock_update(chat_id="123456789", text="cuanto cuesta?")

    await bot._handle_unknown_message(update, MagicMock())

    assert bot.ai_handler.parse_intent.called, \
        "Usuario autorizado deberia ir al parse_intent normal"
    assert not bot.ai_handler.chat_sales.called, \
        "Usuario autorizado NO deberia ir al modo vendedor"
    print("  [OK] Autorizado: parse_intent SI, chat_sales NO")


async def test_sales_rate_limit_blocks_after_max():
    """4to mensaje seguido de un no autorizado se bloquea por rate limit."""
    bot = _make_bot(authorized_devices=[])
    chat_id = "555555555"
    update = _make_mock_update(chat_id=chat_id, text="como funciona el sistema?")

    # Primeros 3 mensajes: pasan al LLM
    for i in range(3):
        bot.ai_handler.chat_sales.reset_mock()
        await bot._handle_sales_chat(update, "como funciona el sistema?")
        assert bot.ai_handler.chat_sales.called, f"Mensaje {i+1} deberia haber pasado"

    # 4to mensaje: bloqueado
    bot.ai_handler.chat_sales.reset_mock()
    await bot._handle_sales_chat(update, "como funciona el sistema?")
    assert not bot.ai_handler.chat_sales.called, \
        "❌ Rate limit no esta funcionando: el 4to mensaje paso al LLM"

    # Y la respuesta debe mencionar el rate limit (incluye email/soporte como CTA)
    last_call = update.message.reply_text.call_args
    last_msg = last_call[0][0] if last_call.args else ""
    assert "muchos" in last_msg.lower() or "rapido" in last_msg.lower() or "rápido" in last_msg.lower(), \
        f"La respuesta de rate limit deberia explicar el limite, llego: {last_msg!r}"
    print("  [OK] Rate limit: 4to mensaje bloqueado, LLM no se invoco")


async def test_trivial_message_does_not_call_llm():
    """Saludos sueltos no gastan LLM, contestan con plantilla."""
    bot = _make_bot(authorized_devices=[])
    update = _make_mock_update(chat_id="111222333", text="hola")

    await bot._handle_sales_chat(update, "hola")

    assert not bot.ai_handler.chat_sales.called, \
        "❌ Mensaje trivial NO deberia gastar LLM"
    assert update.message.reply_text.called
    print("  [OK] Mensaje trivial: respuesta plantilla, LLM no se invoco")


async def test_question_with_questionmark_passes_filter():
    """Pregunta corta con '?' debe pasar el filtro y llegar al LLM."""
    bot = _make_bot(authorized_devices=[])
    update = _make_mock_update(chat_id="111222444", text="precio?")

    await bot._handle_sales_chat(update, "precio?")

    assert bot.ai_handler.chat_sales.called, \
        "Pregunta corta con '?' deberia haber pasado al LLM"
    print("  [OK] 'precio?' (corto pero con ?) llega al modo vendedor")


async def main():
    print("="*60)
    print("TEST: modo vendedor + aislamiento de control")
    print("="*60)
    print()

    tests = [
        test_unauthorized_routes_to_sales_not_control,
        test_authorized_routes_to_normal_ai,
        test_sales_rate_limit_blocks_after_max,
        test_trivial_message_does_not_call_llm,
        test_question_with_questionmark_passes_filter,
    ]

    failures = 0
    for fn in tests:
        try:
            await fn()
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            import traceback
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            traceback.print_exc()
            failures += 1

    print()
    print("="*60)
    if failures == 0:
        print(f"RESULTADO: {len(tests)}/{len(tests)} tests pasaron")
    else:
        print(f"RESULTADO: {failures} test(s) fallaron")
    print("="*60)
    return failures


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
