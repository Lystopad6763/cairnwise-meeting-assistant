"""Summary-воркер (Агент-2, Фаза 7): Redis-черга -> grounded резюме у Postgres.

Дзеркало scripts/worker.py за топологією, але легше: НЕ потребує torch/GPU — лише HTTP до
Ollama (local) або OpenAI (cloud). Чому окремий host-процес, а не в API: (1) локальний рушій
ходить у host-Ollama (:11434), якого CPU-only API-контейнер не дістає через localhost;
(2) генерація триває хвилини — не можна тримати HTTP-запит.

Потік одного job:
  BRPOP meeting_id -> читаємо Summary(status=pending, engine) + Transcript ->
  застосовуємо relabel-підписи (резюме говорить ІМЕНАМИ, не «Speaker N») ->
  рушій за рядком engine: local:<model> (Ollama) / cloud:<model> (OpenAI) ->
  пишемо summary+сутності+confidence, status=ready/failed.

Запуск (інфра піднята; .env дає REDIS_URL/DATABASE_URL/OLLAMA_HOST/OPENAI_API_KEY):
    .\.venv\Scripts\python scripts\summary_worker.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))   # _env
sys.path.insert(0, ROOT)                             # пакет app

from _env import load_env  # noqa: E402
load_env()                 # .env -> REDIS_URL / DATABASE_URL / OLLAMA_HOST / OPENAI_API_KEY

from app.config import settings                                   # noqa: E402
from app.db import SessionLocal, init_db                          # noqa: E402
from app.jobs import SUMMARIZE_QUEUE, get_redis                   # noqa: E402
from app.models import Meeting, Summary, Transcript               # noqa: E402
from app.rag.entities import extract_entities, relabel_segments   # noqa: E402  (torch-free)

POLL_TIMEOUT = 5   # сек BRPOP — щоб реагувати на Ctrl+C


def _run_engine(engine: str, segments: list[dict], date: str) -> dict:
    """engine = 'local:<model>' | 'cloud:<model>' -> {summary, decisions, action_items, risks_blockers, confidence}."""
    kind, _, model = (engine or "").partition(":")
    if kind == "cloud":
        from app.rag.summarize_cloud import extract_entities_cloud   # ліниво (мережа OpenAI)
        return extract_entities_cloud(segments, date, model or None)
    return extract_entities(segments, date, model or None)           # local (Ollama)


def process_job(meeting_id: str) -> None:
    """Один job: (пере)генерувати резюме зустрічі. Винятки -> Summary.status=failed (воркер живе далі)."""
    db = SessionLocal()
    try:
        summ = db.query(Summary).filter(Summary.meeting_id == meeting_id).one_or_none()
        meeting = db.get(Meeting, meeting_id)
        tr = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).one_or_none()
        if meeting is None or tr is None:
            print(f"  [skip] meeting/transcript відсутній для {meeting_id}")
            if summ is not None:
                summ.status = "failed"
                summ.error = "meeting/transcript missing"
                db.commit()
            return
        if summ is None:   # API зазвичай створює рядок; підстрахуємось (напр. ручний enqueue)
            summ = Summary(meeting_id=meeting_id, project_id=meeting.project_id,
                           status="pending", engine=f"local:{settings.summary_model_local}")
            db.add(summ)
            db.commit()

        engine = summ.engine or f"local:{settings.summary_model_local}"
        date = meeting.created_at.date().isoformat() if meeting.created_at else ""
        # relabel: резюме має говорити іменами/ролями, а не «Speaker N»
        segments = relabel_segments(list(tr.segments), tr.speaker_labels or {})

        print(f"  summarizing «{meeting.title}» · engine={engine} · {len(segments)} сегментів")
        t0 = time.perf_counter()
        result = _run_engine(engine, segments, date)
        dt = time.perf_counter() - t0

        summ.summary = str(result.get("summary") or "")
        summ.action_items = result.get("action_items") or []
        summ.decisions = result.get("decisions") or []
        summ.risks = result.get("risks_blockers") or []
        summ.confidence = float(result.get("confidence") or 0.0)
        summ.status = "ready"
        summ.error = None
        db.commit()
        print(f"  OK  conf={summ.confidence:.2f} · {len(summ.action_items)} action-items · "
              f"{len(summ.decisions)} decisions · {len(summ.risks)} risks · {dt:.1f}s -> status=ready")
    except Exception as exc:  # noqa: BLE001 — job не валить воркер
        db.rollback()
        s = db.query(Summary).filter(Summary.meeting_id == meeting_id).one_or_none()
        if s is not None:
            s.status = "failed"
            s.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        print(f"  FAIL {meeting_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        db.close()


def main() -> int:
    init_db()   # таблиці/колонки на місці (ідемпотентно) — як у worker.py
    r = get_redis()
    print(f"Summary-воркер готовий · local={settings.summary_model_local} · "
          f"cloud={'on' if settings.openai_api_key else 'off'}({settings.summary_model_cloud}) · "
          f"черга={SUMMARIZE_QUEUE}")
    print("чекаю на задачі (Ctrl+C — вихід) ...")
    try:
        while True:
            item = r.brpop(SUMMARIZE_QUEUE, timeout=POLL_TIMEOUT)
            if item is None:
                continue
            _, meeting_id = item
            print(f"\n[{time.strftime('%H:%M:%S')}] job meeting={meeting_id}")
            process_job(meeting_id)
    except KeyboardInterrupt:
        print("\nзупинено (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
