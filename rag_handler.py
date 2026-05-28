"""
RAG Handler - Knowledge Base con Embeddings (Ollama) o TF-IDF (fallback)
=========================================================================
Carga documentos Markdown, los divide en chunks por headings,
y permite buscar fragmentos relevantes usando embeddings semánticos
o TF-IDF como fallback.
"""
import os
import re
import glob
import logging
import unicodedata
import numpy as np
from dataclasses import dataclass
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

# Palabras que indican que el usuario tiene un problema (no solo quiere saber cómo usar algo)
TROUBLESHOOTING_KEYWORDS = (
    "problema", "problemas", "error", "errores", "falla", "fallas", "fallo",
    "no funciona", "no prende", "no enciende", "no responde", "no detecta",
    "no conecta", "no sirve", "dejo de", "dejo de funcionar", "se cayo",
    "se desconecto", "se congelo", "se traba", "se bloquea", "se reinicia",
    "offline", "desconectado", "caido", "averiado", "roto", "defectuoso",
    "no me deja", "no puedo", "ayuda", "solucion", "solucionar", "reparar",
    "me sale", "me aparece", "no llega", "no reconoce",
)

TROUBLESHOOTING_FILES = ("13_solucion_problemas.md", "14_faq.md")
TROUBLESHOOTING_BOOST = 0.12  # Suma al score de chunks de troubleshooting

# Boost cuando la query contiene un token distintivo del filename de un doc.
# Tokens cortos (len < 5) se ignoran para evitar matches ruidosos ("los", "que", "de", "app").
FILENAME_TOKEN_BOOST = 0.10
FILENAME_TOKEN_MIN_LEN = 5


def _is_troubleshooting_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in TROUBLESHOOTING_KEYWORDS)


