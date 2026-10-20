"""
Varios horarios por central (20-oct): la app guarda `lista` en
Horarios/{uid}/devices/{mac}; el VPS la pasa al formato del firmware y, con mas
de uno o con vacaciones, deja de armar y desarmar por su cuenta: decide la
central, que sabe si otro horario sigue en su franja.

    python test_horarios_lista.py
"""
import sys
from datetime import datetime
from unittest import mock

from firebase_manager import FirebaseManager
from scheduler import Scheduler, ScheduleConfig

LV = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes']


def test_lista_al_formato_del_firmware():
    fw = FirebaseManager._lista_para_firmware({'lista': [
        {'nombre': 'Noche', 'activationTime': '22:00', 'deactivationTime': '07:30', 'days': LV},
        {'nombre': 'Playa', 'activationTime': '08:00', 'deactivationTime': '20:00',
         'desde': '2026-11-01', 'hasta': '2026-11-08', 'enabled': False},
    ]})
    assert fw == [
        {'en': True, 'on': 1320, 'off': 450, 'dias': 0b0111110},
        {'en': False, 'on': 480, 'off': 1200, 'desde': 20261101, 'hasta': 20261108},
    ], fw


def test_sin_lista_es_el_horario_de_siempre():
    assert FirebaseManager._lista_para_firmware({'activationTime': '22:00'}) is None
    assert FirebaseManager._lista_para_firmware({'lista': []}) is None


def test_como_mucho_cuatro():
    h = {'activationTime': '22:00', 'deactivationTime': '07:00', 'days': LV}
    assert len(FirebaseManager._lista_para_firmware({'lista': [h] * 6})) == 4


def test_con_varios_o_vacaciones_el_vps_no_arma():
    s = Scheduler.__new__(Scheduler)
    ahora = datetime(2026, 10, 20, 22, 0)  # martes
    uno = ScheduleConfig(enabled=True, on_hour=22, on_minute=0, days=LV,
                         lista=[{'en': True, 'on': 1320, 'off': 420, 'dias': 0b0111110}])
    varios = ScheduleConfig(enabled=True, on_hour=22, on_minute=0, days=LV,
                            lista=uno.lista * 2)
    vacaciones = ScheduleConfig(enabled=True, on_hour=22, on_minute=0, days=LV,
                                lista=[{'en': True, 'on': 1320, 'off': 420, 'desde': 20261101, 'hasta': 20261108}])
    with mock.patch('scheduler.datetime') as dt:
        dt.now.return_value = ahora
        assert s._is_due(uno, 'on', reminder=False), "con uno, el VPS sigue como siempre"
        assert not s._is_due(varios, 'on', reminder=False)
        assert not s._is_due(vacaciones, 'on', reminder=False)


def test_la_lista_sobrevive_al_reinicio_del_vps():
    cfg = ScheduleConfig(enabled=True, lista=[{'en': True, 'on': 1, 'off': 2, 'dias': 1}])
    assert ScheduleConfig.from_dict(cfg.to_dict()).lista == cfg.lista


if __name__ == "__main__":
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}", flush=True)
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}", flush=True)
        except Exception as e:
            fallos += 1
            print(f"ERROR  {t.__name__}: {type(e).__name__}: {e}", flush=True)
    print(f"{chr(10)}{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
