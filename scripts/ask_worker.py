"""Ask-воркер (Phase 5 retrieval): Redis-черга -> grounded відповідь із памʼяті у Postgres.

BRPOP cairnwise:ask -> AskResult(pending) -> answer_question (embed bge-m3 + hybrid search +
rerank bge-reranker + grounded LLM з [#N] + abstention) -> пишемо answer/citations, status=ready.

embedder + reranker — на **CPU** (один запит за раз, CPU встигає), щоб GPU лишався під Ollama
(не тримаємо три моделі на 4GB). Чому host, а не API: torch (embed+rerank) + host-Ollama (:11434),
якого CPU-only контейнер не дістає.

Запуск (інфра піднята; .env дає REDIS_URL/DATABASE_URL/QDRANT_URL/OLLAMA_HOST/OPENAI_API_KEY):
    .\.venv\Scripts\python scripts\ask_worker.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))   # _env
sys.path.insert(0, ROOT)                             # пакет app

from _env import load_env  # noqa: E402
load_env()

from app.config import settings                       # noqa: E402
from app.db import SessionLocal, init_db              # noqa: E402
from app.jobs import ASK_QUEUE, get_redis            # noqa: E402
from app.models import AskResult                      # noqa: E402

POLL_TIMEOUT = 5


def process_job(ask_id: str, *, embedder, store, reranker) -> None:
    """Один Q&A-job. Винятки -> AskResult.status=failed (воркер живе далі)."""
    from app.rag.ask import answer_question

    db = SessionLocal()
    try:
        row = db.get(AskResult, ask_id)
        if row is None:
            print(f"  [skip] ask {ask_id} не знайдено")
            return
        print(f"  asking «{row.question[:60]}» · project={row.project_id} · engine={row.engine}")
        t0 = time.perf_counter()
        res = answer_question(
            row.project_id, row.question,
            embedder=embedder, store=store, reranker=reranker, engine=row.engine,
        )
        dt = time.perf_counter() - t0
        row.answer = res["answer"]
        row.citations = res["citations"]
        row.abstained = bool(res["abstained"])
        row.status = "ready"
        row.error = None
        db.commit()
        tag = "ABSTAIN" if row.abstained else f"{len(row.citations)} cites"
        print(f"  OK  {tag} · {dt:.1f}s -> status=ready")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        r = db.get(AskResult, ask_id)
        if r is not None:
            r.status = "failed"
            r.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        print(f"  FAIL {ask_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        db.close()


def main() -> int:
    init_db()
    # embed + rerank на CPU -> GPU вільний під Ollama. Вантажаться ліниво на першому запиті.
    from app.rag.embedder import Embedder
    from app.rag.reranker import Reranker
    from app.rag.vector_store import VectorStore

    embedder = Embedder(device="cpu")
    reranker = Reranker(device=settings.reranker_device)
    store = VectorStore()

    r = get_redis()
    print(f"Ask-воркер готовий · embed=cpu · reranker={settings.reranker_device} · "
          f"search_limit={settings.ask_search_limit} · top_k={settings.ask_top_k} · черга={ASK_QUEUE}")
    print("чекаю на задачі (Ctrl+C — вихід) ...")
    try:
        while True:
            item = r.brpop(ASK_QUEUE, timeout=POLL_TIMEOUT)
            if item is None:
                continue
            _, ask_id = item
            print(f"\n[{time.strftime('%H:%M:%S')}] job ask={ask_id}")
            process_job(ask_id, embedder=embedder, store=store, reranker=reranker)
    except KeyboardInterrupt:
        print("\nзупинено (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
