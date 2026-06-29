"""scripts/check_isolation.py — доказ namespace-ізоляції per-project памʼяті (Phase 4).

Самодостатній, TORCH-FREE, ідемпотентний. НЕ потребує GPU / embedder / реальних транскриптів:
будує СИНТЕТИЧНІ dense+sparse-вектори для двох фейкових проєктів-тенантів (A, B) і доводить, що
жоден read / count / search / delete не перетинає межу `project_id`. Чистить за собою.

Це виконуваний доказ твердження з vector_store.py: «кожен read/count/delete бере project_id як
ОБОВʼЯЗКОВИЙ аргумент і інжектить Filter(project_id) — немає жодного query-шляху без нього».

Exit 0 = PASS, 1 = FAIL.

Запуск (інфра піднята через docker compose; .env дає QDRANT_URL):
    .\.venv\Scripts\python scripts\check_isolation.py
    .\.venv\Scripts\python scripts\check_isolation.py --real f8ffed98-...   # + реальний проєкт (count>0)
"""
from __future__ import annotations

import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")   # cyrillic-safe на cp1251-консолі Windows
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))   # _env
sys.path.insert(0, ROOT)                             # пакет app

from _env import load_env  # noqa: E402
load_env()                 # .env -> QDRANT_URL (наш Qdrant на :6543, не дефолтний :6333)

from app.rag.schema import EMBED_DIM, Chunk, EmbeddedChunk   # noqa: E402  (torch-free)
from app.rag.vector_store import VectorStore                  # noqa: E402  (torch-free)
from qdrant_client import models as qm                        # noqa: E402

# Синтетичні тенанти — імена з підкресленнями, щоб НІКОЛИ не збігтися з реальним slug/uuid проєкту.
PA, PB = "__isol_test_A__", "__isol_test_B__"
MA, MB = "isol-meeting-A", "isol-meeting-B"
N_A, N_B = 5, 3


def _unit(idx: int) -> list[float]:
    """Орт-вектор розмірності EMBED_DIM з 1.0 на позиції idx (cosine-розрізнювані напрями)."""
    v = [0.0] * EMBED_DIM
    v[idx] = 1.0
    return v


def _mk_chunks(n: int, dense_idx: int, sparse_idx: int, speaker: str) -> list[EmbeddedChunk]:
    """n синтетичних EmbeddedChunk зі спільним напрямом dense (= орт dense_idx)."""
    out: list[EmbeddedChunk] = []
    for i in range(n):
        ch = Chunk(
            chunk_index=i,
            text=f"{speaker}: synthetic isolation chunk {i}",
            speaker=speaker, speakers=[speaker],
            start=float(i), end=float(i) + 1.0,
            seg_start=i + 1, seg_end=i + 1,
        )
        out.append(EmbeddedChunk(
            chunk=ch, dense=_unit(dense_idx),
            sparse_indices=[sparse_idx], sparse_values=[1.0],
        ))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real", help="реальний project_id -> додатково перевірити, що count>0")
    args = ap.parse_args()

    store = VectorStore()
    store.ensure_collection()

    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if not cond:
            fails.append(msg)

    # --- ідемпотентний клінап ПЕРЕД стартом (на випадок обірваного попереднього run) ---
    store.delete_meeting(PA, MA)
    store.delete_meeting(PB, MB)

    # --- засів: проєкт A (напрям dense[0]) та B (напрям dense[1]) ---
    store.upsert_chunks(PA, MA, "2026-01-01", "Isolation A", _mk_chunks(N_A, 0, 0, "Speaker A"))
    store.upsert_chunks(PB, MB, "2026-01-01", "Isolation B", _mk_chunks(N_B, 1, 1, "Speaker B"))

    print("counts (чокпойнт _project_filter):")
    cA, cB = store.count(PA), store.count(PB)
    check(cA == N_A, f"count(A) == {N_A} (got {cA})")
    check(cB == N_B, f"count(B) == {N_B} (got {cB})")
    check(store.count("__no_such_project__") == 0, "count(неіснуючий проєкт) == 0")

    print("search-ізоляція (один і той самий запит, різні фільтри):")
    qa = _unit(0)                                   # вектор-запит «у напрямі A»
    sa = qm.SparseVector(indices=[0], values=[1.0])
    resA = store.search(PA, qa, sa, limit=10)
    check(len(resA) == N_A, f"search(filter=A) -> {N_A} точок (got {len(resA)})")
    check(all(p.payload.get("project_id") == PA for p in resA),
          "усі результати search(filter=A) мають project_id == A")

    # ТОЙ САМИЙ вектор-запит, але фільтр B: точки A ідеально матчать запит, проте НЕ мають
    # просочитися — фільтр project_id їх відрізає на рівні prefetch.
    resB = store.search(PB, qa, sa, limit=10)
    check(all(p.payload.get("project_id") == PB for p in resB),
          "search(filter=B) тим самим вектором НЕ повертає жодної точки A")
    check(all(p.payload.get("meeting_id") != MA for p in resB),
          "жодна точка зустрічі A не просочилася у проєкт B")

    print("ізоляція видалення:")
    store.delete_meeting(PA, MA)                    # прибрати лише A
    check(store.count(PA) == 0, "після delete(A): count(A) == 0")
    check(store.count(PB) == N_B, f"після delete(A): count(B) досі {N_B} (видалення не зачепило B)")

    if args.real:
        cr = store.count(args.real)
        print(f"реальний проєкт {args.real}:")
        check(cr > 0, f"count(real) > 0 (got {cr})")

    # --- фінальний клінап ---
    store.delete_meeting(PB, MB)

    print()
    if fails:
        print(f"ISOLATION CHECK: FAIL — {len(fails)} проблем(и)")
        return 1
    print("ISOLATION CHECK: PASS — жоден read/count/search/delete не перетнув межу project_id ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
