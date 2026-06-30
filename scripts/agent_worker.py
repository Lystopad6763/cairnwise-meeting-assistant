"""Agent-воркер (Phase 6): Redis-черга -> ReAct-агент -> запропоновані дії у Postgres.

BRPOP cairnwise:agent -> AgentRun(pending) -> run_agent (ReAct: search_memory + list_entities ->
propose) -> ProposedAction(proposed) на HITL-апрув. embedder+reranker на CPU (як ask_worker), щоб
GPU лишався під Ollama. Чому host: torch (embed/rerank) + host-Ollama (:11434).

Запуск:  .\.venv\Scripts\python scripts\agent_worker.py
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, ROOT)

from _env import load_env  # noqa: E402
load_env()

from app.config import settings                       # noqa: E402
from app.db import SessionLocal, init_db              # noqa: E402
from app.jobs import AGENT_QUEUE, get_redis           # noqa: E402
from app.models import AgentRun                        # noqa: E402

POLL_TIMEOUT = 5


def process_job(run_id: str, *, embedder, store, reranker) -> None:
    from app.rag.agent import run_agent

    db = SessionLocal()
    try:
        run = db.get(AgentRun, run_id)
        if run is None:
            print(f"  [skip] agent run {run_id} не знайдено")
            return
        print(f"  agent goal=«{run.goal[:60]}» · project={run.project_id} · engine={run.engine}")
        t0 = time.perf_counter()
        res = run_agent(
            run.project_id, run.goal,
            embedder=embedder, store=store, reranker=reranker, db=db,
            engine=run.engine, meeting_id=run.meeting_id,
        )
        dt = time.perf_counter() - t0
        run.n_proposed = res["n_proposed"]
        run.trace = res["trace"]
        run.status = "ready"
        run.error = None
        db.commit()
        print(f"  OK  {run.n_proposed} proposed · {dt:.1f}s -> status=ready")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        r = db.get(AgentRun, run_id)
        if r is not None:
            r.status = "failed"
            r.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        print(f"  FAIL {run_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        db.close()


def main() -> int:
    init_db()
    from app.rag.embedder import Embedder
    from app.rag.reranker import Reranker
    from app.rag.vector_store import VectorStore

    embedder = Embedder(device="cpu")
    reranker = Reranker(device=settings.reranker_device)
    store = VectorStore()

    r = get_redis()
    print(f"Agent-воркер готовий · embed=cpu · reranker={settings.reranker_device} · черга={AGENT_QUEUE}")
    print("чекаю на задачі (Ctrl+C — вихід) ...")
    try:
        while True:
            item = r.brpop(AGENT_QUEUE, timeout=POLL_TIMEOUT)
            if item is None:
                continue
            _, run_id = item
            print(f"\n[{time.strftime('%H:%M:%S')}] job agent={run_id}")
            process_job(run_id, embedder=embedder, store=store, reranker=reranker)
    except KeyboardInterrupt:
        print("\nзупинено (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
