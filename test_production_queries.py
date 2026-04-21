#!/usr/bin/env python3
"""
Test de las 11 preguntas reales observadas en prodlog2.1 (2026-04-16).

Reproduce cada consulta que los usuarios PANA y Oscar enviaron al bot
y evalua si la respuesta del pipeline (intent parsing + RAG) mejora
respecto al baseline observado en produccion.

Uso:
    python test_production_queries.py
    python test_production_queries.py --backend ollama
"""
import asyncio
import os
import sys
import time
import unicodedata

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from ai_handler import AIHandler
from rag_handler import KnowledgeBase


GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Dispositivos simulados acordes con lo observado en produccion
# PANA tenia 4, Oscar 1. Usamos una mezcla para cubrir los casos.
MOCK_DEVICES = [
    {"id": "08_D1_F9_E7_41_E", "name": "Casa", "is_armed": True, "is_online": True},
    {"id": "6C_C8_40_4F_C7", "name": "Estudio", "is_armed": True, "is_online": True},
    {"id": "C8_2E_18_26_60", "name": "Bodega", "is_armed": False, "is_online": True},
    {"id": "A0_A3_B3_2F_A2", "name": "Oficina", "is_armed": False, "is_online": True},
]


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def contains_word(haystack: str, needle: str) -> bool:
    return strip_accents(needle.lower()) in strip_accents(haystack.lower())


# Cada entrada:
#   user:                usuario real
#   query:               texto enviado
#   intent:              'arm' | 'disarm' | 'status' | 'question' | 'query_schedule' | 'list_devices' | None (acepta cualquiera)
#   rag_expect_words:    palabras que DEBEN aparecer en la respuesta RAG (si aplica)
#   rag_forbid_words:    palabras que NO deben aparecer
#   rag_expect_source:   fragmento de source_file que deberia estar entre las fuentes
#   baseline:            que paso en prod (para reporte comparativo)
PRODUCTION_QUERIES = [
    {
        "id": 1,
        "user": "PANA",
        "query": "Horario que se encuentra?",
        "intent": "query_schedule",
        "baseline": "crash AttributeError cfg.on_time_display (NO hubo respuesta)",
        "fix": "Fix #1 - cambiado a format_on_time_12h()",
    },
    {
        "id": 2,
        "user": "PANA",
        "query": "Horarios?",
        "intent": "query_schedule",
        "baseline": "Ollama devolvio JSON vacio - respondio 'No entendi'",
        "fix": "Fix #2/#3 - validacion + fallback a Groq",
    },
    {
        "id": 3,
        "user": "PANA",
        "query": "Horario que se encuentra Estudio?",
        "intent": "query_schedule",
        "expected_device": "Estudio",
        "baseline": "JSON vacio - 'No entendi'",
        "fix": "Fix #2/#3",
    },
    {
        "id": 4,
        "user": "PANA",
        "query": "Activa la alarma",
        "intent": "arm",
        "baseline": "OK - armed 4 dispositivos",
        "fix": "ya funcionaba",
    },
    {
        "id": 5,
        "user": "PANA",
        "query": "Que alarma esta activada?",
        "intent": "status",
        "baseline": "JSON vacio - 'No entendi'",
        "fix": "Fix #2/#3",
    },
    {
        "id": 6,
        "user": "Oscar",
        "query": "Me puedes ayudar a instalar el sensor",
        "intent": "question",
        "rag_expect_words": ["sensor", "instal"],
        "rag_expect_source_any": ["instalacion_hardware", "solucion_problemas"],
        "baseline": "RAG devolvio troubleshooting en vez de instalacion - regular",
        "fix": "ok, 'ayuda' ahora tambien dispara boost troubleshooting pero respuesta sigue util",
    },
    {
        "id": 7,
        "user": "Oscar",
        "query": "Tengo problemas con el modulo de bengala",
        "intent": "question",
        "rag_expect_words": ["bengala"],
        "rag_expect_source_any": ["solucion_problemas", "bengala"],
        "rag_forbid_words": ["/config_bengala"],
        "baseline": "JSON vacio - 'No entendi'",
        "fix": "Fix #2/#3 + boost troubleshooting (Fix #4)",
    },
    {
        "id": 8,
        "user": "Oscar",
        "query": "Tengo problema con la bengala",
        "intent": "question",
        "rag_expect_words": ["bengala"],
        "rag_expect_source_any": ["solucion_problemas", "bengala"],
        "rag_forbid_source_only": ["lenguaje_natural"],  # NO debe ser el unico
        "baseline": "RAG fue a lenguaje_natural y dio instrucciones de disparo (MAL)",
        "fix": "Fix #4 - boost troubleshooting",
    },
    {
        "id": 9,
        "user": "Oscar",
        "query": "Como configuro el sensor de la puerta?",
        "intent": "question",
        "rag_expect_words": ["sensor", "puerta"],
        "rag_expect_source_any": ["instalacion_hardware"],
        "baseline": "OK - RAG respondio con magnetico",
        "fix": "ya funcionaba",
    },
    {
        "id": 10,
        "user": "Oscar",
        "query": "Como configuro el master con todos los demas componentes que trae el kit?",
        "intent": "question",
        "rag_expect_words": ["master", "kit"],
        "rag_expect_source_any": ["configuracion_inicial", "sistema_general"],
        "baseline": "RAG: 'No encontre informacion relevante' (MAL)",
        "fix": "Fix #5 - agregado seccion 'Configuracion del kit completo'",
    },
    {
        "id": 11,
        "user": "Oscar",
        "query": "Como sincroniso en master con todos los demas componentes?",
        "intent": "question",
        "rag_expect_words": ["master"],
        "rag_expect_source_any": ["configuracion_inicial", "sistema_general", "horarios"],
        "baseline": "RAG hablo de sync de horarios, no de pareo inicial (regular)",
        "fix": "Fix #5 - nuevo chunk habla de modulos preparados",
    },
    {
        "id": 12,
        "user": "PANA",
        "query": "Como configuro los permisos",
        "intent": "question",
        "rag_expect_words": ["permisos", "admin"],
        "rag_expect_source_any": ["usuarios_permisos"],
        "baseline": "RAG respondio 'No tengo esa informacion' - fuentes: bengala, configuracion_inicial (MAL)",
        "fix": "Fix filename-in-embedding (rag_handler._chunk_index_text)",
    },
    {
        "id": 13,
        "user": "PANA",
        "query": "Los Permisos como se configura?",
        "intent": "question",
        "rag_expect_words": ["permisos"],
        "rag_expect_source_any": ["usuarios_permisos"],
        "baseline": "Mismo fallo que #12 - fuentes: bengala, configuracion_inicial (MAL)",
        "fix": "Parcial: el filename-in-embedding no alcanza; requiere sinonimos en 12_usuarios_permisos.md",
    },
    {
        "id": 14,
        "user": "PANA",
        "query": "Gestionar usuarios?",
        "intent": "question",
        "rag_expect_words": ["usuarios", "admin"],
        "rag_expect_source_any": ["usuarios_permisos"],
        "baseline": "OK pero incompleto - no mencionaba /adduser ni /approve_CHATID (solo /start, /permisos, Telegram_ID_2)",
        "fix": "Fix filename-in-embedding mejora recall; seccion 'Agregar nuevos usuarios' entra mejor en top-k",
    },
]


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}PASS{RESET} {msg}")

