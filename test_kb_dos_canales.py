"""
La base de conocimiento habla de los DOS canales, y el buscador lo encuentra.

Se escribio despues de reescribir la KB (fase 4 del plan de comandos) porque
redactar no es suficiente: el RAG responde con lo que su buscador RECUPERA, y
un parrafo nuevo que ningun fragmento devuelve es un parrafo que el usuario no
va a leer nunca. Aqui se comprueban las dos cosas por separado.

    python test_kb_dos_canales.py

CAPA 1 -- el texto. Sin modelo ni red: lee los .md y comprueba que lo que era
falso ya no esta y que lo nuevo si. Corre en cualquier maquina y es la que
protege de que alguien reintroduzca "/si o /no" mas adelante.

CAPA 2 -- el buscador. NO corre por defecto: hay que pedirla.

    python test_kb_dos_canales.py --buscador

Construye la KnowledgeBase igual que el bot y comprueba que ciertas preguntas
recuperan el archivo que ahora tiene la respuesta. Va aparte porque necesita
infraestructura: si `use_embeddings` esta activo y Ollama no contesta, `load()`
se queda pidiendo embeddings uno a uno y la tanda tarda minutos. Y porque
IMPORTA donde se ejecuta: en produccion el buscador usa embeddings, asi que una
tanda con TF-IDF no dice nada sobre produccion. Avisa por pantalla de cual esta
usando; si dice TF-IDF, el resultado no vale para decidir nada.

LO QUE ESTE TEST NO DICE. Construye su PROPIA KnowledgeBase leyendo los .md del
disco, asi que mide los archivos desplegados, no el indice que el bot tiene en
memoria. Un verde aqui NO significa que el bot ya conteste con lo nuevo: para
eso hace falta ademas /reload_kb, o reiniciar el servicio. Son dos
comprobaciones independientes y el orden entre ellas da igual; lo que no vale es
tomar una por la otra.
"""
import os
import sys

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")


def _leer(nombre: str) -> str:
    with open(os.path.join(KB_DIR, nombre), encoding="utf-8") as f:
        return f.read()


def _toda_la_kb() -> str:
    return "\n".join(
        _leer(n) for n in sorted(os.listdir(KB_DIR)) if n.endswith(".md")
    )


# ----------------------------------------------------------------------
# Capa 1: el texto
# ----------------------------------------------------------------------

def test_no_se_presentan_si_y_no_como_comandos():
    """
    `/si` y `/no` NO existen: no estan entre los CommandHandler del bot. La KB
    los daba por buenos para confirmar la bengala en modo Pregunta, y de aqui
    salen las respuestas al usuario, asi que era peor que tenerlo mal en un
    manual.
    """
    kb = _toda_la_kb()
    # Se permite nombrarlos para DESMENTIRLOS; lo que no puede haber es la
    # instruccion de usarlos.
    assert "con /si o /no" not in kb, "sigue diciendo que se confirma con /si o /no"
    assert "confirma con /si" not in kb
    assert "NO existen los comandos /si ni /no" in _leer("08_bengala.md"), \
        "falta el desmentido explicito en el doc de la bengala"


def test_los_permisos_no_dicen_que_la_app_no_pinta_nada():
    """
    El alta y la aprobacion de usuarios si son solo de Telegram, pero los
    DESTINATARIOS de cada equipo se editan en la ficha del dispositivo. Decir
    "no desde la app movil" a secas mandaba a Telegram a quien ya podia
    hacerlo donde estaba.
    """
    doc = _leer("12_usuarios_permisos.md")
    assert "no desde la app movil" not in doc
    assert "ficha del dispositivo" in doc, "falta decir donde se editan en la app"


def test_el_lenguaje_natural_menciona_los_dos_canales():
    """
    Era el peor de todos: hablaba solo del bot cuando el chat de la app entiende
    las mismas frases y tambien ejecuta.
    """
    doc = _leer("06_lenguaje_natural.md")
    for esperado in ("Senti", "Telegram", "app"):
        assert esperado in doc, f"06_lenguaje_natural.md no menciona {esperado}"
    assert "Confirmas?" in doc, "no explica que Senti pregunta antes de desarmar"


