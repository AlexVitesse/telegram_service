#!/usr/bin/env python3
"""
Integracion con el emulador de la RTDB: la forma real de los eventos.

`test_estado_y_armado.py` usa dobles que PRESUPONEN que la RTDB entrega un
`update()` del nodo como patch en /{mac} y un `set()` en /Answer como put en
/{mac}/Answer. De eso depende que la sincronizacion de `Answer` no mande
ordenes y que las de la app si (auditoria del 1-oct, PR #6). Aqui se comprueba
contra el emulador, no contra produccion.

    firebase emulators:exec --only database --project demo-sentinel \\
        "python test_answer_emulador.py"

Sin FIREBASE_DATABASE_EMULATOR_HOST se salta: nunca toca la base real.
"""
import os
import sys
import time
from unittest.mock import MagicMock

if not os.environ.get("FIREBASE_DATABASE_EMULATOR_HOST"):
    print("SALTADA: sin FIREBASE_DATABASE_EMULATOR_HOST (usa firebase emulators:exec)")
    sys.exit(0)

import logging
logging.basicConfig(handlers=[logging.NullHandler()])

import firebase_admin
from firebase_admin import credentials, db

from firebase_manager import FirebaseManager


class _SinCredenciales(credentials.Base):
    """El emulador no comprueba credenciales; el SDK solo pide un objeto."""

    def get_credential(self):
        return MagicMock(token="owner", valid=True, expired=False)


def _esperar(condicion, segundos=5.0):
    fin = time.time() + segundos
    while time.time() < fin:
        if condicion():
            return True
        time.sleep(0.05)
    return condicion()


def main() -> int:
    host = os.environ["FIREBASE_DATABASE_EMULATOR_HOST"]
    firebase_admin.initialize_app(
        _SinCredenciales(), {"databaseURL": f"http://{host}?ns=demo-sentinel"}
    )
    raiz = db.reference("ESP32")
    raiz.set({"C8": {"Estado": True, "Answer": True}})

    fm = FirebaseManager()
    fm.db = db
    fm.initialized = True
    fm.mqtt_handler = MagicMock()
    fm._get_all_devices = lambda: raiz.get() or {}
    listener = raiz.listen(fm._app_command_listener)
    try:
        time.sleep(1)  # el primer evento es la foto completa en "/"
        enviados = fm.mqtt_handler.send_command.call_args_list

        # 1) La central se desarma sola: el servidor sincroniza Answer.
        fm.update_device_state_in_firebase("C8", {"is_armed": False})
        assert _esperar(lambda: raiz.child("C8/Answer").get() is False), "Answer no se sincronizo"
        time.sleep(1)
        assert enviados == [], f"la sincronizacion mando ordenes: {enviados}"

        # 2) Dos sincronizaciones iguales (cache atrasado): sin ordenes.
        fm.update_device_state_in_firebase("C8", {"is_armed": False})
        time.sleep(1)
        assert enviados == [], f"la segunda sincronizacion mando ordenes: {enviados}"

        # 3) La app arma y desarma: las dos ordenes llegan.
        raiz.child("C8/Answer").set(True)
        assert _esperar(lambda: len(enviados) == 1), f"no llego el ARM: {enviados}"
        raiz.child("C8/Answer").set(False)
        assert _esperar(lambda: len(enviados) == 2), f"no llego el DISARM: {enviados}"
        cmds = [c.kwargs["cmd"] for c in enviados]
        assert cmds == ["arm", "disarm"], cmds
    finally:
        listener.close()

    print("ok  la RTDB entrega update() como patch del nodo y set() en /Answer como orden")
    return 0


if __name__ == "__main__":
    sys.exit(main())
