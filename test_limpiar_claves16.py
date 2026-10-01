"""Reglas de limpiar_claves16.py y la comparacion de MAC que el traspaso usa."""
from firebase_manager import FirebaseManager
from limpiar_claves16 import planificar


def arbol():
    return {
        "ESP32": {
            "C8_2E_18_26_60": {"ownerUid": "pedro"},      # central real, de otro
            "A0_A3_B3_2F_A2": {"ownerUid": "ana"},        # central real, suya
            "AC_15_18_D5_2D": {"Nombre": "conflicto"},    # central real sin dueño
            "AC_15_18_D4_47_4": {"Nombre": "vieja"},      # solo nodo de 16
            "D4_D4_DA_E3_DC_1": {"Estado": False},        # nodo de 16 que nadie lista
        },
        "Usuarios": {
            "admin": {"Dispositivos": ["C8_2E_18_26_60_9", "AC_15_18_D4_47_4"]},
            "ana": {"Dispositivos": ["A0_A3_B3_2F_A2_8", "A0_A3_B3_2F_A2"]},
            "luis": {"Dispositivos": ["08_D1_F9_29_E4_A"]},
            "eva": {"Dispositivos": ["AC_15_18_D5_2D_F"]},
            "pedro": {"Dispositivos": ["C8_2E_18_26_60"]},
        },
        "Horarios": {"admin": {"devices": {"D4_D4_DA_E3_DC_1": {"enabled": True}}}},
    }


def test_central_de_otro_se_quita():
    cambios, _ = planificar(arbol())
    assert cambios["Usuarios/admin/Dispositivos"] == ["AC_15_18_D4_47_4"]


def test_central_propia_pasa_a_14_sin_duplicar():
    cambios, _ = planificar(arbol())
    assert cambios["Usuarios/ana/Dispositivos"] == ["A0_A3_B3_2F_A2"]


def test_fantasma_se_quita_y_la_lista_vacia_se_borra():
    cambios, _ = planificar(arbol())
    assert cambios["Usuarios/luis/Dispositivos"] is None


def test_central_sin_dueno_no_se_toca():
    cambios, informe = planificar(arbol())
    assert "Usuarios/eva/Dispositivos" not in cambios
    assert any(l.startswith("REVISAR AC_15_18_D5_2D_F") for l in informe)


def test_solo_nodo_16_no_se_toca():
    cambios, informe = planificar(arbol())
    assert "ESP32/AC_15_18_D4_47_4" not in cambios
    assert any(l.startswith("REVISAR AC_15_18_D4_47_4") for l in informe)


def test_nodo_16_sin_listar_se_borra_con_su_horario():
    cambios, _ = planificar(arbol())
    assert cambios["ESP32/D4_D4_DA_E3_DC_1"] is None
    assert cambios["Horarios/admin/devices/D4_D4_DA_E3_DC_1"] is None


def test_quien_ya_esta_bien_no_se_escribe():
    cambios, _ = planificar(arbol())
    assert "Usuarios/pedro/Dispositivos" not in cambios
    assert "ESP32/C8_2E_18_26_60" not in cambios


def test_misma_mac_reconoce_la_clave_de_16():
    misma = FirebaseManager._misma_mac
    assert misma("C8_2E_18_26_60_9", "C8_2E_18_26_60")
    assert misma("C8_2E_18_26_60", "C8_2E_18_26_60")
    assert misma("C8:2E:18:26:60:9A", "C8_2E_18_26_60")  # completa de 17
    assert not misma("C8_2E_18_26_61_9", "C8_2E_18_26_60")
    assert not misma("C8_2E_18_26_60AB", "C8_2E_18_26_60")  # 16 sin "_" en su sitio


if __name__ == "__main__":
    for nombre, f in list(globals().items()):
        if nombre.startswith("test_"):
            f()
    print("limpiar_claves16: OK")
