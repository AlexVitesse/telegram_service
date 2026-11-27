#!/usr/bin/env python3
"""
Reglas de la RTDB (APP/database.rules.json) contra el emulador: #124 F0.

Matriz de §7 del plan (docs/PLAN_FAMILIA_PARTICIPANTES_2026-11-18.md), con
las correcciones de Codex: el miembro manda por `Orden` (C1), no por `Answer`
ni `DisparoApp`; `miembros/{uid}` solo lleva `rol` (C3); `Miembros/{mac}` lo
lee solo el dueño; los horarios del dueño, en solo lectura para el miembro (C6).

La prueba sube las reglas ella misma, así que vale cualquier emulador:

    firebase emulators:exec --only database --project demo-sentinel \\
        "python <ruta>/VPS/test_reglas_emulador.py"

o, con uno que ya esté corriendo (en Windows suele quedar vivo en el 9000):

    FIREBASE_DATABASE_EMULATOR_HOST=127.0.0.1:9000 python test_reglas_emulador.py

Por REST con tokens sin firmar (el emulador no comprueba la firma).
Sin FIREBASE_DATABASE_EMULATOR_HOST se salta: nunca toca la base real.
"""
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

HOST = os.environ.get("FIREBASE_DATABASE_EMULATOR_HOST")
if not HOST:
    print("SALTADA: sin FIREBASE_DATABASE_EMULATOR_HOST (usa firebase emulators:exec)")
    sys.exit(0)

NS = "demo-sentinel"
MAC = "AA_BB_CC_DD_EE_FF"
OTRA = "11_22_33_44_55_66"   # tambien de A, sin miembros
A, B, C, D = "uid_dueno", "uid_familia", "uid_ajeno", "uid_admin"


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def _token(uid):
    if uid == "admin":
        return "owner"   # el emulador lo trata como SDK de administrador
    if uid is None:
        return None
    ahora = int(time.time())
    return ".".join([_b64({"alg": "none", "typ": "JWT"}), _b64({
        "sub": uid, "user_id": uid, "aud": NS, "iat": ahora, "exp": ahora + 3600,
        "auth_time": ahora, "iss": f"https://securetoken.google.com/{NS}",
        "firebase": {"sign_in_provider": "password"}}), ""])


def _pedir(quien, metodo, ruta, cuerpo=None):
    """True si la RTDB lo permite, False si lo deniega."""
    # El emulador trata cualquier "Authorization: Bearer" como administrador:
    # el usuario va en ?auth=, el administrador en la cabecera.
    url = f"http://{HOST}/{ruta}.json?ns={NS}"
    tok = _token(quien)
    if tok and quien != "admin":
        url += f"&auth={tok}"
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, method=metodo)
    if quien == "admin":
        req.add_header("Authorization", "Bearer owner")
    try:
        urllib.request.urlopen(req).read()
        return True
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return False
        raise


def _sembrar():
    assert _pedir("admin", "PUT", "", {
        "ESP32": {
            MAC: {"ownerUid": A, "Nombre": "Casa", "Answer": False, "Telegram_ID": "1",
                  "Tiempo_Bomba": 30, "BengalaHab": True,
                  "Pendientes": {"x": {"autorizar": False}},
                  "miembros": {B: {"rol": "familia"}, D: {"rol": "admin"}}},
            OTRA: {"ownerUid": A, "Nombre": "Oficina"},
        },
        "Miembros": {MAC: {B: {"nombre": "Beto", "alta": 1}}},
        "Locales": {MAC: {"key": "ab" * 32, "pass": "p", "ssid": "Sentinel-1"}},
        "Horarios": {A: {"devices": {MAC: {"h1": {"activationTime": "22:00"}},
                                     OTRA: {"h1": {"activationTime": "08:00"}}}}},
        "Invitaciones": {"ABCDEFGH": {"mac": MAC, "invitadoPor": A, "expira": 1}},
    })


ORDEN = lambda por, **extra: {"accion": "arm", "por": por, "ts": 1764000000000, **extra}

