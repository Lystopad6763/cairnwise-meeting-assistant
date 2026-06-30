"""Cross-encoder reranker над BAAI/bge-reranker-v2-m3. HOST ONLY (torch + FlagEmbedding).

Phase 5 retrieval: гібридний пошук дає кандидатів, reranker переоцінює (query, passage) парами і
ранжує точніше за bi-encoder. За замовчуванням на **CPU** — на query-time це 1 запит × ~20 пасажів,
CPU встигає, і GPU лишається під Ollama (не тримаємо дві моделі на 4GB одночасно).

Не імпортувати в CPU-only API-контейнері — лише host (ask_worker). Lazy-завантаження на першому rerank.
"""
from __future__ import annotations

from app.config import settings


class Reranker:
    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self.model_name = model_name or settings.reranker_model
        self.device = (device or settings.reranker_device or "cpu").lower()
        self._model = None  # lazy

    def _ensure(self):
        if self._model is None:
            from FlagEmbedding import FlagReranker  # host-only, lazy
            try:
                self._model = FlagReranker(
                    self.model_name, use_fp16=(self.device == "cuda"), devices=self.device,
                )
            except TypeError:
                # старіші FlagEmbedding без `devices` — фолбек
                self._model = FlagReranker(self.model_name, use_fp16=(self.device == "cuda"))
        return self._model

    def rerank(self, query: str, passages: list[str], top_k: int | None = None) -> list[tuple[int, float]]:
        """(query, passages) -> [(оригінальний_індекс, score)] відсортовано за спаданням score.

        score нормалізований у [0,1] (sigmoid). top_k обрізає вихід."""
        if not passages:
            return []
        model = self._ensure()
        scores = model.compute_score([[query, p] for p in passages], normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        ranked = sorted(enumerate(float(s) for s in scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k] if top_k else ranked
