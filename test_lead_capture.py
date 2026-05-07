#!/usr/bin/env python3
"""
Tests del flujo de captura de leads (modo vendedor).

Cubre:
  - Click "Quiero comprar" inicia el state machine
  - Email valido pasa al siguiente paso
  - Email invalido pide reintentar (state intacto)
  - "saltar" en telefono completa el flujo sin numero
  - Telefono valido completa el flujo con numero
  - Telefono invalido pide reintentar
  - "cancelar" sale del flujo
  - Lead expirado se descarta
  - El admin recibe notificacion al guardar
  - Validators (email, phone) directos

Uso:
    python test_lead_capture.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from unittest.mock import AsyncMock, MagicMock

logging.basicConfig(level=logging.CRITICAL)


def _make_mock_query(chat_id: str, user_name: str = "Juan"):
    """Construye un CallbackQuery fake para los tests de botones."""
    query = MagicMock()
    query.message.chat_id = chat_id
    query.message.reply_text = AsyncMock()
    query.from_user.first_name = user_name
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    return query


def _make_mock_update(chat_id: str, text: str, user_name: str = "Juan"):
    update = MagicMock()
    update.effective_chat.id = chat_id
    update.effective_chat.send_action = AsyncMock()
    update.effective_user.first_name = user_name
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def _make_bot():
    from telegram_bot import TelegramBot

    firebase_manager = MagicMock()
    firebase_manager.get_authorized_devices = MagicMock(return_value=[])
    firebase_manager.save_lead = MagicMock(return_value=True)

    bot = TelegramBot.__new__(TelegramBot)
    bot.firebase_manager = firebase_manager
    bot.device_manager = MagicMock()
    bot.ai_handler = MagicMock()
    bot.ai_handler.chat_sales = AsyncMock(return_value="Demo response")
    bot.ai_handler._backend = "ollama"
    bot.knowledge_base = MagicMock()
    bot.knowledge_base.search = MagicMock(return_value=[])
    bot.interaction_logger = MagicMock()
    bot._get_keyboard = MagicMock(return_value=None)
    bot._unauth_rate_limits = {}
    bot.UNAUTH_RATE_LIMIT_MAX = 3
    bot.UNAUTH_RATE_LIMIT_WINDOW = 300
    bot._unauth_welcomed = set()
    bot._lead_states = {}
    bot.send_message = AsyncMock()  # para notify admin
    return bot


# ----------------------------------------------------------------------
# Validators
# ----------------------------------------------------------------------

def test_validate_email():
    from telegram_bot import TelegramBot
    cases = [
        ("juan@example.com",        "juan@example.com"),
        ("Juan.Perez@DOMINIO.AR",   "juan.perez@dominio.ar"),
        ("a+b@c.io",                "a+b@c.io"),
        ("noemail",                 None),
        ("@example.com",            None),
        ("juan@",                   None),
        ("juan @ example.com",      None),
        ("",                        None),
        ("juan@.com",               None),
        ("juan@example",            None),
    ]
    for raw, expected in cases:
        got = TelegramBot._validate_email(raw)
        assert got == expected, f"_validate_email({raw!r}) = {got!r}, esperado {expected!r}"
    print("  [OK] _validate_email: 10 casos pasaron")


def test_validate_phone():
    from telegram_bot import TelegramBot
    cases = [
        ("+54 11 5555-5555",        "+54 11 5555-5555"),  # arg formal
        ("(011) 5555 5555",         "(011) 5555 5555"),
        ("1155555555",              "1155555555"),
        ("+1 415 555 0123",         "+1 415 555 0123"),
        ("123",                     None),  # muy corto
        ("12345678901234567890",    None),  # demasiado largo
        ("abc-def-ghij",            None),
        ("",                        None),
        ("phone:+5491155551234",    None),  # tiene letras
    ]
    for raw, expected in cases:
        got = TelegramBot._validate_phone(raw)
        assert got == expected, f"_validate_phone({raw!r}) = {got!r}, esperado {expected!r}"
    print("  [OK] _validate_phone: 9 casos pasaron")


# ----------------------------------------------------------------------
# Flow tests
# ----------------------------------------------------------------------

async def test_buy_button_starts_lead_state():
    bot = _make_bot()
    query = _make_mock_query("999")

    await bot._handle_sales_callback(query, "999", "Juan", "sales_buy")

    assert "999" in bot._lead_states, "Deberia haberse creado lead state"
    assert bot._lead_states["999"].waiting_for == "email"
    assert query.message.reply_text.called, "Bot deberia haber pedido el email"
    msg = query.message.reply_text.call_args[0][0]
    assert "email" in msg.lower()
    print("  [OK] sales_buy: state creado, bot pide email")


async def test_full_lead_flow_happy_path():
    bot = _make_bot()
    chat_id = "888"

    # 1. Click "Quiero comprar"
    query = _make_mock_query(chat_id)
    await bot._handle_sales_callback(query, chat_id, "Maria", "sales_buy")
    assert bot._lead_states[chat_id].waiting_for == "email"

    # 2. Mandar email valido
    update = _make_mock_update(chat_id, "maria@example.com")
    await bot._handle_sales_chat(update, "maria@example.com")
    state = bot._lead_states[chat_id]
    assert state.email == "maria@example.com"
    assert state.waiting_for == "phone"

    # 3. Mandar telefono valido
    update = _make_mock_update(chat_id, "+54 9 11 5555-5555")
    await bot._handle_sales_chat(update, "+54 9 11 5555-5555")

    # State limpiado, save_lead llamado
    assert chat_id not in bot._lead_states, "State deberia limpiarse al final"
    assert bot.firebase_manager.save_lead.called, "save_lead deberia ejecutarse"
    args, kwargs = bot.firebase_manager.save_lead.call_args
    assert kwargs["email"] == "maria@example.com"
    assert kwargs["phone"] == "+54 9 11 5555-5555"
    assert kwargs["first_name"] == "Maria"
    print("  [OK] Happy path: email -> phone -> save")


async def test_invalid_email_keeps_state():
    bot = _make_bot()
    chat_id = "777"
    query = _make_mock_query(chat_id)
    await bot._handle_sales_callback(query, chat_id, "Pedro", "sales_buy")

    update = _make_mock_update(chat_id, "no es un email")
    await bot._handle_sales_chat(update, "no es un email")

    # state intacto, sigue esperando email
    assert bot._lead_states[chat_id].waiting_for == "email"
    assert not bot.firebase_manager.save_lead.called
    print("  [OK] Email invalido: state intacto, save NO llamado")


async def test_skip_phone_completes_with_empty_phone():
    bot = _make_bot()
    chat_id = "666"
    query = _make_mock_query(chat_id)
    await bot._handle_sales_callback(query, chat_id, "Ana", "sales_buy")

    # email
    update = _make_mock_update(chat_id, "ana@dominio.com")
    await bot._handle_sales_chat(update, "ana@dominio.com")

    # saltar
    update = _make_mock_update(chat_id, "saltar")
    await bot._handle_sales_chat(update, "saltar")

    assert chat_id not in bot._lead_states
    assert bot.firebase_manager.save_lead.called
    kwargs = bot.firebase_manager.save_lead.call_args.kwargs
    assert kwargs["phone"] == "", f"Phone deberia ser vacio, llego {kwargs['phone']!r}"
    print("  [OK] 'saltar' completa el flujo con phone vacio")


async def test_invalid_phone_keeps_state():
    bot = _make_bot()
    chat_id = "555"
    query = _make_mock_query(chat_id)
    await bot._handle_sales_callback(query, chat_id, "Lucia", "sales_buy")

    update = _make_mock_update(chat_id, "lucia@x.com")
    await bot._handle_sales_chat(update, "lucia@x.com")

    update = _make_mock_update(chat_id, "abc")
    await bot._handle_sales_chat(update, "abc")

    assert bot._lead_states[chat_id].waiting_for == "phone", "Sigue esperando phone"
    assert not bot.firebase_manager.save_lead.called
    print("  [OK] Phone invalido: state intacto, save NO llamado")


async def test_cancel_exits_flow():
    bot = _make_bot()
    chat_id = "444"
    query = _make_mock_query(chat_id)
    await bot._handle_sales_callback(query, chat_id, "X", "sales_buy")

    update = _make_mock_update(chat_id, "cancelar")
    await bot._handle_sales_chat(update, "cancelar")

    assert chat_id not in bot._lead_states, "State deberia limpiarse al cancelar"
    assert not bot.firebase_manager.save_lead.called
    print("  [OK] 'cancelar' limpia el state y NO guarda")


async def test_expired_lead_is_cleaned():
    from telegram_bot import LeadCaptureState
    bot = _make_bot()
    chat_id = "333"
    # Lead state con timestamp viejo (> 10 min atras)
    bot._lead_states[chat_id] = LeadCaptureState(
        chat_id=chat_id, first_name="Z", started_at=time.time() - 700,
        waiting_for="email",
    )
    bot._cleanup_expired_lead_states()
    assert chat_id not in bot._lead_states, "Lead expirado deberia eliminarse"
    print("  [OK] Lead expirado: limpiado por _cleanup_expired_lead_states")


async def test_admin_notified_on_lead_save():
    bot = _make_bot()
    # Configurar admin chat id
    from config import config
    original = config.telegram.admin_chat_id
    config.telegram.admin_chat_id = "ADMIN_TEST"

    try:
        chat_id = "222"
        query = _make_mock_query(chat_id)
        await bot._handle_sales_callback(query, chat_id, "Test", "sales_buy")

        update = _make_mock_update(chat_id, "test@example.com")
        await bot._handle_sales_chat(update, "test@example.com")

        update = _make_mock_update(chat_id, "saltar")
        await bot._handle_sales_chat(update, "saltar")

        # send_message debe haberse llamado al admin
        assert bot.send_message.called
        admin_msg_args = bot.send_message.call_args
        assert admin_msg_args[0][0] == "ADMIN_TEST", "Deberia notificar al admin"
        print("  [OK] Admin notificado al guardar lead")
    finally:
        config.telegram.admin_chat_id = original


async def test_buttons_disabled_features_safely():
    """Sales callbacks NO requieren auth, no deben tirar errores con usuario nuevo."""
    bot = _make_bot()
    query = _make_mock_query("111")

    for data in ("sales_more_info", "sales_support"):
        query.message.reply_text.reset_mock()
        await bot._handle_sales_callback(query, "111", "X", data)
        assert query.message.reply_text.called, f"{data} deberia responder"
    print("  [OK] sales_more_info y sales_support responden sin auth")


async def main():
    print("="*60)
    print("TEST: captura de leads + botones de modo vendedor")
    print("="*60)
    print()

    sync_tests = [test_validate_email, test_validate_phone]
    async_tests = [
        test_buy_button_starts_lead_state,
        test_full_lead_flow_happy_path,
        test_invalid_email_keeps_state,
        test_skip_phone_completes_with_empty_phone,
        test_invalid_phone_keeps_state,
        test_cancel_exits_flow,
        test_expired_lead_is_cleaned,
        test_admin_notified_on_lead_save,
        test_buttons_disabled_features_safely,
    ]

    failures = 0
    for fn in sync_tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            failures += 1

    for fn in async_tests:
        try:
            await fn()
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            failures += 1
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"  [ERROR] {fn.__name__}: {type(e).__name__}: {e}")
            failures += 1

    total = len(sync_tests) + len(async_tests)
    print()
    print("="*60)
    if failures == 0:
        print(f"RESULTADO: {total}/{total} tests pasaron")
    else:
        print(f"RESULTADO: {failures} test(s) de {total} fallaron")
    print("="*60)
    return failures


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
