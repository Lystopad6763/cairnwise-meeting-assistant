"""Qdrant VectorStore (Phase 4 запис + Phase 5 пошук). TORCH-FREE — лише qdrant-client.

Цей модуль безпечно імпортується в CPU-only API-контейнері (Phase 5 read-path): query-вектор
виробляє host-side Embedder і ПЕРЕДАЄ сюди.

ІЗОЛЯЦІЯ (диференціатор) — кожен read/count/delete бере project_id як ОБОВʼЯЗКОВИЙ аргумент і
інжектить Filter(must=[FieldCondition("project_id", MatchValue(project_id))]). Немає жодного
query-шляху без нього. is_tenant=True co-locates точки проєкту на диску; hnsw m=0 + payload_m=16
будує HNSW-граф per project_id. scripts/check_isolation.py це доводить.
"""
from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.config import settings
from app.rag.schema import DENSE, EMBED_DIM, SPARSE, EmbeddedChunk, chunk_point_id


def _project_filter(project_id: str) -> qm.Filter:
    """Чокпойнт ізоляції: жоден read/count/delete не йде без цього фільтра."""
    return qm.Filter(must=[
        qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id)),
    ])


def _meeting_filter(project_id: str, meeting_id: str) -> qm.Filter:
    return qm.Filter(must=[
        qm.FieldCondition(key="project_id", match=qm.MatchValue(value=project_id)),
        qm.FieldCondition(key="meeting_id", match=qm.MatchValue(value=meeting_id)),
    ])


def _payload(project_id: str, meeting_id: str, date: str, title: str, chunk) -> dict:
    return {
        "project_id": project_id,
        "meeting_id": meeting_id,
        "chunk_index": int(chunk.chunk_index),
        "speaker": chunk.speaker,
        "speakers": list(chunk.speakers),
        "start": float(chunk.start),
        "end": float(chunk.end),
        "date": date,                       # ISO YYYY-MM-DD
        "seg_start": int(chunk.seg_start),
        "seg_end": int(chunk.seg_end),
        "text": chunk.text,
        "title": title,
    }


class VectorStore:
    def __init__(self, client: QdrantClient | None = None, collection: str | None = None) -> None:
        self.client = client or QdrantClient(url=settings.qdrant_url)
        self.collection = collection or settings.qdrant_collection

    # ---------------------------------------------------------------- schema
    def ensure_collection(self) -> None:
        """Ідемпотентно. Якщо колекція є — лише гарантуємо payload-індекси; інакше створюємо."""
        if self.client.collection_exists(self.collection):
            self._ensure_indexes()
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
            },
            sparse_vectors_config={
                # Modifier.IDF -> Qdrant застосовує корпусний IDF до bge-m3 lexical weights
                # (BM25-еквівалент на query-time, Phase 5).
                SPARSE: qm.SparseVectorParams(modifier=qm.Modifier.IDF),
            },
            # m=0 + payload_m=16 -> HNSW-граф будується ПЕР-ТЕНАНТ (per project_id), а не глобально.
            hnsw_config=qm.HnswConfigDiff(m=0, payload_m=16),
        )
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        """Payload-індекси (ідемпотентно: кожен create обгорнуто try/except для re-run)."""
        # project_id -> tenant-індекс (co-location + per-tenant HNSW).
        try:
            self.client.create_payload_index(
                self.collection, "project_id",
                qm.KeywordIndexParams(type=qm.KeywordIndexType.KEYWORD, is_tenant=True),
            )
        except Exception:
            pass
        for field in ("meeting_id", "date", "speaker"):
            try:
                self.client.create_payload_index(
                    self.collection, field, qm.PayloadSchemaType.KEYWORD,
                )
            except Exception:
                pass

    # ---------------------------------------------------------------- write
    def upsert_chunks(
        self,
        project_id: str,
        meeting_id: str,
        date: str,
        title: str,
        embedded: list[EmbeddedChunk],
    ) -> int:
        """Записати чанки зустрічі. Детермінований uuid5-id -> upsert=replace, не append."""
        if not embedded:
            return 0
        points = [
            qm.PointStruct(
                id=chunk_point_id(meeting_id, ec.chunk.chunk_index),
                vector={
                    DENSE: ec.dense,
                    SPARSE: qm.SparseVector(indices=ec.sparse_indices, values=ec.sparse_values),
                },
                payload=_payload(project_id, meeting_id, date, title, ec.chunk),
            )
            for ec in embedded
        ]
        self.client.upsert(self.collection, points=points)
        return len(points)

    def delete_meeting(self, project_id: str, meeting_id: str) -> None:
        """Видалити всі точки зустрічі (idempotency: викликається ПЕРЕД upsert)."""
        self.client.delete(
            self.collection,
            points_selector=qm.FilterSelector(filter=_meeting_filter(project_id, meeting_id)),
        )

    # ---------------------------------------------------------------- read
    def count(self, project_id: str) -> int:
        """К-сть точок проєкту (через чокпойнт ізоляції)."""
        return self.client.count(
            self.collection, count_filter=_project_filter(project_id), exact=True,
        ).count

    def search(
        self,
        project_id: str,
        dense: list[float],
        sparse: qm.SparseVector | None = None,
        *,
        limit: int = 20,
        extra_filter: qm.Filter | None = None,
    ) -> list:
        """Гібридний пошук (Phase 5). ЗАВЖДИ інжектить _project_filter (чокпойнт ізоляції).

        Dense + sparse через два Prefetch, злиті FusionQuery(RRF). Якщо sparse=None — лише dense.
        extra_filter (recency/speaker, Phase 5) долучається через AND до project-фільтра.
        """
        proj = _project_filter(project_id)
        if extra_filter is not None:
            proj = qm.Filter(must=(proj.must or []) + (extra_filter.must or []))

        prefetch = [qm.Prefetch(query=dense, using=DENSE, limit=limit * 2, filter=proj)]
        if sparse is not None:
            prefetch.append(qm.Prefetch(query=sparse, using=SPARSE, limit=limit * 2, filter=proj))

        res = self.client.query_points(
            self.collection,
            prefetch=prefetch,
            query=qm.FusionQuery(fusion=qm.Fusion.RRF),
            limit=limit,
            with_payload=True,
            query_filter=proj,
        )
        return list(res.points)
