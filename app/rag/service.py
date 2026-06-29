"""ingest_meeting() — оркестрація Phase 4: Transcript -> chunks(Qdrant) + entities(Postgres).

Ідемпотентно (delete-then-write в ОБОХ сховищах + детермінований uuid5-id точок). Кидає на
відсутні дані. Порядок (vectors -> postgres -> status) робить так, що mid-crash лишає
status != ingested, а повторний запуск self-heal (обидва delete-и проганяються знову).

Цей модуль ТОРКАЄТЬСЯ app.rag.embedder (host-only) ЛИШЕ ліниво — коли embedder не передали і
треба збудувати свій. Воркер/CLI передають довгоживучі інстанси, тож import torch не тягнеться
у read-path. extract_entities — torch-free (Ollama через HTTP).
"""
from __future__ import annotations

import sys

from app.config import settings
from app.rag.chunker import chunk_segments
from app.rag.entities import extract_entities
from app.rag.schema import IngestResult


def ingest_meeting(meeting_id: str, *, embedder=None, store=None, db=None) -> IngestResult:
    """Транскрипт зустрічі -> per-project RAG-памʼять. Ідемпотентно.

    embedder/store/db: воркер передає довгоживучі інстанси; CLI/one-shot лишає None -> будуємо.
    """
    from app.db import SessionLocal
    from app.models import ActionItem, Decision, Meeting, MeetingStatus, Transcript

    owns_db = db is None
    if owns_db:
        db = SessionLocal()
    if store is None:
        from app.rag.vector_store import VectorStore
        store = VectorStore()
    if embedder is None:
        from app.rag.embedder import Embedder   # host-only, ліниво
        embedder = Embedder()

    try:
        meeting = db.get(Meeting, meeting_id)
        tr = (
            db.query(Transcript).filter(Transcript.meeting_id == meeting_id).one_or_none()
            if meeting is not None else None
        )
        if meeting is None or tr is None:
            raise ValueError(f"meeting/transcript missing for {meeting_id} (transcribed?)")

        project_id = meeting.project_id
        date = meeting.created_at.date().isoformat() if meeting.created_at else ""

        # status=ingesting — робить вікно обробки спостережуваним (зустріч у роботі).
        meeting.status = MeetingStatus.ingesting
        meeting.error = None
        db.commit()

        store.ensure_collection()

        segments = list(tr.segments)
        chunks = chunk_segments(
            segments,
            max_chars=settings.chunk_max_chars,
            overlap_turns=settings.chunk_overlap_turns,
            max_gap_s=settings.chunk_max_gap_s,
        )
        embedded = embedder.encode_chunks(chunks)

        # 7) QDRANT idempotency: delete-by-(project_id,meeting_id) ПЕРЕД upsert (без orphan-ів).
        store.delete_meeting(project_id, meeting_id)
        n_chunks = store.upsert_chunks(project_id, meeting_id, date, meeting.title, embedded)

        # 8) POSTGRES idempotency (одна транзакція): delete старих сутностей -> flush -> insert нових.
        db.query(ActionItem).filter_by(meeting_id=meeting_id).delete()
        db.query(Decision).filter_by(meeting_id=meeting_id).delete()
        db.flush()

        result = extract_entities(segments, date=date, model=settings.entity_model)
        conf = float(result.get("confidence") or 0.0)

        action_items = result.get("action_items") or []
        decisions = result.get("decisions") or []
        for ai in action_items:
            db.add(ActionItem(
                project_id=project_id,
                meeting_id=meeting_id,
                owner=ai.get("owner"),
                task=str(ai.get("task") or ""),
                deadline=ai.get("deadline"),
                citations=list(ai.get("citations") or []),
                confidence=conf,
            ))
        for dec in decisions:
            db.add(Decision(
                project_id=project_id,
                meeting_id=meeting_id,
                decision=str(dec.get("decision") or ""),
                citations=list(dec.get("citations") or []),
                confidence=conf,
            ))

        # citation-аудит (grounding): зібрати [#N] поза діапазоном сегментів.
        from app.rag.entities import citation_audit
        _, invalid = citation_audit(result, len(segments))

        # 9) status=ingested -> commit (фіксуємо все одночасно).
        meeting.status = MeetingStatus.ingested
        db.commit()

        return IngestResult(
            meeting_id=meeting_id,
            project_id=project_id,
            n_chunks=n_chunks,
            n_action_items=len(action_items),
            n_decisions=len(decisions),
            confidence=conf,
            invalid_citations=list(invalid),
        )
    except Exception as exc:  # noqa: BLE001 — будь-яка помилка -> failed + error (worker pattern)
        db.rollback()
        try:
            m = db.get(Meeting, meeting_id)
            if m is not None:
                m.status = MeetingStatus.failed
                m.error = f"{type(exc).__name__}: {exc}"
                db.commit()
        except Exception as inner:  # noqa: BLE001
            print(f"  [ingest status-update failed] {inner}", file=sys.stderr)
        raise
    finally:
        if owns_db:
            db.close()
