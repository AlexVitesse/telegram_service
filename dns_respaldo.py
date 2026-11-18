"""Respaldo de DNS dentro del proceso (no hay sudo en el VPS para cambiar el DNS del sistema).

El router 193.167.200.1, que es el único DNS del VPS, da SERVFAIL para oauth2.googleapis.com, y del 15 al
17-nov-2026 eso dejó al servicio sin Firebase. Este módulo envuelve socket.getaddrinfo: si el sistema no
resuelve un nombre, lo pregunta por DNS sobre HTTPS a 1.1.1.1 o 8.8.8.8 (por IP, así que no necesita DNS)
y reintenta con la IP que obtiene. TLS sigue usando el nombre original (SNI y certificado), porque solo
cambia la resolución.
Ver docs/INCIDENTE_DNS_VPS_2026-11-18.md.
"""
import json
import logging
import socket
import ssl
import urllib.request

logger = logging.getLogger(__name__)

_original = socket.getaddrinfo
_DOH = ("https://1.1.1.1/dns-query", "https://8.8.8.8/resolve")
_CTX = ssl.create_default_context()


def _doh(nombre: str) -> list:
    """IPs (A) de `nombre` según DoH; [] si nadie responde."""
    for url in _DOH:
        try:
            req = urllib.request.Request(f"{url}?name={nombre}&type=A",
                                         headers={"accept": "application/dns-json"})
            with urllib.request.urlopen(req, timeout=5, context=_CTX) as r:
                datos = json.load(r)
            ips = [a["data"] for a in datos.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception as e:  # noqa: BLE001 - probar el siguiente proveedor
            logger.debug(f"DoH {url} falló para {nombre}: {e}")
    return []


def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    try:
        return _original(host, port, family, type, proto, flags)
    except socket.gaierror:
        # ponytail: sin caché, cada falla del sistema hace una consulta DoH (~50 ms); poner caché por TTL si se nota.
        if not isinstance(host, str) or family == socket.AF_INET6:
            raise
        ips = _doh(host)
        if not ips:
            raise
        logger.warning(f"DNS del sistema no resolvió {host}; uso DoH -> {ips[0]}")
        res = []
        for ip in ips:
            res += _original(ip, port, socket.AF_INET, type, proto, flags | socket.AI_NUMERICHOST)
        return res


def activar():
    socket.getaddrinfo = _getaddrinfo


if __name__ == "__main__":
    # Prueba: un nombre que el sistema "no resuelve" debe salir por DoH.
    def _falla(host, *a, **k):
        if host == "oauth2.googleapis.com":
            raise socket.gaierror(-3, "Temporary failure in name resolution")
        return _real(host, *a, **k)
    _real = _original
    _original = _falla
    activar()
    r = socket.getaddrinfo("oauth2.googleapis.com", 443, type=socket.SOCK_STREAM)
    assert r and r[0][0] == socket.AF_INET, r
    assert socket.getaddrinfo("localhost", 80)  # lo normal sigue igual
    try:
        socket.getaddrinfo("no-existe.invalid", 80)
        raise AssertionError("debió fallar")
    except socket.gaierror:
        pass
    import urllib.error
    try:  # TLS con el nombre original sobre la IP de DoH (404 = conectó bien)
        urllib.request.urlopen("https://oauth2.googleapis.com/", timeout=10)
    except urllib.error.HTTPError:
        pass
    print("ok", r[0][4][0])