def test_se_dice_lo_que_la_app_NO_puede_hacer():
    """
    Un "no puedo" explicito ya es producto. Lo que la app no hace desde el chat
    tiene que estar escrito, o el usuario lo intenta y se queda sin saber que
    paso.
    """
    doc = _leer("06_lenguaje_natural.md")
    for accion in ("sirena", "Ultimo evento", "Bengala", "Horarios"):
        assert accion in doc, f"no dice que pasa con: {accion}"


def test_armado_menciona_el_asistente():
    doc = _leer("07_armado_desarmado.md")
    assert "Senti" in doc, "el doc de armado no menciona el asistente de la app"


def test_la_app_documenta_su_asistente():
    doc = _leer("04_app_sentinel_guard.md")
    assert "Senti" in doc, "el doc de la app no menciona a Senti"


# ----------------------------------------------------------------------
# Capa 2: el buscador
# ----------------------------------------------------------------------

#: (pregunta, archivo que DEBE aparecer entre las fuentes, texto que debe traer)
#: El texto es lo que de verdad importa: que el archivo salga pero devolviendo
#: el fragmento viejo no arregla nada.
CASOS = [
    ("como configuro la bengala",
     "08_bengala.md", "ficha del equipo"),
    ("como confirmo la bengala en modo pregunta",
     "08_bengala.md", "botones"),
    ("puedo darle ordenes al asistente de la app",
     "06_lenguaje_natural.md", "Senti"),
    ("que puede hacer senti y que no",
     "06_lenguaje_natural.md", "Senti"),
    ("como agrego un usuario nuevo",
     "12_usuarios_permisos.md", "destinatarios"),
    ("como armo la alarma desde la app",
     "07_armado_desarmado.md", "Senti"),
]


def _kb():
    from config import config
    from rag_handler import KnowledgeBase

    kb = KnowledgeBase(
        KB_DIR,
        ollama_base_url=config.ai.ollama_base_url,
        embed_model=config.ai.ollama_embed_model,
        use_embeddings=config.ai.use_embeddings,
    )
    kb.load()
    return kb


def test_el_buscador_encuentra_lo_nuevo():
    kb = _kb()
    con_embeddings = getattr(kb, "_embeddings", None) is not None
    print(f"      buscador: {'embeddings' if con_embeddings else 'TF-IDF'}", flush=True)
    if not con_embeddings:
        print("      OJO: produccion usa embeddings. Esta tanda no dice nada de produccion.", flush=True)

    fallos = []
    for pregunta, archivo, texto in CASOS:
        res = kb.search(pregunta, top_k=4)
        fuentes = [r.chunk.source_file for r in res]
        recuperado = "\n".join(r.chunk.text for r in res)
        if archivo not in fuentes:
            fallos.append(f"'{pregunta}' -> no trajo {archivo}, trajo {fuentes}")
        elif texto.lower() not in recuperado.lower():
            fallos.append(
                f"'{pregunta}' -> trajo {archivo} pero sin '{texto}' "
                f"(fragmento viejo)"
            )
    assert not fallos, "\n        " + "\n        ".join(fallos)


if __name__ == "__main__":
    con_buscador = "--buscador" in sys.argv
    pruebas = [
        v for k, v in sorted(globals().items())
        if k.startswith("test_")
        and (con_buscador or k != "test_el_buscador_encuentra_lo_nuevo")
    ]
    if not con_buscador:
        print("(solo la capa del texto; para la del buscador: --buscador)", flush=True)
        print("", flush=True)
    fallos = 0
    for t in pruebas:
        try:
            t()
            print(f"  ok  {t.__name__}", flush=True)
        except AssertionError as e:
            fallos += 1
            print(f"FALLO  {t.__name__}: {e}", flush=True)
        except Exception as e:
            fallos += 1
            print(f"ERROR  {t.__name__}: {type(e).__name__}: {e}", flush=True)
    print(f"\n{len(pruebas) - fallos}/{len(pruebas)} pruebas pasan")
    sys.exit(1 if fallos else 0)
