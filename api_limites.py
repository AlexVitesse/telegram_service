"""
Tope de uso del endpoint por usuario.

Cada pregunta gasta una llamada al LLM, asi que un token valido sin tope basta
para vaciar la cuota de Groq. Son dos limites distintos y hacen falta los dos:

- **Por hora**: el gasto sostenido. Alguien preguntando todo el dia.
- **Entre preguntas**: la rafaga. Un bucle mal escrito en la app, o un dedo
  nervioso en el boton de enviar, dispara veinte peticiones en dos segundos y
  el limite por hora no las para hasta que ya se gastaron.

Vive en memoria a proposito: el servicio es un solo proceso y el tope no tiene
que sobrevivir a un reinicio. Si algun dia hay varias instancias, esto se cae
—cada una llevaria su propia cuenta— y habria que moverlo a Redis o a RTDB.
"""
import math
import time
from collections import deque
from typing import Deque, Dict, Optional, Tuple

VENTANA_SEG = 3600.0


class Limitador:
    def __init__(self, max_por_hora: int, espera_min_seg: float):
        self.max_por_hora = max_por_hora
        self.espera_min_seg = espera_min_seg
        self._historial: Dict[str, Deque[float]] = {}

    def permitir(self, uid: str, ahora: Optional[float] = None) -> Tuple[bool, str]:
        """
        ¿Puede este uid preguntar ahora?

        Devuelve `(permitido, motivo)`. El motivo va al usuario, asi que dice
        cuanto falta en vez de "limite excedido" a secas: sin un numero, lo
        unico que puede hacer es reintentar a ciegas.
        """
        t = time.monotonic() if ahora is None else ahora
        cola = self._historial.setdefault(uid, deque())

        # Fuera lo que ya salio de la ventana.
        while cola and t - cola[0] > VENTANA_SEG:
            cola.popleft()

        if cola and t - cola[-1] < self.espera_min_seg:
            # ceil y minimo 1: con .0f, esperar 0.4 s se leia como "espera 0 s",
            # que no le dice nada a nadie. Siempre hacia arriba, para que al
            # cumplirse el numero la peticion pase de verdad.
            falta = max(1, math.ceil(self.espera_min_seg - (t - cola[-1])))
            return False, f"Espera {falta} s antes de la siguiente pregunta."

        if len(cola) >= self.max_por_hora:
            faltan_min = int((VENTANA_SEG - (t - cola[0])) / 60) + 1
            return (
                False,
                f"Has alcanzado el limite de {self.max_por_hora} preguntas por "
                f"hora. Vuelve a intentarlo en {faltan_min} min.",
            )

        cola.append(t)
        return True, ""

    def olvidar(self, uid: str) -> None:
        """Solo para pruebas."""
        self._historial.pop(uid, None)


def normalizar_pregunta(texto: object, largo_max: int = 500) -> Optional[str]:
    """
    Valida y recorta lo que llega por HTTP.

    Devuelve `None` si no sirve. El largo maximo no es capricho: el texto entra
    en el prompt del LLM, asi que un campo sin limite es una factura sin limite.
    """
    if not isinstance(texto, str):
        return None
    limpio = " ".join(texto.split())
    if not limpio:
        return None
    return limpio[:largo_max]