def fail(msg):
    print(f"  {RED}FAIL{RESET} {msg}")

def warn(msg):
    print(f"  {YELLOW}WARN{RESET} {msg}")

def info(msg):
    print(f"  {BLUE}INFO{RESET} {msg}")

def header(msg):
    print(f"\n{BOLD}{CYAN}{'='*70}{RESET}")
    print(f"{BOLD}{CYAN}{msg}{RESET}")
    print(f"{BOLD}{CYAN}{'='*70}{RESET}")


async def run_case(ai: AIHandler, kb: KnowledgeBase, case: dict) -> tuple[bool, str]:
    """
    Ejecuta un caso. Retorna (passed, detail).
    """
    query = case["query"]
    expected_intent = case.get("intent")

    # Paso 1: intent parsing
    t0 = time.time()
    intent_result = await ai.parse_intent(query, MOCK_DEVICES)
    elapsed_intent = time.time() - t0

    if intent_result is None:
        return False, f"parse_intent None despues de {elapsed_intent:.1f}s (esperaba {expected_intent})"

    actual_intent = intent_result["intent"]
    intent_ok = (expected_intent is None) or (actual_intent == expected_intent)

    details = [f"intent='{actual_intent}' (conf={intent_result['confidence']:.2f}) en {elapsed_intent:.1f}s"]

    # Si no es question, basta con intent OK
    if actual_intent != "question":
        if intent_ok:
            return True, "; ".join(details)
        return False, f"intent esperado='{expected_intent}' recibido='{actual_intent}'"

    # Paso 2: RAG (solo si intent es question o expected_intent era question)
    results = kb.search(query, top_k=4, min_score=0.08)
    if not results:
        return False, f"{details[0]}; RAG sin resultados (>{'0.08'})"

    sources = [r.chunk.source_file for r in results]
    scores = [r.score for r in results]
    details.append(f"RAG sources={sources} scores={[f'{s:.2f}' for s in scores]}")

    # Validacion de source
    expect_sources = case.get("rag_expect_source_any", [])
    if expect_sources:
        source_match = any(
            any(exp in s for s in sources)
            for exp in expect_sources
        )
        if not source_match:
            return False, "; ".join(details) + f"; esperaba source en {expect_sources}"

    # Validacion: forbid source_only
    forbid_only = case.get("rag_forbid_source_only", [])
    if forbid_only and all(
        any(forb in s for forb in forbid_only) for s in sources
    ):
        return False, "; ".join(details) + f"; SOLO uso fuentes prohibidas {forbid_only}"

    # Generar respuesta con LLM (si tenemos credenciales)
    chunks = [r.chunk.text for r in results]
    answer = await ai.chat_with_context(query, chunks)
    details.append(f"respuesta={answer[:120]}...")

    # Validar palabras esperadas
    expect_words = case.get("rag_expect_words", [])
    missing = [w for w in expect_words if not contains_word(answer, w)]
    if missing:
        return False, "; ".join(details) + f"; faltaron palabras {missing}"

    # Validar palabras prohibidas
    forbid = case.get("rag_forbid_words", [])
    banned = [w for w in forbid if contains_word(answer, w)]
    if banned:
        return False, "; ".join(details) + f"; alucino {banned}"

    return True, "; ".join(details)


