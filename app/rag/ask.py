"""answer_question() — Phase 5 retrieval: питання -> grounded відповідь із памʼяті проєкту.

Потік: embed query (bge-m3) -> hybrid search (Qdrant, namespace=project_id) -> cross-encoder
rerank (bge-reranker-v2-m3) -> top-k у grounded LLM-промпт -> відповідь із цитатами [#N] + ABSTENTION.

embedder/store/reranker — host-only інстанси (передає ask_worker/CLI). LLM-виклик torch-free
(urllib до Ollama / OpenAI), тож сам цей модуль НЕ тягне torch на верхньому рівні. Ізоляція
проєкту форсована store.search (інжектить project_id-фільтр) — той самий чокпойнт, що в Phase 4.
"""
from __future__ import annotations

import json
import urllib.request

from qdrant_client import models as qm

from app.config import settings

ABSTAIN_TEXT = "У памʼяті проєкту це не зафіксовано."


def _build_prompt(question: str, ctx_lines: list[str]) -> str:
    ctx = "\n".join(ctx_lines)
    return f"""Ти — асистент памʼяті проєкту. Відповідай на питання ВИКЛЮЧНО на основі наведених
фрагментів — це репліки з транскриптів зустрічей цього проєкту.

Питання: {question}

Фрагменти памʼяті (кожен: [#N] (зустріч · дата · спікер): текст):
{ctx}

ПРАВИЛА (суворо):
1. Спирайся ЛИШЕ на фрагменти вище. НЕ вигадуй фактів, імен, чисел, дат.
2. Після кожного твердження вкажи джерело у форматі [#N].
3. ABSTENTION: якщо у фрагментах НЕМАЄ відповіді — поверни РІВНО: "{ABSTAIN_TEXT}" і більше нічого.
4. Відповідай УКРАЇНСЬКОЮ, стисло (1–4 речення).

Відповідь:"""


def _gen_local(prompt: str, model: str, timeout: int = 300) -> str:
    body = json.dumps({
        "model": model, "prompt": prompt, "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(f"{settings.ollama_host}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return (json.loads(r.read().decode("utf-8")).get("response") or "").strip()


def _gen_cloud(prompt: str, model: str, timeout: int = 120) -> str:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY не задано — хмарний режим недоступний")
    body = json.dumps({
        "model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {settings.openai_api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data["choices"][0]["message"]["content"] or "").strip()


def _generate(prompt: str, engine: str) -> str:
    kind, _, model = (engine or "").partition(":")
    if kind == "cloud":
        return _gen_cloud(prompt, model or settings.summary_model_cloud)
    return _gen_local(prompt, model or settings.ask_model)


def answer_question(
    project_id: str, question: str, *, embedder, store, reranker, engine: str | None = None,
) -> dict:
    """Питання -> {answer, citations[], abstained, engine}. Ізоляція форсована store.search."""
    engine = engine or f"local:{settings.ask_model}"

    eq = embedder.encode_query(question)
    sparse = (
        qm.SparseVector(indices=eq.sparse_indices, values=eq.sparse_values)
        if eq.sparse_indices else None
    )
    points = store.search(project_id, eq.dense, sparse, limit=settings.ask_search_limit)
    if not points:
        return {"answer": ABSTAIN_TEXT, "citations": [], "abstained": True, "engine": engine}

    passages = [(p.payload or {}).get("text", "") for p in points]
    ranked = reranker.rerank(question, passages, top_k=settings.ask_top_k)

    ctx_lines: list[str] = []
    cites: list[dict] = []
    for n, (idx, score) in enumerate(ranked, 1):
        pl = points[idx].payload or {}
        ctx_lines.append(
            f"[#{n}] ({pl.get('title', '?')} · {pl.get('date', '?')} · {pl.get('speaker', '?')}): "
            f"{pl.get('text', '')}"
        )
        cites.append({
            "n": n,
            "meeting_id": pl.get("meeting_id"),
            "title": pl.get("title"),
            "date": pl.get("date"),
            "speaker": pl.get("speaker"),
            "start": pl.get("start"),
            "end": pl.get("end"),
            "score": round(float(score), 3),
            "text": (pl.get("text") or "")[:500],
        })

    answer = _generate(_build_prompt(question, ctx_lines), engine).strip()
    # Нормалізуємо детект абстенції (модель могла додати/прибрати крапку).
    abstained = answer.rstrip(".").strip().lower() == ABSTAIN_TEXT.rstrip(".").lower()
    return {
        "answer": answer,
        "citations": [] if abstained else cites,
        "abstained": abstained,
        "engine": engine,
    }
