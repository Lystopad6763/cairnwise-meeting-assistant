"""RAG-схема (Phase 4): константи + dataclass-и. TORCH-FREE.

Цей модуль — фундамент пакета app.rag і НЕ імпортує torch / FlagEmbedding / transformers,
тож його можна імпортувати всередині CPU-only API-контейнера (Phase 5/6 read-path).

Один словник «грунтування» на всю систему: seg_start/seg_end чанка вирівняні з [#N]-якорями
summarize.py / entities.py (1-based індекси сегментів), тож знайдений чанк відображається назад
на span транскрипту і на citations action_item/decision.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

COLLECTION = "cairnwise_memory"   # також доступне через settings.qdrant_collection (дефолт ідентичний)
DENSE = "dense"                   # імʼя dense-вектора у Qdrant
SPARSE = "sparse"                 # імʼя sparse-вектора у Qdrant
EMBED_DIM = 1024                  # розмірність dense у bge-m3


@dataclass(frozen=True)
class Chunk:
    """Одне вікно діаризованого транскрипту, готове до embedding.

    seg_start/seg_end — 1-based індекси ДЖЕРЕЛЬНИХ сегментів (включно), вирівняні з [#N].
    """
    chunk_index: int          # 0-based, стабільний у межах зустрічі
    text: str                 # speaker-prefixed рядки: "Speaker 2: ...\nSpeaker 1: ..."
    speaker: str              # домінантний спікер за к-стю символів, інакше "multi"
    speakers: list[str]       # усі різні спікери у вікні (відсортовані)
    start: float              # min start (s)
    end: float                # max end (s)
    seg_start: int            # 1-based ПЕРШИЙ джерельний сегмент (вирівняно з summarize [#N])
    seg_end: int              # 1-based ОСТАННІЙ джерельний сегмент (включно)


@dataclass(frozen=True)
class EmbeddedChunk:
    """Чанк + його dense/sparse-вектори від bge-m3 (host-side embedder)."""
    chunk: Chunk
    dense: list[float]                      # len == EMBED_DIM (1024)
    sparse_indices: list[int]               # bge-m3 lexical_weights token ids
    sparse_values: list[float]              # bge-m3 lexical_weights ваги (той самий порядок)


@dataclass
class IngestResult:
    """Підсумок одного ingest_meeting() — повертається CLI/воркеру для звіту."""
    meeting_id: str
    project_id: str
    n_chunks: int
    n_action_items: int
    n_decisions: int
    confidence: float
    invalid_citations: list[int] = field(default_factory=list)


def chunk_point_id(meeting_id: str, chunk_index: int) -> str:
    """Детермінований UUID5-id точки Qdrant -> повторний ingest ПЕРЕЗАПИСУЄ, не дублює.

    uuid5(NAMESPACE_URL, "{meeting_id}:{chunk_index}") стабільний між запусками, тож часткова
    переінжестія перезаписує точки in-place (upsert=replace), а не додає нові.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{meeting_id}:{chunk_index}"))
