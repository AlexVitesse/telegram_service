"""
Check del scheduler por dispositivo.
El bug que cubre: un horario global compartido mandaba recordatorios y armaba
dispositivos de otros usuarios (log del 2026-08-28 06:55, 7 chats notificados
por un horario ajeno). Ejecutar: python test_scheduler.py
"""
import asyncio
import datetime as _dt
import json
import tempfile
from pathlib import Path

import scheduler as sched_mod
from scheduler import Scheduler


def _freeze(dt: _dt.datetime):
    """Congela datetime.now() dentro del modulo scheduler"""
    class _FakeDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return dt
    sched_mod.datetime = _FakeDatetime


def _make(tmp: Path) -> Scheduler:
    return Scheduler(data_dir=str(tmp))


def test_horarios_aislados_por_dispositivo(tmp: Path):
    s = _make(tmp)
    # A arma a las 22:00; B a las 07:00
    s.set_on_time("DEV_A", 22, 0)
    s.set_enabled("DEV_A", True)
    s.set_on_time("DEV_B", 7, 0)
    s.set_enabled("DEV_B", True)

    recordatorios, armados = [], []
    s.on_reminder(lambda dev, kind, mins: _collect(recordatorios, (dev, kind, mins)))
    s.on_arm(lambda dev: _collect(armados, dev))

    # 06:55 de un viernes: solo le toca a DEV_B
    _freeze(_dt.datetime(2026, 8, 28, 6, 55))
    asyncio.run(s._check_schedule())
    assert recordatorios == [("DEV_B", "on", 5)], recordatorios

    # 07:00: solo se arma DEV_B
    _freeze(_dt.datetime(2026, 8, 28, 7, 0))
    asyncio.run(s._check_schedule())
    assert armados == ["DEV_B"], armados


def test_no_repite_el_mismo_dia(tmp: Path):
    s = _make(tmp)
    s.set_on_time("DEV_A", 22, 0)
    s.set_enabled("DEV_A", True)
    armados = []
    s.on_arm(lambda dev: _collect(armados, dev))

    _freeze(_dt.datetime(2026, 8, 28, 22, 0))
    asyncio.run(s._check_schedule())
    asyncio.run(s._check_schedule())
    assert armados == ["DEV_A"], armados


def test_dia_inactivo_no_dispara(tmp: Path):
    s = _make(tmp)
    s.set_on_time("DEV_A", 22, 0)
    s.set_days("DEV_A", ["Lunes"])
    s.set_enabled("DEV_A", True)
    armados = []
    s.on_arm(lambda dev: _collect(armados, dev))

    _freeze(_dt.datetime(2026, 8, 28, 22, 0))  # viernes
    asyncio.run(s._check_schedule())
    assert armados == [], armados


def test_recordatorio_cruza_medianoche(tmp: Path):
    s = _make(tmp)
    s.set_on_time("DEV_A", 0, 2)
    s.set_enabled("DEV_A", True)
    recordatorios = []
    s.on_reminder(lambda dev, kind, mins: _collect(recordatorios, (dev, kind, mins)))

    _freeze(_dt.datetime(2026, 8, 27, 23, 57))
    asyncio.run(s._check_schedule())
    assert recordatorios == [("DEV_A", "on", 5)], recordatorios


def test_descarta_formato_global_antiguo(tmp: Path):
    (tmp / "schedule_config.json").write_text(
        json.dumps({"enabled": True, "on_hour": 22, "off_hour": 7}), encoding="utf-8"
    )
    assert _make(tmp).configs == {}


def test_persiste_por_dispositivo(tmp: Path):
    s = _make(tmp)
    s.set_on_time("DEV_A", 21, 30)
    s.set_enabled("DEV_A", True)

    recargado = _make(tmp)
    assert recargado.cfg("DEV_A").format_on_time() == "21:30"
    assert recargado.cfg("DEV_B").enabled is False


async def _collect_async(bucket, value):
    bucket.append(value)


def _collect(bucket, value):
    return _collect_async(bucket, value)


if __name__ == "__main__":
    real_datetime = sched_mod.datetime
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        with tempfile.TemporaryDirectory() as d:
            fn(Path(d))
        sched_mod.datetime = real_datetime
        print(f"ok  {fn.__name__}")
    print(f"{len(tests)} checks OK")
