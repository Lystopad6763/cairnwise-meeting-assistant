"""HOST ingestion CLI (Фаза 4) — діаризований Transcript -> per-project RAG-памʼять.

One-shot / seed / debug-інструмент: дзеркало scripts/worker.py за топологією (ХОСТ, .venv,
torch/bge-m3 на GPU/CPU), але запускається руками для одного meeting / проєкту / усіх.
ЧЕРГовий аналог — scripts/ingest_worker.py (BRPOP cairnwise:ingest); обидва кличуть ОДИН
і той самий app.rag.service.ingest_meeting() — одне джерело правди оркестрації.

Цей файл НЕ реімплементує embedder/chunker/store/extraction — він ЛИШЕ:
  • резолвить цільові meeting_id (--meeting / --project <slug> / --all);
  • будує ОДИН довгоживучий Embedder + ОДИН VectorStore (модель вантажиться раз на весь run);
  • для кожної зустрічі кличе ingest_meeting(...) і друкує IngestResult;
  • robust try/except per meeting — одна впала зустріч НЕ валить пакет.
Уся важка робота (chunk -> bge-m3 dense+sparse -> Qdrant під namespace=project_id; entities
-> Postgres) живе у CORE-модулі app.rag. Ідемпотентність гарантує ingest_meeting()
(delete-by-(project_id,meeting_id) у Qdrant + детермінований uuid5-id; delete-by-meeting у
Postgres) — повторний запуск ПЕРЕЗАПИСУЄ, не дублює.

torch-важке (FlagEmbedding/bge-m3) живе на ХОСТІ, не в CPU-only API-образі — тому це host-CLI.
--dry-run лишається torch-free (тільки чанкер) -> працює навіть без FlagEmbedding у .venv.

Запуск (інфра вже піднята через docker compose up; .env дає DATABASE_URL/QDRANT_URL):
    .\.venv\Scripts\python scripts\ingest.py --meeting <id>
    .\.venv\Scripts\python scripts\ingest.py --project acme
    .\.venv\Scripts\python scripts\ingest.py --all
    .\.venv\Scripts\python scripts\ingest.py --all --dry-run          # лише чанки/лічильники
    .\.venv\Scripts\python scripts\ingest.py --project acme --device cpu --batch-size 4
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))   # _env / transcribe (device-резолв у Embedder)
sys.path.insert(0, ROOT)                             # пакет app

from _env import load_env  # noqa: E402
load_env()                 # .env (DATABASE_URL/QDRANT_URL/HF) + фікс HF-symlink ДО torch/FlagEmbedding

from app.config import settings                                       # noqa: E402
from app.db import SessionLocal, init_db                              # noqa: E402
from app.models import Meeting, MeetingStatus, Project, Transcript    # noqa: E402
# CORE — імпортуємо, НЕ реімплементуємо. chunk_segments/VectorStore/ingest_meeting торч-free;
# Embedder (torch+FlagEmbedding) тягнемо ЛИШЕ для не-dry-run шляху (lazy import у main()).
from app.rag import chunk_segments, ingest_meeting                    # noqa: E402


def _resolve_meeting_ids(db, args: argparse.Namespace) -> list[str]:
    """--meeting <id> | --project <slug> | --all -> список meeting_id для інжестії.

    Для --project/--all беремо лише зустрічі зі status=transcribed (готовий транскрипт). Для
    явного --meeting НЕ фільтруємо за статусом — даємо примусово (ре)інжестити конкретну зустріч
    (напр. застряглу в ingesting/failed), ingest_meeting() сам перевірить наявність транскрипту.
    """
    if args.meeting:
        return [args.meeting]

    if args.project:
        proj = (
            db.query(Project).filter(Project.slug == args.project).one_or_none()
        )
        if proj is None:
            raise SystemExit(f"проєкт зі slug='{args.project}' не знайдено")
        rows = (
            db.query(Meeting.id)
            .filter(Meeting.project_id == proj.id, Meeting.status == MeetingStatus.transcribed)
            .order_by(Meeting.created_at)
            .all()
        )
        return [r[0] for r in rows]

    # --all
    rows = (
        db.query(Meeting.id)
        .filter(Meeting.status == MeetingStatus.transcribed)
        .order_by(Meeting.created_at)
        .all()
    )
    return [r[0] for r in rows]


def _dry_run(db, meeting_ids: list[str]) -> int:
    """Чанкінг + лічильники, БЕЗ embedding / Qdrant / Postgres-записів (torch-free)."""
    print(f"--dry-run · {len(meeting_ids)} зустріч(і) · max_chars={settings.chunk_max_chars} · "
          f"overlap_turns={settings.chunk_overlap_turns} · max_gap_s={settings.chunk_max_gap_s}\n")
    failed = 0
    for mid in meeting_ids:
        try:
            tr = db.query(Transcript).filter(Transcript.meeting_id == mid).one_or_none()
            if tr is None:
                print(f"  {mid}: НЕМАЄ транскрипту (status transcribed?) — пропуск", file=sys.stderr)
                failed += 1
                continue
            segments = list(tr.segments)
            chunks = chunk_segments(
                segments,
                max_chars=settings.chunk_max_chars,
                overlap_turns=settings.chunk_overlap_turns,
                max_gap_s=settings.chunk_max_gap_s,
            )
            speakers = sorted({s.get("speaker", "Speaker ?") for s in segments})
            avg = (sum(len(c.text) for c in chunks) / len(chunks)) if chunks else 0.0
            print(f"  {mid}: {len(chunks)} chunks · {len(segments)} segments · "
                  f"~{avg:.0f} chars/chunk · speakers={', '.join(speakers)}")
        except Exception as exc:  # noqa: BLE001 — одна зустріч не валить весь dry-run
            print(f"  {mid}: FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
            failed += 1
    return 1 if failed else 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = ap.add_mutually_exclusive_group(required=True)
    target.add_argument("--meeting", help="інжестити ОДНУ зустріч за meeting_id")
    target.add_argument("--project", help="інжестити ВСІ transcribed-зустрічі проєкту (за slug)")
    target.add_argument("--all", action="store_true",
                        help="інжестити ВСІ transcribed-зустрічі всіх проєктів")
    ap.add_argument("--dry-run", action="store_true",
                    help="лише чанкінг + лічильники; БЕЗ embedding / Qdrant / Postgres (torch-free)")
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default=None,
                    help="override settings.embed_device для цього run (на OOM -> cpu)")
    ap.add_argument("--batch-size", type=int, default=None,
                    help="override settings.embed_batch_size (на OOM зменшуй 8->4->2)")
    args = ap.parse_args()

    load_env()      # ще раз, ідемпотентно (на випадок lazy-старту)
    init_db()       # таблиці/колонки на місці (ідемпотентно) — як у worker.py

    db = SessionLocal()
    try:
        meeting_ids = _resolve_meeting_ids(db, args)
        if not meeting_ids:
            scope = (f"проєкту '{args.project}'" if args.project
                     else "усіх проєктів" if args.all else f"зустрічі {args.meeting}")
            print(f"немає зустрічей для інжестії ({scope}; потрібен status=transcribed).")
            return 0

        # ---------- DRY-RUN: torch-free, без записів ----------
        if args.dry_run:
            return _dry_run(db, meeting_ids)

        # ---------- РЕАЛЬНА ІНЖЕСТІЯ ----------
        # Embedder тягне torch+FlagEmbedding — імпортуємо ЛИШЕ тут (не для dry-run / не на топ-рівні),
        # щоб модуль лишався імпортовним без FlagEmbedding у .venv доки не дійшло до embedding.
        from app.rag.embedder import Embedder
        from app.rag.vector_store import VectorStore

        device = args.device or settings.embed_device
        batch_size = args.batch_size if args.batch_size is not None else settings.embed_batch_size

        # ОДИН Embedder + ОДИН VectorStore на весь run -> модель bge-m3 вантажиться один раз
        # (lazy на першому encode), Qdrant-клієнт переюзається між зустрічами.
        emb = Embedder(device=device, batch_size=batch_size)
        store = VectorStore()
        store.ensure_collection()    # ідемпотентно (per-tenant HNSW + payload-індекси)

        print(f"ingest · {len(meeting_ids)} зустріч(і) · embed={settings.embed_model} · "
              f"device={emb.device} · batch={emb.batch_size} · collection={store.collection} · "
              f"entity_model={settings.entity_model}")
        print("(bge-m3 вантажиться на першому chunk; перша зустріч повільніша) ...\n")

        ok = 0
        failed = 0
        per_project: dict[str, dict[str, int]] = {}   # project_id -> агреговані лічильники
        t0 = time.perf_counter()

        for mid in meeting_ids:
            tm = time.perf_counter()
            print(f"[{time.strftime('%H:%M:%S')}] ingest meeting={mid}")
            try:
                # ingest_meeting сам: ensure_collection, status ingesting->ingested/failed,
                # delete-then-upsert у Qdrant, delete-then-insert сутностей у Postgres (idempotent).
                res = ingest_meeting(mid, embedder=emb, store=store, db=db)
                dt = time.perf_counter() - tm
                bad = (f" · invalid_citations={res.invalid_citations}"
                       if res.invalid_citations else "")
                print(f"  OK  project={res.project_id} · {res.n_chunks} chunks · "
                      f"{res.n_action_items} action-items · {res.n_decisions} decisions · "
                      f"confidence={res.confidence:.2f}{bad} · {dt:.1f}s")
                ok += 1
                agg = per_project.setdefault(
                    res.project_id, {"meetings": 0, "chunks": 0, "actions": 0, "decisions": 0}
                )
                agg["meetings"] += 1
                agg["chunks"] += res.n_chunks
                agg["actions"] += res.n_action_items
                agg["decisions"] += res.n_decisions
            except Exception as exc:  # noqa: BLE001 — одна зустріч не валить пакет (ingest_meeting
                # уже виставив status=failed + error у БД через свій except/rollback)
                print(f"  FAIL {mid}: {type(exc).__name__}: {exc}", file=sys.stderr)
                failed += 1

        # ---------- ПІДСУМОК ----------
        total = time.perf_counter() - t0
        print(f"\n=== ПІДСУМОК ({total:.1f}s) ===")
        print(f"  зустрічей: {ok} ok · {failed} fail · {len(meeting_ids)} усього")
        for pid, agg in sorted(per_project.items()):
            # store.count(project_id) — той самий чокпойнт ізоляції (Filter project_id), тож
            # звітна цифра = саме те, що бачить read-path. Best-effort: не валимо підсумок на мережі.
            try:
                total_pts = store.count(pid)
            except Exception:  # noqa: BLE001
                total_pts = -1
            qd = f"{total_pts} у Qdrant" if total_pts >= 0 else "Qdrant-лічильник недоступний"
            print(f"  project={pid}: +{agg['chunks']} chunks ({agg['meetings']} зустріч) · "
                  f"+{agg['actions']} action-items · +{agg['decisions']} decisions · {qd} (всього проєкт)")

        return 1 if failed else 0
    except KeyboardInterrupt:
        print("\nперервано (Ctrl+C).", file=sys.stderr)
        return 130
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
