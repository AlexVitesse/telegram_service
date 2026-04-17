#!/usr/bin/env python3
"""
Test RAG + AI Handler
=====================
Prueba el flujo completo: intent parsing + RAG search + respuestas.
Usa Groq en dev local u Ollama si está disponible.

Uso:
    python test_rag.py
    python test_rag.py --backend ollama
"""
import asyncio
import os
import sys
import time
import unicodedata

# Fix Windows encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Agregar directorio actual al path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from ai_handler import AIHandler
from rag_handler import KnowledgeBase


# ─── Configuración ───────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Dispositivos simulados para intent parsing
MOCK_DEVICES = [
    {"id": "6C_C8_40_4F_C7", "name": "Estudio", "is_armed": False, "is_online": True},
    {"id": "AC_15_18_D5_2D", "name": "Oficina", "is_armed": True, "is_online": True},
]

def strip_accents(text: str) -> str:
    """Remove unicode accents for accent-insensitive comparison."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def contains_word(haystack: str, needle: str) -> bool:
    """Check if needle is found in haystack, accent-insensitive."""
    return strip_accents(needle.lower()) in strip_accents(haystack.lower())


# ─── Casos de test ───────────────────────────────────────────────────

INTENT_TESTS = [
    # (mensaje, intent_esperado, descripción)
    ("activa la alarma", "arm", "Comando armar - directo"),
    ("apaga el sistema", "disarm", "Comando desarmar - directo"),
    ("como esta la alarma?", "status", "Consulta estado"),
    ("silencia la sirena", "stop_alarm", "Detener sirena"),
    ("cuantos dispositivos tengo?", "list_devices", "Listar dispositivos"),
    ("arma la de Estudio", "arm", "Armar dispositivo específico"),
    ("desarma la Oficina", "disarm", "Desarmar dispositivo específico"),
    ("dispara la bengala", "trigger_bengala", "Activar bengala"),
    ("cuando fue la ultima alarma?", "last_event", "Ultimo evento"),
    ("arma lunes a viernes de 10pm a 6am", "schedule", "Configurar horario"),
    ("que horarios tengo?", "query_schedule", "Consultar horarios"),
    # Preguntas informativas (deben ser "question")
    ("como configuro la bengala?", "question", "Pregunta sobre bengala"),
    ("como agrego un usuario?", "question", "Pregunta sobre usuarios"),
    ("que hago si mi dispositivo esta offline?", "question", "Pregunta troubleshooting"),
    ("que es el modo pregunta de la bengala?", "question", "Pregunta concepto"),
    ("como cambio la contrasena del teclado?", "question", "Pregunta teclado"),
    # Unknown (no relacionado)
    ("que tiempo hace hoy?", "unknown", "Mensaje no relacionado"),
    ("hola que tal", "unknown", "Saludo genérico"),
]

RAG_TESTS = [
    # (pregunta, palabras_esperadas_en_respuesta, descripción)
    (
        "como configuro la bengala?",
        ["auto", "pregunta", "deshabilitad"],
        "Debe mencionar los 3 modos de bengala"
    ),
    (
        "como agrego un nuevo usuario al sistema?",
        ["adduser", "join", "admin"],
        "Debe mencionar /adduser y el flujo de invitación"
    ),
    (
        "mi dispositivo aparece offline que hago?",
        ["wifi", "encendido", "reconect"],
        "Debe dar pasos de troubleshooting"
    ),
    (
        "como armo la alarma desde el teclado?",
        ["contrasena", "1234", "#"],
        "Debe explicar uso del teclado"
    ),
    (
        "que pasa si se va la luz?",
        ["alimentacion", "bateria", "reconect"],
        "Debe explicar comportamiento sin luz"
    ),
    (
        "como programo horarios automaticos?",
        ["horarios", "activar", "desactivar"],
        "Debe explicar /horarios o app"
    ),
    (
        "cuantos dispositivos puedo tener?",
        ["ltiple", "dispositivo"],
        "Debe responder sobre multi-dispositivo"
    ),
    (
        "como instalo el sensor de movimiento?",
        ["altura", "PIR", "110", "7 metro"],
        "Debe dar instrucciones de instalación PIR"
    ),
]

RAG_HALLUCINATION_TESTS = [
    # (pregunta, palabras_prohibidas, descripción)
    (
        "como configuro la bengala?",
        ["intensidad media", "intensidad baja", "intensidad alta", "/config_bengala"],
        "No debe inventar niveles de intensidad ni comandos falsos"
    ),
    (
        "como agrego un usuario?",
        ["/adduser_", "/register", "/invite"],
        "No debe inventar comandos que no existen"
    ),
]


# ─── Colores para terminal ───────────────────────────────────────────
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


def ok(msg):
    print(f"  {GREEN}PASS{RESET} {msg}")

def fail(msg):
    print(f"  {RED}FAIL{RESET} {msg}")

def warn(msg):
    print(f"  {YELLOW}WARN{RESET} {msg}")

def header(msg):
    print(f"\n{BOLD}{CYAN}{'='*60}{RESET}")
    print(f"{BOLD}{CYAN}{msg}{RESET}")
    print(f"{BOLD}{CYAN}{'='*60}{RESET}")


# ─── Tests ────────────────────────────────────────────────────────────

async def test_knowledge_base():
    """Test 1: Carga y búsqueda en Knowledge Base."""
    header("TEST 1: Knowledge Base (TF-IDF)")

    kb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base")
    kb = KnowledgeBase(
        kb_dir,
        ollama_base_url=OLLAMA_URL,
        embed_model=OLLAMA_EMBED_MODEL,
        use_embeddings=True,
    )
    count = kb.load()

    if count > 0:
        ok(f"Cargados {count} chunks de knowledge_base/")
    else:
        fail("No se cargaron chunks")
        return None

    # Probar búsquedas
    test_queries = [
        ("bengala", "bengala"),
        ("sirena", "sirena"),
        ("offline", "solucion"),
        ("teclado contrasena", "teclado"),
        ("agregar usuario", "usuarios"),
        ("horarios programar", "horarios"),
        ("instalar sensor movimiento", "instalacion"),
    ]

    passed = 0
    for query, expected_topic in test_queries:
        results = kb.search(query, top_k=3, min_score=0.05)
        if results:
            top = results[0]
            ok(f"'{query}' -> score={top.score:.3f} | {top.chunk.source_file}:{top.chunk.heading[:40]}")
            passed += 1
        else:
            fail(f"'{query}' -> sin resultados (ni con score 0.05)")

    print(f"\n  Búsquedas: {passed}/{len(test_queries)} pasaron")
    return kb


async def test_intent_parsing(ai: AIHandler):
    """Test 2: Intent parsing con LLM."""
    header("TEST 2: Intent Parsing")

    passed = 0
    failed = 0

    for msg, expected_intent, desc in INTENT_TESTS:
        t0 = time.time()
        result = await ai.parse_intent(msg, MOCK_DEVICES)
        elapsed = time.time() - t0

        if result is None:
            if expected_intent == "unknown":
                ok(f"({elapsed:.1f}s) '{msg}' -> None (esperado unknown)")
                passed += 1
            else:
                fail(f"({elapsed:.1f}s) '{msg}' -> None (esperado {expected_intent}) [{desc}]")
                failed += 1
            continue

        actual = result["intent"]
        confidence = result["confidence"]

        if actual == expected_intent:
            ok(f"({elapsed:.1f}s) '{msg}' -> {actual} (conf={confidence:.2f}) [{desc}]")
            passed += 1
        else:
            fail(f"({elapsed:.1f}s) '{msg}' -> {actual} (esperado {expected_intent}, conf={confidence:.2f}) [{desc}]")
            failed += 1

    print(f"\n  Intent parsing: {passed}/{passed+failed} pasaron")
    return passed, failed


async def test_rag_responses(ai: AIHandler, kb: KnowledgeBase):
    """Test 3: Respuestas RAG con documentación."""
    header("TEST 3: RAG Responses")

    passed = 0
    failed = 0

    for query, expected_words, desc in RAG_TESTS:
        results = kb.search(query, top_k=4, min_score=0.08)

        if not results:
            fail(f"Sin chunks para '{query}' [{desc}]")
            failed += 1
            continue

        chunks = [r.chunk.text for r in results]
        sources = [f"{r.chunk.source_file}({r.score:.2f})" for r in results]

        t0 = time.time()
        answer = await ai.chat_with_context(query, chunks)
        elapsed = time.time() - t0

        found = [w for w in expected_words if contains_word(answer, w)]
        missing = [w for w in expected_words if not contains_word(answer, w)]

        if len(found) >= len(expected_words) // 2 + 1:  # mayoría
            ok(f"({elapsed:.1f}s) '{query}' [{desc}]")
            print(f"         Fuentes: {', '.join(sources)}")
            print(f"         Palabras OK: {found}")
            if missing:
                warn(f"         Faltaron: {missing}")
            passed += 1
        else:
            fail(f"({elapsed:.1f}s) '{query}' [{desc}]")
            print(f"         Respuesta: {answer[:150]}...")
            print(f"         Encontradas: {found} | Faltaron: {missing}")
            failed += 1

    print(f"\n  RAG responses: {passed}/{passed+failed} pasaron")
    return passed, failed


async def test_no_hallucinations(ai: AIHandler, kb: KnowledgeBase):
    """Test 4: Verificar que el LLM NO inventa información."""
    header("TEST 4: Anti-Hallucination")

    passed = 0
    failed = 0

    for query, forbidden_words, desc in RAG_HALLUCINATION_TESTS:
        results = kb.search(query, top_k=4, min_score=0.08)
        if not results:
            warn(f"Sin chunks para '{query}', skip")
            continue

        chunks = [r.chunk.text for r in results]
        answer = await ai.chat_with_context(query, chunks)
        hallucinations = [w for w in forbidden_words if contains_word(answer, w)]

        if not hallucinations:
            ok(f"'{query}' -> sin alucinaciones [{desc}]")
            passed += 1
        else:
            fail(f"'{query}' -> ALUCINA: {hallucinations} [{desc}]")
            print(f"         Respuesta: {answer[:200]}...")
            failed += 1

    print(f"\n  Anti-hallucination: {passed}/{passed+failed} pasaron")
    return passed, failed


# ─── Main ─────────────────────────────────────────────────────────────

async def main():
    # Detectar backend
    backend = "groq"
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        backend = sys.argv[2] if len(sys.argv) > 2 else "groq"

    if backend == "groq" and not GROQ_API_KEY:
        print(f"{RED}Error: GROQ_API_KEY no configurada en .env{RESET}")
        sys.exit(1)

    intent_model = os.getenv("INTENT_MODEL", "llama-3.1-8b-instant")
    chat_model = os.getenv("CHAT_MODEL", "openai/gpt-oss-20b")

    print(f"{BOLD}Backend: {backend}{RESET}")
    print(f"Intent model: {intent_model}")
    print(f"Chat model:   {chat_model}")
    print(f"Embeddings:   {OLLAMA_EMBED_MODEL} (Ollama @ {OLLAMA_URL})")

    # Inicializar
    ai = AIHandler(
        llm_backend=backend,
        ollama_base_url=OLLAMA_URL,
        ollama_model=OLLAMA_MODEL,
        groq_api_key=GROQ_API_KEY,
        groq_model=GROQ_MODEL,
        intent_model=intent_model,
        chat_model=chat_model,
    )

    # Test 1: Knowledge Base
    kb = await test_knowledge_base()
    if not kb:
        print(f"\n{RED}Abortando: Knowledge Base no disponible{RESET}")
        return

    # Test 2: Intent Parsing
    intent_passed, intent_failed = await test_intent_parsing(ai)

    # Test 3: RAG Responses
    rag_passed, rag_failed = await test_rag_responses(ai, kb)

    # Test 4: Anti-Hallucination
    hall_passed, hall_failed = await test_no_hallucinations(ai, kb)

    # Resumen
    total_passed = intent_passed + rag_passed + hall_passed
    total_failed = intent_failed + rag_failed + hall_failed
    total = total_passed + total_failed

    header("RESUMEN")
    print(f"  Total: {total_passed}/{total} pasaron")
    print(f"  Intent parsing: {intent_passed}/{intent_passed+intent_failed}")
    print(f"  RAG responses:  {rag_passed}/{rag_passed+rag_failed}")
    print(f"  Anti-hallucination: {hall_passed}/{hall_passed+hall_failed}")

    if total_failed == 0:
        print(f"\n  {GREEN}{BOLD}ALL TESTS PASSED{RESET}")
    else:
        print(f"\n  {RED}{BOLD}{total_failed} TESTS FAILED{RESET}")

    await ai.close()


if __name__ == "__main__":
    asyncio.run(main())
