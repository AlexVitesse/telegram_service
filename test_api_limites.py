"""
Pruebas del tope de uso. Sin red, sin reloj real: el tiempo se pasa a mano.

    python test_api_limites.py
"""
import sys

from api_limites import Limitador, normalizar_pregunta, VENTANA_SEG


def test_la_primera_pregunta_pasa():
    lim = Limitador(max_por_hora=20, espera_min_seg=3)
    ok, motivo = lim.permitir("u1", ahora=1000.0)
    assert ok and motivo == ""


def test_dos_seguidas_se_frenan():
    lim = Limitador(max_por_hora=20, espera_min_seg=3)
    lim.permitir("u1", ahora=1000.0)
    ok, motivo = lim.permitir("u1", ahora=1001.0)
    assert not ok
    # El motivo dice CUANTO falta: sin numero solo puede reintentar a ciegas.
    assert "2 s" in motivo


def test_nunca_dice_espera_cero_segundos():
    """Decirle a alguien que espere 0 s no le dice nada."""
    lim = Limitador(max_por_hora=20, espera_min_seg=3)
    lim.permitir("u1", ahora=1000.0)
    # Faltan 0,4 s: con redondeo normal salia "0 s".
    ok, motivo = lim.permitir("u1", ahora=1002.6)
    assert not ok
    assert "0 s" not in motivo
    assert "1 s" in motivo


def test_pasada_la_espera_vuelve_a_pasar():
    lim = Limitador(max_por_hora=20, espera_min_seg=3)
    lim.permitir("u1", ahora=1000.0)
    ok, _ = lim.permitir("u1", ahora=1003.5)
    assert ok


def test_el_tope_por_hora_corta():
    lim = Limitador(max_por_hora=3, espera_min_seg=0)
    for i in range(3):
        ok, _ = lim.permitir("u1", ahora=1000.0 + i)
        assert ok, f"la {i + 1} deberia pasar"
    ok, motivo = lim.permitir("u1", ahora=1003.0)
    assert not ok
    assert "3 preguntas por hora" in motivo
    assert "min" in motivo


def test_la_ventana_se_desliza():
    lim = Limitador(max_por_hora=2, espera_min_seg=0)
    lim.permitir("u1", ahora=1000.0)
    lim.permitir("u1", ahora=1001.0)
    assert not lim.permitir("u1", ahora=1002.0)[0]
    # Justo despues de que la primera salga de la ventana, hay hueco otra vez.
    ok, _ = lim.permitir("u1", ahora=1000.0 + VENTANA_SEG + 1)
    assert ok


def test_cada_usuario_lleva_su_cuenta():
    """Que uno gaste su cuota no puede dejar sin servicio a los demas."""
    lim = Limitador(max_por_hora=1, espera_min_seg=0)
    assert lim.permitir("u1", ahora=1000.0)[0]
    assert not lim.permitir("u1", ahora=1001.0)[0]
    assert lim.permitir("u2", ahora=1001.0)[0]


def test_normalizar_rechaza_lo_que_no_sirve():
    assert normalizar_pregunta("") is None
    assert normalizar_pregunta("   ") is None
    assert normalizar_pregunta(None) is None
    assert normalizar_pregunta(42) is None
    assert normalizar_pregunta({"a": 1}) is None


def test_normalizar_limpia_y_recorta():
    assert normalizar_pregunta("  hola   mundo \n ") == "hola mundo"
    # El texto entra en el prompt: un campo sin limite es una factura sin limite.
    largo = normalizar_pregunta("a" * 900)
    assert len(largo) == 500


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}")
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}")
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
