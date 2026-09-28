#!/usr/bin/env python3
"""
Migración de una sola vez tras las pruebas en el banco (24/09/2026)
===================================================================
Pone un dueño a cada central y deja un solo horario por equipo.

    python migrar_retro_banco.py            # solo informa (no escribe nada)
    python migrar_retro_banco.py --aplicar  # escribe, en una sola actualización

Hacer antes `python backup_firebase.py backup`.

Qué hace:
  (a) `ESP32/{mac}/ownerUid`: el usuario que tiene la MAC en su lista. Si la
      tienen varios, el que tenga `telegram_id` igual al `Telegram_ID` del
      equipo. Si no hay forma de decidir, se informa como conflicto y NO se
      asigna: eso lo decide una persona.
  (b) Quita la MAC de las listas de quien no es el dueño. Era la causa de que
      Pedrito viera y controlara la central de José.
  (c) Un horario por equipo, en `Horarios/{dueño}/devices/{mac}`. Candidatas:
      las entradas de ese equipo bajo cualquier clave y los `system` del dueño
      (por su uid o su Telegram). Gana el `lastUpdated` más reciente; si
      empatan, la habilitada. Se borran los `system`, las demás copias y los
      horarios de equipos que ya no existen.
"""
import sys
from typing import Dict, List, Tuple

from mqtt_protocol import normalizar_mac
from scheduler import marca_ms


def _lista(datos) -> List[str]:
    if isinstance(datos, list):
        crudas = datos
    elif isinstance(datos, dict):
        crudas = list(datos.values())
    elif isinstance(datos, str):
        crudas = datos.split(",")
    else:
        return []
    return [str(m).strip() for m in crudas if m and str(m).strip()]


def _misma(guardada: str, mac: str) -> bool:
    g = normalizar_mac(guardada)
    return g == mac or g[:-1] == mac


def planificar(arbol: dict) -> Tuple[Dict[str, object], List[str]]:
    """
    Devuelve (cambios, informe). `cambios` es {ruta: valor | None} para un
    `update()` multi-ruta sobre la raíz; None borra.
    """
    equipos = {m: d for m, d in (arbol.get("ESP32") or {}).items() if isinstance(d, dict)}
    usuarios = {u: d for u, d in (arbol.get("Usuarios") or {}).items() if isinstance(d, dict)}
    horarios = {k: d for k, d in (arbol.get("Horarios") or {}).items() if isinstance(d, dict)}
    cambios: Dict[str, object] = {}
    informe: List[str] = []

    # (a) dueños
    duenos: Dict[str, str] = {}
    for mac, nodo in equipos.items():
        if nodo.get("ownerUid"):
            duenos[mac] = str(nodo["ownerUid"])
            continue
        candidatos = [u for u, d in usuarios.items() if any(_misma(m, mac) for m in _lista(d.get("Dispositivos")))]
        if len(candidatos) > 1:
            tg = str(nodo.get("Telegram_ID") or "")
            por_tg = [u for u in candidatos if tg and str(usuarios[u].get("telegram_id") or "") == tg]
            if len(por_tg) != 1:
                informe.append(f"CONFLICTO {mac}: lo tienen {candidatos}; decidir a mano")
                continue
            candidatos = por_tg
        if not candidatos:
            informe.append(f"SIN DUEÑO {mac}: nadie lo tiene en su lista")
            continue
        duenos[mac] = candidatos[0]
        cambios[f"ESP32/{mac}/ownerUid"] = candidatos[0]
        informe.append(f"DUEÑO {mac} -> {candidatos[0]}")

    # (b) listas: fuera lo que es de otro
    for uid, datos in usuarios.items():
        macs = _lista(datos.get("Dispositivos"))
        quedan = [m for m in macs if not any(_misma(m, mac) and d != uid for mac, d in duenos.items())]
        if len(quedan) != len(macs):
            cambios[f"Usuarios/{uid}/Dispositivos"] = quedan or None
            informe.append(f"LISTA {uid}: quitados {sorted(set(macs) - set(quedan))}")

    # (c) horarios
    def claves_del_dueno(mac: str) -> set:
        uid = duenos[mac]
        return {uid, str(usuarios.get(uid, {}).get("telegram_id") or ""),
                str(equipos[mac].get("Telegram_ID") or "")} - {""}

    for mac, uid in duenos.items():
        suyas = claves_del_dueno(mac)
        candidatas = []
        for clave, datos in horarios.items():
            devices = datos.get("devices") if isinstance(datos.get("devices"), dict) else {}
            for dev, h in devices.items():
                if not isinstance(h, dict) or "activationTime" not in h or "deactivationTime" not in h:
                    continue
                if dev == mac or (dev == "system" and clave in suyas):
                    peso = (marca_ms(h.get("lastUpdated")), 1 if h.get("enabled") else 0, 1 if dev == mac else 0)
                    candidatas.append((peso, clave, dev, h))
        if not candidatas:
            continue
        _, clave, dev, elegido = max(candidatas, key=lambda c: c[0])
        destino = f"Horarios/{uid}/devices/{mac}"
        nuevo = dict(elegido)
        nuevo["lastUpdated"] = marca_ms(elegido.get("lastUpdated"))
        if (clave, dev) != (uid, mac) or nuevo != elegido:
            cambios[destino] = nuevo
        informe.append(f"HORARIO {mac}: {len(candidatas)} candidata(s), gana {clave}/{dev}")

    # Borrar todo lo demás: system, copias bajo otras claves y equipos que no existen.
    conflictos = {m for m in equipos if m not in duenos}
    for clave, datos in horarios.items():
        devices = datos.get("devices") if isinstance(datos.get("devices"), dict) else {}
        for dev in devices:
            ruta = f"Horarios/{clave}/devices/{dev}"
            if dev in conflictos or (dev in duenos and clave == duenos[dev]):
                continue
            if ruta not in cambios:
                cambios[ruta] = None
                informe.append(f"BORRAR {ruta}")

    return cambios, informe


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    from firebase_manager import firebase_manager

    if not firebase_manager.initialize():
        print("No se pudo conectar a Firebase")
        return 1
    db = firebase_manager.db
    arbol = {n: db.reference(n).get() for n in ("ESP32", "Usuarios", "Horarios")}
    cambios, informe = planificar(arbol)
    print("\n".join(informe) or "Nada que migrar")
    print(f"\n{len(cambios)} escritura(s)")
    if not aplicar:
        print("Modo informe: no se escribió nada. Usa --aplicar para escribir.")
        return 0
    if cambios:
        db.reference("/").update(cambios)
        print("Aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
