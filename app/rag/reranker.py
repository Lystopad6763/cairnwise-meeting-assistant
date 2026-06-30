"""Cross-encoder reranker над BAAI/bge-reranker-v2-m3. HOST ONLY (torch + transformers).

Phase 5 retrieval: гібридний пошук дає кандидатів, reranker переоцінює (query, passage) парами і
ранжує точніше за bi-encoder. За замовчуванням на **CPU** — на query-time це 1 запит × ~20 пасажів
у ОДНОМУ batched forward, CPU встигає, і GPU лишається під Ollama (не тримаємо дві моделі на 4GB).

ВАЖЛИВО: НЕ використовуємо FlagEmbedding.FlagReranker — він спавнить worker-процеси для
compute_score і ДЕДЛОЧИТЬСЯ на Windows (підтверджено: rerank висів >240с). Натомість прямий
transformers-форвард (AutoModelForSequenceClassification + sigmoid) — детермінований, без пулів.

Не імпортувати в CPU-only API-контейнері — лише host (ask_worker). Lazy-завантаження на першому rerank.
"""
from __future__ import annotations

from app.config import settings


class Reranker:
    def __init__(self, model_name: str | None = None, device: str | None = None) -> None:
        self.model_name = model_name or settings.reranker_model
        self.device = (device or settings.reranker_device or "cpu").lower()
        self._tok = None
        self._model = None  # lazy

    def _ensure(self) -> None:
        if self._model is None:
            import os
            # OFFLINE: якщо ваги не докачані — НЕ висіти на мережі, а швидко впасти (ask.py зловить
            # і відкотиться на порядок гібридного пошуку). Усі моделі мають бути попередньо в кеші.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            self._tok = AutoTokenizer.from_pretrained(self.model_name)
            model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
            if self.device == "cuda":
                model = model.half()
            self._model = model.to(self.device).eval()

    def rerank(self, query: str, passages: list[str], top_k: int | None = None) -> list[tuple[int, float]]:
        """(query, passages) -> [(оригінальний_індекс, score)] відсортовано за спаданням score.

        score = sigmoid(logit) у [0,1]. Один batched forward (без мультипроцесингу). top_k обрізає."""
        if not passages:
            return []
        import torch
        self._ensure()
        pairs = [[query, p or ""] for p in passages]
        with torch.no_grad():
            inputs = self._tok(
                pairs, padding=True, truncation=True, max_length=512, return_tensors="pt",
            ).to(self.device)
            logits = self._model(**inputs, return_dict=True).logits.view(-1).float()
            scores = torch.sigmoid(logits).cpu().tolist()
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k] if top_k else ranked