# URL patterns: protocolo, dominio.tld/path, t.me, www.foo, bit.ly, etc.
# Cubre los casos comunes que llegan al bot por accidente (links pegados).
_URL_RE = re.compile(
    r"""
    (?:https?://|ftp://)\S+            # protocolo + resto hasta espacio
    | www\.\S+                          # www. + resto
    | t\.me/\S+                         # t.me/ + resto
    | bit\.ly/\S+                       # bit.ly/ + resto
    | \b\w+\.(?:com|org|net|io|me|click|app|ai|co|dev)(?:/\S*)?\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def looks_like_url_only(text: str) -> bool:
    """True si el mensaje es esencialmente una URL pegada (no una pregunta).

    Devolvemos True solo si despues de quitar la(s) URL(s) queda muy poco
    texto util — asi no rechazamos preguntas legitimas tipo
    "vi en https://x.com/algo, como hago Y?".
    """
    if not text:
        return False
    s = text.strip()
    if not s:
        return False
    # Quitar URLs detectadas y ver si sobra algo significativo.
    leftover = _URL_RE.sub("", s).strip()
    # Quita signos sueltos y emojis basicos.
    leftover_alnum = re.sub(r"[^\w]", "", leftover, flags=re.UNICODE)
    # Si el residuo alfa es < 4 chars Y el original contenia al menos una URL,
    # tratamos el input como "solo link".
    return bool(_URL_RE.search(s)) and len(leftover_alnum) < 4


def _normalize_for_match(text: str) -> str:
    """Minúsculas sin acentos."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _stem_es(token: str) -> str:
    """Quita plurales en espanol (-es/-s) para unir usuario/usuarios,
    permiso/permisos. Heuristico simple; no es un stemmer completo."""
    if len(token) > 5 and token.endswith("es"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s"):
        return token[:-1]
    return token


def _clean_doc_title(filename: str) -> str:
    """Filename -> titulo legible. Ej: '12_usuarios_permisos.md' -> 'usuarios permisos'."""
    return filename.replace(".md", "").lstrip("0123456789_").replace("_", " ")


@dataclass
class DocumentChunk:
    """Un fragmento de documentación indexado."""
    text: str
    source_file: str
    heading: str


@dataclass
class SearchResult:
    """Resultado de búsqueda con score de relevancia."""
    chunk: DocumentChunk
    score: float


class KnowledgeBase:
    """
    Carga, indexa y busca en documentos Markdown.

    Soporta dos backends de búsqueda:
    - Embeddings via Ollama (semántico, mejor calidad)
    - TF-IDF via scikit-learn (fallback, keyword-based)

    Uso:
        kb = KnowledgeBase("/path/to/knowledge_base")
        count = kb.load()
        results = kb.search("como configuro la bengala?")
    """

    def __init__(
        self,
        kb_dir: str,
        max_chunk_chars: int = 2000,
        ollama_base_url: str = "http://localhost:11434",
        embed_model: str = "nomic-embed-text",
        use_embeddings: bool = True,
    ):
        self.kb_dir = kb_dir
        self.max_chunk_chars = max_chunk_chars
        self.chunks: List[DocumentChunk] = []

        # Embeddings config
        self._ollama_url = ollama_base_url.rstrip("/")
        self._embed_model = embed_model
        self._use_embeddings = use_embeddings
        self._embeddings: Optional[np.ndarray] = None

        # TF-IDF fallback
        self._vectorizer = None
        self._tfidf_matrix = None

        # Precomputado en load(): file -> set de tokens >=MIN_LEN (normalizados+stem).
        self._file_tokens: dict = {}

    def load(self) -> int:
        """
        Carga todos los .md del directorio, los divide en chunks
        y construye el índice (embeddings o TF-IDF).

        Returns:
            Número de chunks indexados.
        """
        self.chunks = []

        if not os.path.isdir(self.kb_dir):
            logger.warning("📚 Directorio knowledge_base no encontrado: %s", self.kb_dir)
            return 0

        md_files = sorted(glob.glob(os.path.join(self.kb_dir, "*.md")))
        if not md_files:
            logger.warning("📚 No se encontraron archivos .md en %s", self.kb_dir)
            return 0

        self._file_tokens = {}
        for filepath in md_files:
            filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                chunks = self._split_by_headings(content, filename)
                self.chunks.extend(chunks)
                self._file_tokens[filename] = {
                    _stem_es(_normalize_for_match(t))
                    for t in _clean_doc_title(filename).split()
                    if len(t) >= FILENAME_TOKEN_MIN_LEN
                }
            except Exception as e:
                logger.error("📚 Error leyendo %s: %s", filename, e)

        if not self.chunks:
            logger.warning("📚 No se generaron chunks de los documentos")
            return 0

        # Intentar embeddings, fallback a TF-IDF
        if self._use_embeddings:
            try:
                self._build_embeddings_index()
                logger.info(
                    "📚 Knowledge Base cargada: %d chunks de %d archivos (embeddings: %s)",
                    len(self.chunks), len(md_files), self._embed_model,
                )
                return len(self.chunks)
            except Exception as e:
                logger.warning("📚 Embeddings no disponibles (%s), usando TF-IDF como fallback", e)
                self._use_embeddings = False

        self._build_tfidf_index()
        logger.info(
            "📚 Knowledge Base cargada: %d chunks de %d archivos (TF-IDF fallback)",
            len(self.chunks), len(md_files),
        )
        return len(self.chunks)

    def search(self, query: str, top_k: int = 4, min_score: float = 0.08) -> List[SearchResult]:
        """
        Busca chunks relevantes para la query.

        Args:
            query: Texto de búsqueda.
            top_k: Máximo de resultados a retornar.
            min_score: Score mínimo para incluir un resultado.

        Returns:
            Lista de SearchResult ordenados por relevancia.
        """
        if not self.chunks:
            return []

        if self._use_embeddings and self._embeddings is not None:
            return self._search_embeddings(query, top_k, min_score)
        elif self._tfidf_matrix is not None:
            return self._search_tfidf(query, top_k, min_score)
        return []

    def reload(self) -> int:
        """Recarga la knowledge base desde disco."""
        logger.info("📚 Recargando Knowledge Base...")
        return self.load()

    # ------------------------------------------------------------------
    # Embeddings (Ollama)
    # ------------------------------------------------------------------

    def _get_embedding(self, text: str) -> np.ndarray:
        """Obtiene embedding de un texto via Ollama API (síncrono)."""
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self._ollama_url}/api/embeddings",
                json={"model": self._embed_model, "prompt": text},
            )
            response.raise_for_status()
            return np.array(response.json()["embedding"], dtype=np.float32)

    @staticmethod
    def _chunk_index_text(chunk: "DocumentChunk") -> str:
        """Texto para construir el indice. Incluye filename tokens
        (ej. 'permisos') que de otro modo no entrarian al vector.
        Este texto NO se pasa al LLM — el LLM solo ve chunk.text."""
        return f"{_clean_doc_title(chunk.source_file)}\n{chunk.heading}\n{chunk.text}"

    def _build_embeddings_index(self):
        """Genera embeddings para todos los chunks."""
        logger.info("📚 Generando embeddings para %d chunks...", len(self.chunks))
        embeddings = []
        for i, chunk in enumerate(self.chunks):
            text = self._chunk_index_text(chunk)
            emb = self._get_embedding(text)
            embeddings.append(emb)
            if (i + 1) % 20 == 0:
                logger.debug("📚 Embeddings: %d/%d", i + 1, len(self.chunks))

        self._embeddings = np.stack(embeddings)
        # Normalizar para cosine similarity
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self._embeddings = self._embeddings / norms
        logger.info("📚 Embeddings generados: %d vectores de dim %d", *self._embeddings.shape)

    def _apply_boosts(self, query: str, scores: np.ndarray) -> None:
        """Aplica boosts in-place sobre el vector de scores: troubleshooting
        (cuando la query indica un problema) y filename-match (cuando un
        token distintivo del nombre del doc aparece en la query)."""
        is_trouble = _is_troubleshooting_query(query)
        filename_matches = self._matched_files_for_query(query)
        if not is_trouble and not filename_matches:
            return
        for i, chunk in enumerate(self.chunks):
            if is_trouble and chunk.source_file in TROUBLESHOOTING_FILES:
                scores[i] += TROUBLESHOOTING_BOOST
            if chunk.source_file in filename_matches:
                scores[i] += FILENAME_TOKEN_BOOST

    # Cuando un archivo gana filename-match (ej. query "horarios" -> 09_horarios.md),
    # garantizamos al menos N chunks de ese archivo en el top_k. Sin esto, un archivo
    # con multiples secciones complementarias (ej. "...desde Telegram" vs "...desde la App")
    # puede entregar solo una al LLM y la respuesta sale parcial/incorrecta.
    GUARANTEED_CHUNKS_PER_MATCHED_FILE = 2

    def _matched_files_for_query(self, query: str) -> set:
        if not query:
            return set()
        q_tokens = {
            _stem_es(t) for t in re.findall(r"\w+", _normalize_for_match(query))
        }
        return {f for f, tokens in self._file_tokens.items() if tokens & q_tokens}

    def _rank_and_filter(
        self,
        scores: np.ndarray,
        top_k: int,
        min_score: float,
        query: str = "",
    ) -> List[SearchResult]:
        sorted_idx = scores.argsort()[::-1].tolist()

        # Pasada 1: top_k normal por score.
        selected: List[int] = []
        for idx in sorted_idx:
            if len(selected) >= top_k:
                break
            if scores[idx] < min_score:
                break
            selected.append(idx)

        # Pasada 2: garantizar diversidad por archivo cuando hay filename-match.
        matched_files = self._matched_files_for_query(query)
        if matched_files:
            for f in matched_files:
                current = sum(1 for i in selected if self.chunks[i].source_file == f)
                if current >= self.GUARANTEED_CHUNKS_PER_MATCHED_FILE:
                    continue
                for cand_idx in sorted_idx:
                    if cand_idx in selected:
                        continue
                    if self.chunks[cand_idx].source_file != f:
                        continue
                    if scores[cand_idx] < min_score:
                        break
                    # Reemplazar el chunk con peor score que NO sea de un matched_file.
                    replace_pos = None
                    for i in range(len(selected) - 1, -1, -1):
                        if self.chunks[selected[i]].source_file not in matched_files:
                            replace_pos = i
                            break
                    if replace_pos is None:
                        break
                    selected[replace_pos] = cand_idx
                    current += 1
                    if current >= self.GUARANTEED_CHUNKS_PER_MATCHED_FILE:
                        break
            # Reordenar por score real para devolverlos en orden descendente.
            selected.sort(key=lambda i: -scores[i])

        return [
            SearchResult(chunk=self.chunks[i], score=float(scores[i]))
            for i in selected
        ]

    def _search_embeddings(self, query: str, top_k: int, min_score: float) -> List[SearchResult]:
        query_emb = self._get_embedding(query)
        query_emb = query_emb / (np.linalg.norm(query_emb) or 1)
        scores = (self._embeddings @ query_emb).copy()
        self._apply_boosts(query, scores)
        return self._rank_and_filter(scores, top_k, min_score, query=query)

    # ------------------------------------------------------------------
    # TF-IDF (fallback)
    # ------------------------------------------------------------------

    def _build_tfidf_index(self):
        """Construye el índice TF-IDF sobre todos los chunks."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [self._chunk_index_text(c) for c in self.chunks]
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=5000,
            sublinear_tf=True,
            strip_accents="unicode",
            lowercase=True,
            token_pattern=r"(?u)\b\w[\w']+\b",
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(texts)
        logger.debug("📚 Índice TF-IDF construido: %d features", len(self._vectorizer.get_feature_names_out()))

    def _search_tfidf(self, query: str, top_k: int, min_score: float) -> List[SearchResult]:
        from sklearn.metrics.pairwise import cosine_similarity
        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten().copy()
        self._apply_boosts(query, scores)
        return self._rank_and_filter(scores, top_k, min_score, query=query)

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _split_by_headings(self, content: str, filename: str) -> List[DocumentChunk]:
        """Divide contenido Markdown en chunks por headings ## y ###."""
        chunks = []
        sections = re.split(r'^(#{1,3}\s+.+)$', content, flags=re.MULTILINE)

        current_heading = filename.replace(".md", "").lstrip("0123456789_")
        current_text = ""

        for part in sections:
            part = part.strip()
            if not part:
                continue

            if re.match(r'^#{1,3}\s+', part):
                if current_text.strip():
                    for chunk in self._split_large_chunk(current_text.strip(), filename, current_heading):
                        chunks.append(chunk)
                current_heading = re.sub(r'^#{1,3}\s+', '', part).strip()
                current_text = ""
            else:
                current_text += "\n" + part

        if current_text.strip():
            for chunk in self._split_large_chunk(current_text.strip(), filename, current_heading):
                chunks.append(chunk)

        return chunks

    def _split_large_chunk(self, text: str, filename: str, heading: str) -> List[DocumentChunk]:
        """Si un chunk excede max_chunk_chars, lo divide por párrafos."""
        if len(text) <= self.max_chunk_chars:
            return [DocumentChunk(text=text, source_file=filename, heading=heading)]

        chunks = []
        paragraphs = text.split("\n\n")
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 2 > self.max_chunk_chars and current:
                chunks.append(DocumentChunk(text=current.strip(), source_file=filename, heading=heading))
                current = para
            else:
                current += "\n\n" + para if current else para

        if current.strip():
            chunks.append(DocumentChunk(text=current.strip(), source_file=filename, heading=heading))

        return chunks
