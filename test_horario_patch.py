#!/usr/bin/env python3
"""
#315: `/horarios on` se deshacia solo.

El bot guarda con `Horarios.update({"uid/devices/mac": {...}})`; el listener
recibe un `patch` en "/" con esas rutas planas. Se tomaba por el arbol entero,
no salia ningun horario valido y el recien habilitado acababa "huerfano":
deshabilitado y mandado asi a la central (log del 25-nov, central CUARTO).

    python test_horario_patch.py
"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import scheduler as sch
from test_retro_banco import MAC, _fm

HORARIO = {"activationTime": "22:00", "deactivationTime": "07:00", "enabled": True,
           "days": ["Lunes", "Martes"], "lastUpdated": 1}


def _preparar():
    fm = _fm({"ESP32": {MAC: {"ownerUid": "jose", "Telegram_ID": "7001112222"}},
              "Horarios": {"jose": {"devices": {MAC: dict(HORARIO)}}}})
    fm.enviar_horario = MagicMock()
    sch.scheduler._save_configs = lambda: None
    sch.scheduler.configs.clear()
    return fm


def _enviados_apagando(fm):
    return [c for c in fm.mqtt_handler.send_set_schedule.call_args_list
            if c.kwargs.get("enabled") is False]


def test_un_patch_en_la_raiz_no_deja_huerfano_el_horario():
    fm = _preparar()
    evento = SimpleNamespace(event_type="patch", path="/", data={f"jose/devices/{MAC}": dict(HORARIO)})
    fm._schedule_listener(evento)
    assert MAC in sch.scheduler.configs, "el horario habilitado quedo como huerfano"
    assert sch.scheduler.cfg(MAC).enabled is True
    assert not _enviados_apagando(fm), _enviados_apagando(fm)


def test_un_put_en_la_raiz_sigue_valiendo_como_arbol_entero():
    fm = _preparar()
    fm._schedule_listener(SimpleNamespace(event_type="put", path="/",
                                          data={"jose": {"devices": {MAC: dict(HORARIO)}}}))
    assert sch.scheduler.cfg(MAC).enabled is True
    # Y un put sin el equipo si lo deja huerfano (borrado de verdad).
    fm._schedule_listener(SimpleNamespace(event_type="put", path="/", data={}))
    assert MAC not in sch.scheduler.configs
    assert _enviados_apagando(fm)


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