# (quien, metodo, ruta, cuerpo, esperado, descripcion)
CASOS = [
    # Lectura del nodo
    (A, "GET", f"ESP32/{MAC}", None, True, "dueño lee la central"),
    (B, "GET", f"ESP32/{MAC}", None, True, "familia lee la central"),
    (C, "GET", f"ESP32/{MAC}", None, False, "ajeno no lee la central"),
    (None, "GET", f"ESP32/{MAC}", None, False, "anónimo no lee la central"),
    (B, "GET", f"ESP32/{OTRA}", None, False, "familia no lee otra central del dueño"),
    (C, "GET", "ESP32/00_00_00_00_00_00", None, True, "central inexistente: cualquiera (como hoy)"),
    # Orden (C1)
    (B, "PUT", f"ESP32/{MAC}/Orden", ORDEN(B), True, "familia manda Orden"),
    (B, "PUT", f"ESP32/{MAC}/Orden", ORDEN(B, local=True), True, "familia manda Orden local"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {**ORDEN(B), "accion": "panic"}, True, "familia manda pánico"),
    (A, "PUT", f"ESP32/{MAC}/Orden", ORDEN(A), True, "dueño también puede escribir Orden"),
    (C, "PUT", f"ESP32/{MAC}/Orden", ORDEN(C), False, "ajeno no manda Orden"),
    (B, "PUT", f"ESP32/{MAC}/Orden", ORDEN(A), False, "familia no firma como otro"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {**ORDEN(B), "accion": "borrar"}, False, "acción inventada"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {**ORDEN(B), "ts": "1"}, False, "ts no numérico"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {**ORDEN(B), "ts": 10 ** 15}, False, "ts del año 33658 (#273)"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {**ORDEN(B), "ts": 1}, False, "ts de 1970 (#273)"),
    # Llave local fuera del nodo que lee familia (#274)
    (A, "GET", f"Locales/{MAC}", None, True, "dueño lee la llave local"),
    (B, "GET", f"Locales/{MAC}", None, False, "familia no lee la llave local"),
    (C, "GET", f"Locales/{MAC}", None, False, "ajeno no lee la llave local"),
    (A, "PUT", f"Locales/{MAC}/key", "x", False, "nadie escribe la llave desde la app"),
    (B, "PUT", f"ESP32/{MAC}/Orden", ORDEN(B, extra=1), False, "hijo extra en Orden"),
    (B, "PUT", f"ESP32/{MAC}/Orden", {"accion": "arm", "por": B}, False, "Orden sin ts"),
    (B, "DELETE", f"ESP32/{MAC}/Orden", None, False, "familia no borra Orden"),
    # El miembro ya no escribe Answer ni DisparoApp (C1)
    (A, "PUT", f"ESP32/{MAC}/Answer", True, True, "dueño escribe Answer"),
    (B, "PUT", f"ESP32/{MAC}/Answer", True, False, "familia no escribe Answer"),
    (B, "PUT", f"ESP32/{MAC}/DisparoApp", True, False, "familia no escribe DisparoApp"),
    (C, "PUT", f"ESP32/{MAC}/Answer", True, False, "ajeno no escribe Answer"),
    # Configuración: solo el dueño
    (A, "PUT", f"ESP32/{MAC}/Nombre", "Casa 2", True, "dueño cambia el nombre"),
    (B, "PUT", f"ESP32/{MAC}/Nombre", "x", False, "familia no cambia el nombre"),
    (B, "PUT", f"ESP32/{MAC}/Telegram_ID", "9", False, "familia no cambia Telegram_ID"),
    (B, "PUT", f"ESP32/{MAC}/Tiempo_Bomba", 1, False, "familia no cambia Tiempo_Bomba"),
    (B, "PUT", f"ESP32/{MAC}/BengalaHab", False, False, "familia no cambia BengalaHab"),
    (B, "PUT", f"ESP32/{MAC}/Pendientes/x/autorizar", True, False, "familia no autoriza sensores"),
    (B, "PUT", f"ESP32/{MAC}/ownerUid", B, False, "familia no se queda la central"),
    (B, "PATCH", f"ESP32/{MAC}", {"ownerUid": B, "Nombre": "mía"}, False, "familia no se la queda con patch"),
    # Membresías (C3)
    (B, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia"}, False, "familia no invita"),
    (C, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia"}, False, "ajeno no se mete solo"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "dueno"}, False, "rol inventado"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{B}", {"rol": "admin"}, False, "el rol lo cambia solo el VPS (#314)"),
    (B, "PUT", f"ESP32/{MAC}/miembros/{B}/rol", "admin", False, "familia no se hace administrador"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia"}, False, "dueño no mete miembros sin invitación (#279)"),
    (A, "PATCH", f"ESP32/{MAC}", {"Nombre": "Casa 2", f"miembros/{C}": {"rol": "familia"}}, False,
     "ni colado en un update del nodo (#279)"),
    (A, "PATCH", f"ESP32/{MAC}", {"Nombre": "Casa"}, True, "el dueño sigue editando su central"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{B}", {"rol": "familia"}, True, "reescribir uno que ya existe, igual"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia", "nombre": "x"}, False, "miembros solo lleva rol"),
    (A, "PUT", f"ESP32/{MAC}/miembros/{C}", {}, True, "vacío = borrar (no existía)"),
    # Nombres de los miembros: solo los lee el dueño
    (A, "GET", f"Miembros/{MAC}", None, True, "dueño lee los nombres"),
    (B, "GET", f"Miembros/{MAC}", None, False, "familia no lee los nombres"),
    (C, "GET", f"Miembros/{MAC}", None, False, "ajeno no lee los nombres"),
    (A, "PUT", f"Miembros/{MAC}/{C}", {"nombre": "x"}, False, "nadie escribe Miembros desde el cliente"),
    (A, "GET", "Miembros/00_00_00_00_00_00", None, False, "Miembros de central borrada: nadie"),
    # Horarios (C6)
    (A, "GET", f"Horarios/{A}", None, True, "dueño lee sus horarios"),
    (B, "GET", f"Horarios/{A}", None, False, "familia no lee todos los horarios del dueño"),
    (B, "GET", f"Horarios/{A}/devices/{MAC}", None, True, "familia lee los horarios de su central"),
    (B, "GET", f"Horarios/{A}/devices/{OTRA}", None, False, "familia no lee los de otra central"),
    (C, "GET", f"Horarios/{A}/devices/{MAC}", None, False, "ajeno no lee horarios"),
    (B, "PUT", f"Horarios/{A}/devices/{MAC}/h1/enabled", False, False, "familia no edita horarios"),
    (B, "GET", f"Horarios/{B}/devices/{MAC}", None, True, "su propio árbol de horarios, como hoy"),
    # Administrador (#314): además horarios, bengala y sensores; nada del dueño
    (D, "PUT", f"ESP32/{MAC}/Orden", ORDEN(D), True, "admin manda Orden"),
    (D, "PUT", f"ESP32/{MAC}/BengalaHab", False, True, "admin cambia BengalaHab"),
    (D, "PATCH", f"ESP32/{MAC}", {"BengalaHab": True, "ModoBengala": 2}, True, "admin cambia el modo de bengala"),
    (D, "PUT", f"ESP32/{MAC}/BengalaHab", "x", False, "BengalaHab no booleano"),
    (D, "PUT", f"ESP32/{MAC}/Pendientes/x/autorizar", True, True, "admin autoriza un sensor"),
    (D, "PUT", f"ESP32/{MAC}/Pendientes/x/ignorado", True, True, "admin ignora un sensor"),
    (D, "PUT", f"ESP32/{MAC}/Sensors/MOV-1/borrar", True, True, "admin borra un sensor"),
    (D, "PUT", f"ESP32/{MAC}/Sensors/MOV-1/renombrar", "Sala", True, "admin renombra un sensor"),
    (D, "PUT", f"ESP32/{MAC}/Sensors/MOV-1", {"name": "x"}, False, "admin no reescribe el sensor entero"),
    (D, "PUT", f"Horarios/{A}/devices/{MAC}/h1/enabled", False, True, "admin edita los horarios de su central"),
    (D, "PUT", f"Horarios/{A}/devices/{OTRA}/h1/enabled", False, False, "admin no edita los de otra central"),
    (D, "GET", f"Horarios/{A}", None, False, "admin no lee todos los horarios del dueño"),
    (D, "PUT", f"ESP32/{MAC}/Nombre", "x", False, "admin no cambia el nombre"),
    (D, "PUT", f"ESP32/{MAC}/Telegram_ID", "9", False, "admin no cambia Telegram_ID"),
    (D, "PUT", f"ESP32/{MAC}/Tiempo_Bomba", 1, False, "admin no cambia Tiempo_Bomba"),
    (D, "PUT", f"ESP32/{MAC}/Answer", True, False, "admin no escribe Answer"),
    (D, "PUT", f"ESP32/{MAC}/ownerUid", D, False, "admin no se queda la central"),
    (D, "PUT", f"ESP32/{MAC}/miembros/{C}", {"rol": "familia"}, False, "admin no invita"),
    (D, "GET", f"Locales/{MAC}", None, False, "admin no lee la llave local del dueño"),
    (D, "GET", f"Miembros/{MAC}", None, False, "admin no lee los nombres"),
    (B, "PUT", f"ESP32/{MAC}/Sensors/MOV-1/borrar", True, False, "familia no borra sensores"),
    (B, "PUT", f"ESP32/{MAC}/ModoBengala", 2, False, "familia no cambia el modo de bengala"),
    # Invitaciones: solo VPS
    (A, "GET", "Invitaciones", None, False, "nadie lee Invitaciones"),
    (B, "PUT", "Invitaciones/ZZZZZZZZ", {"mac": MAC}, False, "nadie escribe Invitaciones"),
]


def _cargar_reglas():
    """Sube APP/database.rules.json al emulador: no depende de firebase.json."""
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "APP", "database.rules.json")
    with open(ruta, "rb") as f:
        req = urllib.request.Request(f"http://{HOST}/.settings/rules.json?ns={NS}",
                                     data=f.read(), method="PUT")
    req.add_header("Authorization", "Bearer owner")
    urllib.request.urlopen(req).read()


def main() -> int:
    _cargar_reglas()
    _sembrar()
    fallos = 0
    for quien, metodo, ruta, cuerpo, esperado, desc in CASOS:
        real = _pedir(quien, metodo, ruta, cuerpo)
        if real != esperado:
            fallos += 1
            print(f"FALLA: {desc}: {quien} {metodo} {ruta} -> {real}, se esperaba {esperado}")
        if real and metodo != "GET":
            _sembrar()   # cada caso parte del mismo árbol

    # Quitar al miembro le corta la lectura al momento
    _pedir("admin", "DELETE", f"ESP32/{MAC}/miembros/{B}")
    if _pedir(B, "GET", f"ESP32/{MAC}"):
        fallos += 1
        print("FALLA: un miembro quitado sigue leyendo la central")
    if _pedir(B, "GET", f"Horarios/{A}/devices/{MAC}"):
        fallos += 1
        print("FALLA: un miembro quitado sigue leyendo los horarios")

    total = len(CASOS) + 2
    print(f"{total - fallos}/{total} casos de reglas en verde")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
