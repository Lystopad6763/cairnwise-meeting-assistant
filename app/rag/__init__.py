"""Пакет per-project RAG-памʼяті (Phase 4: ingestion; Phase 5: retrieval).

Re-export TORCH-FREE поверхні, щоб `import app.rag` лишався імпортовним у CPU-only API-контейнері.
Embedder (host-only, torch + FlagEmbedding) НАВМИСНО не re-export-иться на топ-рівні пакета —
імпортуй його явно: `from app.rag.embedder import Embedder`.
"""
from __future__ import annotations

from app.rag.chunker import chunk_segments
from app.rag.schema import (
    COLLECTION,
    DENSE,
    EMBED_DIM,
    SPARSE,
    Chunk,
    EmbeddedChunk,
    IngestResult,
    chunk_point_id,
)
from app.rag.service import ingest_meeting
from app.rag.vector_store import VectorStore

__all__ = [
    "Chunk",
    "EmbeddedChunk",
    "IngestResult",
    "COLLECTION",
    "DENSE",
    "SPARSE",
    "EMBED_DIM",
    "chunk_point_id",
    "chunk_segments",
    "VectorStore",
    "ingest_meeting",
]
