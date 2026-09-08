#!/usr/bin/env python3
"""
Que `Estado` se repare solo, y que el armado no diga "protegida" antes de serlo.

Los dos fallos que vigila se vieron en produccion el 2026-09-08, en la misma
central y con una hora de diferencia:

  1. `ESP32/08_D1_F9_29_E4/Estado` llevaba desde el 1-sep diciendo `False` con
     la central armada. La app se lo creia. Dos causas encadenadas: la guarda
     de `Telegram_ID` rechazaba la escritura, y `set_armed_state` solo escribia
     cuando el valor cambiaba respecto a su MEMORIA -que decia lo correcto-, asi
     que no habia cambio que detectar y nadie lo reparaba nunca.

  2. Una sola orden de armado manda DOS avisos identicos, separados por el
     tiempo de salida. El primero decia "Sistema Armado" cuando el usuario
     todavia estaba saliendo y la casa NO estaba protegida.

    python test_estado_y_armado.py
"""
import sys
from unittest.mock import MagicMock

import device_manager as dm_mod
import fcm_handler as fcm_mod


class _Ref:
    """Un nodo de la RTDB de mentira que recuerda lo que le escriben."""

    def __init__(self, base, path):
        self.base, self.path = base, path

    def child(self, hijo):
        return _Ref(self.base, f"{self.path}/{hijo}")

    def set(self, valor):
        self.base.escrituras.append((self.path, valor))


class _FakeFirebase:
    """Lo minimo de FirebaseManager para probar la reconciliacion."""

    def __init__(self, nodos):
        self.nodos = nodos
        self.escrituras = []
        self.db = MagicMock()
        self.db.reference = lambda p: _Ref(self, p)

    def is_available(self):
        return True

    def _get_all_devices(self):
        return self.nodos


def _fm(nodos):
    """Un FirebaseManager real, pero con la RTDB y el cache falsos."""
    from firebase_manager import FirebaseManager
    fm = FirebaseManager.__new__(FirebaseManager)
    falso = _FakeFirebase(nodos)
    fm.db = falso.db
    fm.is_available = falso.is_available
    fm._get_all_devices = falso._get_all_devices
    fm._falso = falso
    return fm


# --------------------------------------------------------------------------
# (a) el estado no depende de tener Telegram configurado
# --------------------------------------------------------------------------

def test_un_equipo_sin_telegram_tambien_sincroniza_su_estado():
    """
    El caso literal de produccion: `Telegram_ID` no faltaba, era cadena vacia,
    y vacia es falsa. Con eso la escritura se rechazaba y la app se quedaba con
    un estado viejo. Que el equipo tenga Telegram no dice nada sobre si esta
    armado.
    """
    fm = _fm({"08_D1_F9_29_E4": {"Estado": False, "Telegram_ID": ""}})
    fm.update_device_state_in_firebase("08_D1_F9_29_E4", {"is_armed": True})
    assert fm._falso.escrituras == [("ESP32/08_D1_F9_29_E4/Estado", True)], \
        fm._falso.escrituras


# --------------------------------------------------------------------------
# (b) una divergencia se repara sola
# --------------------------------------------------------------------------

def test_la_divergencia_se_repara_aunque_la_memoria_ya_estuviera_bien():
    """
    El fallo de la semana: memoria=True, RTDB=False, telemetria=True. Como la
    memoria ya decia True no habia "cambio", no se escribia, y la mentira se
    quedaba. Ahora quien decide es la base.
    """
    fm = _fm({"D1": {"Estado": False, "Telegram_ID": "123"}})
    gestor = dm_mod.DeviceManager(fm)
    gestor.devices_state["D1"] = {"is_armed": True}   # la memoria ya estaba bien

    gestor.set_armed_state("D1", True)

    assert fm._falso.escrituras == [("ESP32/D1/Estado", True)], \
        f"no reparo la divergencia: {fm._falso.escrituras}"


