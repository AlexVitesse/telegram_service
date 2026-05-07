#!/usr/bin/env python3
"""
Tests del helper chat_id_utils.

Cubre todos los casos limite de la heuristica de auto-correccion de
supergrupos sin '-':

  - Supergrupo malformado (corregir):  1001234567890, 1009999999999
  - User ID legitimo (NO tocar):       123456789, 8500000000
  - Mid-range ambiguo (NO tocar):      100123456789 (12 digitos)
  - Ya tiene '-' (NO tocar):           -1001234567890
  - Edge cases:                        None, "", strings con espacios

Uso:
    python test_chat_id_utils.py
"""
from __future__ import annotations

import logging
import sys

# Silenciar logs durante los tests para output limpio
logging.basicConfig(level=logging.CRITICAL)

from chat_id_utils import looks_like_stripped_supergroup, normalize_chat_id


# Cada caso: (input, esperado_es_supergrupo_malformado, esperado_normalizado_con_autofix)
CASES = [
    # ------- Supergrupos malformados (deben corregirse) -------
    ("1001234567890",   True,  "-1001234567890"),    # 13 digitos, empieza con 100
    ("1009999999999",   True,  "-1009999999999"),    # ultimo valor posible del rango
    ("1000000000000",   True,  "-1000000000000"),    # primer valor posible del rango
    (1001234567890,     True,  "-1001234567890"),    # input como int

    # ------- User IDs legitimos (NO se tocan) -------
    ("123456789",       False, "123456789"),         # 9 digitos clasico
    ("1234567890",      False, "1234567890"),        # 10 digitos
    ("8500000000",      False, "8500000000"),        # rango actual de Telegram
    ("12345",           False, "12345"),             # user ID viejo corto
    (123456789,         False, "123456789"),         # input como int

    # ------- Patron parecido pero NO match estricto -------
    ("100123456789",    False, "100123456789"),      # 12 digitos (uno menos)
    ("10012345678901",  False, "10012345678901"),    # 14 digitos (uno mas)
    ("2001234567890",   False, "2001234567890"),     # 13 digitos pero NO empieza con 100
    ("1991234567890",   False, "1991234567890"),     # 13 digitos pero prefijo distinto

    # ------- Ya esta correctamente formateado -------
    ("-1001234567890",  False, "-1001234567890"),    # supergrupo OK con '-'
    ("-1234567890",     False, "-1234567890"),       # grupo basico legacy
    (-1001234567890,    False, "-1001234567890"),    # int negativo

    # ------- Inputs degenerados -------
    (None,              False, ""),
    ("",                False, ""),
    ("   ",             False, ""),
    ("  1001234567890  ", True, "-1001234567890"),   # con espacios al borde
    ("abc",             False, "abc"),               # no numerico
    ("100abc1234567",   False, "100abc1234567"),     # mezclado
]


def run_tests():
    failures = 0
    total = len(CASES) * 2  # cada caso testea looks_like + normalize

    for raw, expected_looks, expected_norm in CASES:
        # Test 1: looks_like_stripped_supergroup
        got_looks = looks_like_stripped_supergroup(raw)
        if got_looks != expected_looks:
            print(f"  [FAIL] looks_like_stripped_supergroup({raw!r}) = {got_looks}, esperado {expected_looks}")
            failures += 1

        # Test 2: normalize_chat_id (auto_fix=True por default)
        got_norm = normalize_chat_id(raw, auto_fix=True)
        if got_norm != expected_norm:
            print(f"  [FAIL] normalize_chat_id({raw!r}) = {got_norm!r}, esperado {expected_norm!r}")
            failures += 1

    # Test 3: auto_fix=False NO aplica el fix pero loguea error
    val = normalize_chat_id("1001234567890", auto_fix=False)
    if val != "1001234567890":
        print(f"  [FAIL] normalize con auto_fix=False deberia devolver {val!r} sin tocar")
        failures += 1
        total += 1
    else:
        total += 1

    print()
    passed = total - failures
    print(f"{'='*50}")
    print(f"RESULTADO: {passed}/{total} pasaron, {failures} fallos")
    print(f"{'='*50}")
    return failures


if __name__ == "__main__":
    sys.exit(0 if run_tests() == 0 else 1)