async def main():
    backend = "groq"
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        backend = sys.argv[2] if len(sys.argv) > 2 else "groq"

    if backend == "groq" and not GROQ_API_KEY:
        print(f"{RED}Error: GROQ_API_KEY no configurada en .env{RESET}")
        sys.exit(1)

    intent_model = os.getenv("INTENT_MODEL", "llama-3.1-8b-instant")
    chat_model = os.getenv("CHAT_MODEL", "openai/gpt-oss-20b")

    print(f"{BOLD}Backend:      {backend}{RESET}")
    print(f"Intent model: {intent_model}")
    print(f"Chat model:   {chat_model}")
    print(f"Embeddings:   {OLLAMA_EMBED_MODEL} (Ollama @ {OLLAMA_URL})")

    ai = AIHandler(
        llm_backend=backend,
        ollama_base_url=OLLAMA_URL,
        ollama_model=OLLAMA_MODEL,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        intent_model=intent_model,
        chat_model=chat_model,
    )

    kb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")
    kb = KnowledgeBase(
        kb_dir,
        ollama_base_url=OLLAMA_URL,
        embed_model=OLLAMA_EMBED_MODEL,
        use_embeddings=True,
    )
    count = kb.load()
    if count == 0:
        print(f"{RED}No se pudo cargar knowledge_base{RESET}")
        return

    print(f"\nKnowledge base: {count} chunks")

    header("11 PREGUNTAS REALES DE PRODUCCION")

    passed = 0
    failed = 0
    results_table = []

    for case in PRODUCTION_QUERIES:
        print(f"\n{BOLD}#{case['id']} ({case['user']}){RESET} \"{case['query']}\"")
        info(f"baseline prod: {case['baseline']}")
        info(f"fix aplicado:  {case['fix']}")

        try:
            success, detail = await run_case(ai, kb, case)
        except Exception as e:
            success = False
            detail = f"EXCEPTION: {type(e).__name__}: {e}"

        if success:
            ok(detail)
            passed += 1
            results_table.append((case['id'], case['user'], case['query'][:40], "PASS"))
        else:
            fail(detail)
            failed += 1
            results_table.append((case['id'], case['user'], case['query'][:40], "FAIL"))

    header("RESUMEN")
    for row in results_table:
        color = GREEN if row[3] == "PASS" else RED
        print(f"  #{row[0]:>2} {row[1]:<8} {row[2]:<42} {color}{row[3]}{RESET}")

    total = passed + failed
    print(f"\n  {BOLD}Total: {passed}/{total} ({passed*100//total}%){RESET}")

    if failed == 0:
        print(f"\n  {GREEN}{BOLD}ALL PRODUCTION QUERIES PASS{RESET}")
    else:
        print(f"\n  {RED}{BOLD}{failed} FALLARON{RESET}")

    await ai.close()


if __name__ == "__main__":
    asyncio.run(main())