def test_si_ya_coincide_no_se_escribe():
    """La reconciliacion no puede convertirse en una escritura por telemetria."""
    fm = _fm({"D1": {"Estado": True, "Telegram_ID": "123"}})
    gestor = dm_mod.DeviceManager(fm)
    gestor.devices_state["D1"] = {"is_armed": True}

    gestor.set_armed_state("D1", True)

    assert fm._falso.escrituras == [], fm._falso.escrituras


def test_las_variantes_truncadas_se_sincronizan_todas():
    """La app puede estar leyendo cualquiera de las dos."""
    fm = _fm({
        "08_D1_F9_29": {"Estado": False},
        "08_D1_F9_29_E4": {"Estado": False},
    })
    fm.update_device_state_in_firebase("08_D1_F9_29_E4", {"is_armed": True})
    escritos = {p for p, _ in fm._falso.escrituras}
    assert escritos == {"ESP32/08_D1_F9_29/Estado", "ESP32/08_D1_F9_29_E4/Estado"}, escritos


# --------------------------------------------------------------------------
# Los dos momentos del armado
# --------------------------------------------------------------------------

def test_el_primer_aviso_no_dice_que_ya_esta_protegida():
    """
    Durante el tiempo de salida la casa NO esta protegida. El aviso viejo decia
    "Sistema Armado" en ese momento, que es afirmar lo que todavia no es cierto.
    """
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    aviso = h.create_arming_notification("merida", 60, "D1")
    texto = f"{aviso.title} {aviso.body}".lower()
    assert "60" in texto, aviso.body
    assert "salir" in texto, aviso.body
    assert "protegida" not in aviso.title.lower(), aviso.title


def test_el_segundo_aviso_si_lo_dice():
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    aviso = h.create_protected_notification("merida", "D1")
    assert "protegida" in f"{aviso.title} {aviso.body}".lower()


def test_el_tiempo_de_salida_no_va_clavado_a_60():
    """Si alguien lo pone en 30, el aviso tiene que decir 30."""
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    assert "30" in h.create_arming_notification("merida", 30, "D1").body
    # Y sin dato -telemetria aun no recibida- no se inventa un numero.
    sin_dato = h.create_arming_notification("merida", None, "D1").body
    assert "60" not in sin_dato and "None" not in sin_dato, sin_dato


def test_un_reinicio_no_dice_que_alguien_armo():
    """
    `source: "boot"` no es "alguien acaba de armar": es "la central arranco y
    sigue como estaba". Con el mapa viejo salia crudo -"armado desde boot"- y
    traducirlo a "armado desde Reinicio" se lee como que el reinicio armo la
    casa, que es al reves.
    """
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    protegida = h.create_reinicio_notification("merida", True, "D1")
    desarmada = h.create_reinicio_notification("merida", False, "D1")

    assert "reinició" in protegida.body, protegida.body
    assert "sigue protegida" in protegida.body, protegida.body
    assert "sigue desarmada" in desarmada.body, desarmada.body
    # "armado desde X" es la frase del armado de verdad: aqui no debe aparecer.
    for aviso in (protegida, desarmada):
        assert "armado desde" not in aviso.body.lower(), aviso.body
        assert "boot" not in f"{aviso.title} {aviso.body}".lower(), aviso.body


def test_los_dos_avisos_siguen_siendo_de_la_familia_armado():
    """
    Quien apaga los avisos de armado espera apagar los DOS momentos. Si uno de
    los dos cambiara de tipo, se colaria por el filtro.
    """
    h = fcm_mod.FCMHandler.__new__(fcm_mod.FCMHandler)
    tipo = fcm_mod.NotificationType.SYSTEM_ARMED
    assert h.create_arming_notification("m", 60, "D1").notification_type == tipo
    assert h.create_protected_notification("m", "D1").notification_type == tipo
    assert h.create_reinicio_notification("m", True, "D1").notification_type == tipo
    assert fcm_mod.FCMHandler.OPCIONALES[tipo] == "armado"


def _correr():
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for fn in pruebas:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            print(f"  FALLO  {fn.__name__}: {e}")
            fallos += 1
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    return fallos


if __name__ == "__main__":
    sys.exit(1 if _correr() else 0)
