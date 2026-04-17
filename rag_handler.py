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


def _is_troubleshooting_query(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in TROUBLESHOOTING_KEYWORDS)


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

        for filepath in md_files:
            filename = os.path.basename(filepath)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                chunks = self._split_by_headings(content, filename)
                self.chunks.extend(chunks)
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

    def _build_embeddings_index(self):
        """Genera embeddings para todos los chunks."""
        logger.info("📚 Generando embeddings para %d chunks...", len(self.chunks))
        embeddings = []
        for i, chunk in enumerate(self.chunks):
            text = f"{chunk.heading}\n{chunk.text}"
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

    def _search_embeddings(self, query: str, top_k: int, min_score: float) -> List[SearchResult]:
        """Busca por cosine similarity sobre embeddings. Boost para troubleshooting."""
        query_emb = self._get_embedding(query)
        query_emb = query_emb / (np.linalg.norm(query_emb) or 1)

        scores = (self._embeddings @ query_emb).copy()
        if _is_troubleshooting_query(query):
            for i, chunk in enumerate(self.chunks):
                if chunk.source_file in TROUBLESHOOTING_FILES:
                    scores[i] += TROUBLESHOOTING_BOOST
        ranked_indices = scores.argsort()[::-1]

        results = []
        for idx in ranked_indices[:top_k]:
            score = float(scores[idx])
            if score < min_score:
                break
            results.append(SearchResult(chunk=self.chunks[idx], score=score))
        return results

    # ------------------------------------------------------------------
    # TF-IDF (fallback)
    # ------------------------------------------------------------------

    def _build_tfidf_index(self):
        """Construye el índice TF-IDF sobre todos los chunks."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [f"{c.heading}\n{c.text}" for c in self.chunks]
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
        """Busca por cosine similarity sobre TF-IDF. Boost para troubleshooting."""
        from sklearn.metrics.pairwise import cosine_similarity

        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten().copy()
        if _is_troubleshooting_query(query):
            for i, chunk in enumerate(self.chunks):
                if chunk.source_file in TROUBLESHOOTING_FILES:
                    scores[i] += TROUBLESHOOTING_BOOST
        ranked_indices = scores.argsort()[::-1]

        results = []
        for idx in ranked_indices[:top_k]:
            score = float(scores[idx])
            if score < min_score:
                break
            results.append(SearchResult(chunk=self.chunks[idx], score=score))
        return results

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
