"""
RAG Handler - Knowledge Base con TF-IDF
========================================
Carga documentos Markdown, los divide en chunks por headings,
y permite buscar fragmentos relevantes usando TF-IDF + cosine similarity.
"""
import os
import re
import glob
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


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
    Carga, indexa y busca en documentos Markdown usando TF-IDF.

    Uso:
        kb = KnowledgeBase("/path/to/knowledge_base")
        count = kb.load()
        results = kb.search("como configuro la bengala?")
    """

    def __init__(self, kb_dir: str, max_chunk_chars: int = 2000):
        self.kb_dir = kb_dir
        self.max_chunk_chars = max_chunk_chars
        self.chunks: List[DocumentChunk] = []
        self._vectorizer: Optional[TfidfVectorizer] = None
        self._tfidf_matrix = None

    def load(self) -> int:
        """
        Carga todos los .md del directorio, los divide en chunks
        por headings (##) y construye el índice TF-IDF.

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

        self._build_index()
        logger.info("📚 Knowledge Base cargada: %d chunks de %d archivos", len(self.chunks), len(md_files))
        return len(self.chunks)

    def search(self, query: str, top_k: int = 3, min_score: float = 0.15) -> List[SearchResult]:
        """
        Busca chunks relevantes para la query usando TF-IDF cosine similarity.

        Args:
            query: Texto de búsqueda.
            top_k: Máximo de resultados a retornar.
            min_score: Score mínimo para incluir un resultado.

        Returns:
            Lista de SearchResult ordenados por relevancia.
        """
        if not self.chunks or self._tfidf_matrix is None:
            return []

        query_vec = self._vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # Obtener índices ordenados por score descendente
        ranked_indices = scores.argsort()[::-1]

        results = []
        for idx in ranked_indices[:top_k]:
            score = float(scores[idx])
            if score < min_score:
                break
            results.append(SearchResult(
                chunk=self.chunks[idx],
                score=score,
            ))

        return results

    def reload(self) -> int:
        """Recarga la knowledge base desde disco."""
        logger.info("📚 Recargando Knowledge Base...")
        return self.load()

    def _split_by_headings(self, content: str, filename: str) -> List[DocumentChunk]:
        """Divide contenido Markdown en chunks por headings ## y ###."""
        chunks = []
        # Separar por headings de nivel 2 (##)
        sections = re.split(r'^(#{1,3}\s+.+)$', content, flags=re.MULTILINE)

        current_heading = filename.replace(".md", "").lstrip("0123456789_")
        current_text = ""

        for part in sections:
            part = part.strip()
            if not part:
                continue

            if re.match(r'^#{1,3}\s+', part):
                # Guardar chunk anterior si tiene contenido
                if current_text.strip():
                    for chunk in self._split_large_chunk(current_text.strip(), filename, current_heading):
                        chunks.append(chunk)
                # Nuevo heading
                current_heading = re.sub(r'^#{1,3}\s+', '', part).strip()
                current_text = ""
            else:
                current_text += "\n" + part

        # Último chunk
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
                chunks.append(DocumentChunk(
                    text=current.strip(),
                    source_file=filename,
                    heading=heading,
                ))
                current = para
            else:
                current += "\n\n" + para if current else para

        if current.strip():
            chunks.append(DocumentChunk(
                text=current.strip(),
                source_file=filename,
                heading=heading,
            ))

        return chunks

    def _build_index(self):
        """Construye el índice TF-IDF sobre todos los chunks."""
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
