#!/usr/bin/env python3
"""
Limpieza de una sola vez de las claves de 16 caracteres (01/10/2026)
====================================================================
Una versión antigua de la app guardaba la central como `AA_BB_CC_DD_EE_F`
(16 caracteres) en vez de `AA_BB_CC_DD_EE` (14), que es el ID con el que el
firmware se registra desde siempre. Esas claves apuntan a un nodo que la
central no escucha: quien las tiene ve una tarjeta que no funciona, y el
traspaso o el borrado no las quitaban (`_misma_mac` solo toleraba un
carácter de más).

    python limpiar_claves16.py            # solo informa (no escribe nada)
    python limpiar_claves16.py --aplicar  # escribe, en una sola actualización

Hacer antes `python backup_firebase.py backup`.

Qué hace, para cada clave de 16 en `Usuarios/{uid}/Dispositivos`:
  (a) La central de 14 existe y tiene OTRO dueño → se quita de la lista. Es
      la tarjeta de un equipo que ya no es suyo.
  (b) La central de 14 existe y es suya → se cambia por la de 14 (sin
      duplicar). Así ve la central real.
  (c) No existe ni la de 14 ni la de 16 → se quita: es una tarjeta fantasma.
  (d) NO se toca, se informa como REVISAR: la central de 14 existe pero no
      tiene dueño (conflictos de la migración del 28/09: darla aquí sumaría
      otra cuenta a un conflicto), o solo existe el nodo de 16 (un equipo que
      no reporta en ningún formato). Eso lo decide una persona.
Después, los nodos `ESP32/{16}` que ya no lista nadie y sus horarios
`Horarios/*/devices/{16}` se borran.

También se borran los nodos `ESP32/` cuya clave lleva una coma y que nadie
lista, con sus horarios. Ejemplo: `08_D1_F9_29_E4,E4_65_B8_11_89`, que una
app vieja creó el 15/02 al usar como ruta la lista `Dispositivos` sin
separarla. Sin dueño, sin horario y sin nadie que la liste, pero el servidor
la tomaba por una variante de `08_D1_F9_29_E4` y le escribía el estado.
"""
import re
import sys
from typing import Dict, List, Tuple

CLAVE16 = re.compile(r"^[0-9A-F]{2}(_[0-9A-F]{2}){4}_[0-9A-F]$")


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


def planificar(arbol: dict) -> Tuple[Dict[str, object], List[str]]:
    esp32 = arbol.get("ESP32") or {}
    usuarios = arbol.get("Usuarios") or {}
    horarios = arbol.get("Horarios") or {}
    cambios: Dict[str, object] = {}
    informe: List[str] = []
    listadas_despues = set()

    for uid, datos in usuarios.items():
        if not isinstance(datos, dict):
            continue
        antes = _lista(datos.get("Dispositivos"))
        despues: List[str] = []
        for mac in antes:
            if not CLAVE16.match(mac):
                despues.append(mac)
                continue
            m14 = mac[:14]
            nodo14 = esp32.get(m14)
            if isinstance(nodo14, dict):
                dueno = str(nodo14.get("ownerUid") or "")
                if not dueno:
                    informe.append(f"REVISAR {mac} en {uid}: {m14} no tiene dueño, no se toca")
                    despues.append(mac)
                elif dueno != uid:
                    informe.append(f"QUITAR {mac} de {uid}: {m14} es de {dueno}")
                else:
                    informe.append(f"CAMBIAR {mac} -> {m14} en {uid}")
                    despues.append(m14)
            elif mac in esp32:
                informe.append(f"REVISAR {mac} en {uid}: solo existe el nodo de 16, no se toca")
                despues.append(mac)
            else:
                informe.append(f"QUITAR {mac} de {uid}: no existe ni {m14} ni {mac}")
        despues = list(dict.fromkeys(despues))  # sin duplicados, en orden
        listadas_despues.update(despues)
        if despues != antes:
            cambios[f"Usuarios/{uid}/Dispositivos"] = despues or None

    for mac in sorted(k for k in esp32 if CLAVE16.match(k) or "," in k):
        if mac in listadas_despues:
            continue
        cambios[f"ESP32/{mac}"] = None
        informe.append(f"BORRAR ESP32/{mac}: nadie la lista")
        for clave, datos in horarios.items():
            if isinstance(datos, dict) and isinstance(datos.get("devices"), dict) and mac in datos["devices"]:
                cambios[f"Horarios/{clave}/devices/{mac}"] = None
                informe.append(f"BORRAR Horarios/{clave}/devices/{mac}")

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
    print("\n".join(informe) or "Nada que limpiar")
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
