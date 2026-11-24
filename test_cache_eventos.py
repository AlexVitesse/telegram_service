"""El cache del listener aplica put/patch en la ruta completa (auditoría 23-nov, #272).

Antes un evento en /{mac}/miembros/{uid} dejaba miembros = {"rol": "familia"}
y borrar un miembro borraba a todos.
"""
from types import SimpleNamespace

from firebase_manager import FirebaseManager


def _ev(tipo, ruta, datos):
    return SimpleNamespace(event_type=tipo, path=ruta, data=datos)


def main():
    fm = object.__new__(FirebaseManager)
    fm._all_devices_cache = None
    fm._cache_timestamp = 0
    aplicar = fm._update_cache_from_event

    aplicar(_ev("put", "/m1/Answer", True))            # sin snapshot: se ignora
    assert fm._all_devices_cache is None
    aplicar(_ev("put", "/", {"m1": {"ownerUid": "o", "miembros": {"a": {"rol": "familia"}}, "Local": {"key": "k"}}}))
    m1 = fm._all_devices_cache["m1"]

    aplicar(_ev("put", "/m1/miembros/b", {"rol": "familia"}))
    assert m1["miembros"] == {"a": {"rol": "familia"}, "b": {"rol": "familia"}}, m1["miembros"]
    aplicar(_ev("put", "/m1/miembros/a", None))
    assert m1["miembros"] == {"b": {"rol": "familia"}}, m1["miembros"]
    aplicar(_ev("patch", "/m1/miembros", {"c": {"rol": "familia"}, "b": None}))
    assert m1["miembros"] == {"c": {"rol": "familia"}}, m1["miembros"]
    aplicar(_ev("patch", "/m1", {"Answer": True, "Local/key": "k2"}))
    assert m1["Answer"] is True and m1["Local"] == {"key": "k2"} and m1["ownerUid"] == "o"
    aplicar(_ev("patch", "/", {"m2/Answer": False}))  # patch en raíz no pisa el resto
    assert set(fm._all_devices_cache) == {"m1", "m2"}
    aplicar(_ev("put", "/m2/x/y", None))               # borrar ruta inexistente: sin efecto
    assert fm._all_devices_cache["m2"] == {"Answer": False}
    aplicar(_ev("put", "/m1", {"ownerUid": "n"}))      # put de nodo reemplaza (traspaso)
    assert fm._all_devices_cache["m1"] == {"ownerUid": "n"}
    aplicar(_ev("put", "/m2", None))
    assert "m2" not in fm._all_devices_cache
    print("test_cache_eventos: OK")


if __name__ == "__main__":
    main()
