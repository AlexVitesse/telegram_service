from types import SimpleNamespace

from escalation_handler import build_escalation_message

S = SimpleNamespace(email="a&b@x.com", phone="+52 1 55 6815 5033", hours="9 < 18")


def test_telegram_ve_abrir_chat_y_no_la_url():
    m = build_escalation_message("manual", S, "cuarto C8_2E", html=True)
    assert '<a href="https://wa.me/5215568155033?text=' in m and ">Abrir chat</a>" in m
    assert "a&amp;b@x.com" in m and "9 &lt; 18" in m


def test_app_sigue_en_texto_plano():
    m = build_escalation_message("manual", S, "cuarto C8_2E")
    assert "<a " not in m and "💬 WhatsApp: https://wa.me/5215568155033?text=" in m
