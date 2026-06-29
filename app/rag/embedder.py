"""Embedder над BAAI/bge-m3 (dense 1024 + learned sparse в одному forward-pass). HOST ONLY.

ЦЕ ЄДИНИЙ модуль пакета app.rag, що імпортує torch + FlagEmbedding. Він НЕ повинен імпортуватись
усередині CPU-only API-контейнера. Phase 5 (retrieval) переюзає цей самий код на хості: query-вектор
виробляє цей Embedder і передає у vector_store.search(project_id, dense, sparse, ...).

Lazy singleton: модель вантажиться з ЛОКАЛЬНОГО HF-кешу (offline; _env.load_env() уже пропатчив
HF-symlink) при ПЕРШОМУ encode, не на __init__. Device резолвиться через scripts/transcribe._cuda()
(переюз, не реімплементація) — імпорт усередині __init__, НЕ на верхньому рівні модуля, щоб лишити
вирішення device host-side.

bge-m3 fp16 ~2.3GB НЕ співмешкає з Whisper+pyannote на 4GB GPU — саме тому ingest окремий процес
(STT-модель вивантажена першою). Для одночасного запуску постав EMBED_DEVICE=cpu. На OOM зменшуй
EMBED_BATCH_SIZE 8->4->2 (дзеркалить STT_BATCH_SIZE guidance).
"""
from __future__ import annotations

from app.config import settings
from app.rag.schema import EMBED_DIM, Chunk, EmbeddedChunk


def _resolve_device(device: str | None) -> str:
    """'auto' -> 'cuda' якщо доступна, інакше 'cpu'. Будь-що інше повертаємо як є."""
    dev = (device or settings.embed_device or "auto").lower()
    if dev != "auto":
        return dev
    # Переюз scripts/transcribe._cuda() — імпорт ТУТ (host-side), не на топ-рівні модуля.
    try:
        import os
        import sys
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "scripts",
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from transcribe import _cuda  # noqa: PLC0415
        return "cuda" if _cuda() else "cpu"
    except Exception:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"


class Embedder:
    """Lazy-обгортка над FlagEmbedding.BGEM3FlagModel. Модель вантажиться на першому encode."""

    def __init__(
        self,
        model_name: str | None = None,
        device: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.model_name = model_name or settings.embed_model
        self.device = _resolve_device(device)
        self.batch_size = int(batch_size if batch_size is not None else settings.embed_batch_size)
        self._model = None  # lazy на першому encode

    @property
    def dim(self) -> int:
        return EMBED_DIM

    def _ensure_model(self):
        if self._model is None:
            from FlagEmbedding import BGEM3FlagModel  # host-only, lazy
            self._model = BGEM3FlagModel(
                self.model_name,
                use_fp16=(self.device == "cuda"),   # fp16 лише на GPU
                devices=self.device,
            )
        return self._model

    def _encode_raw(self, texts: list[str]):
        model = self._ensure_model()
        return model.encode(
            texts,
            batch_size=self.batch_size,
            max_length=1024,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )

    @staticmethod
    def _sparse(weights: dict) -> tuple[list[int], list[float]]:
        """bge-m3 lexical_weights {token_id: weight} -> (indices[int], values[float]) у порядку."""
        items = list((weights or {}).items())
        indices = [int(k) for k, _ in items]
        values = [float(v) for _, v in items]
        return indices, values

    def encode_chunks(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        """Список Chunk -> список EmbeddedChunk (dense + sparse, той самий порядок)."""
        if not chunks:
            return []
        out = self._encode_raw([c.text for c in chunks])
        dense = out["dense_vecs"]
        lexical = out["lexical_weights"]
        embedded: list[EmbeddedChunk] = []
        for c, vec, lw in zip(chunks, dense, lexical):
            idx, val = self._sparse(lw)
            embedded.append(EmbeddedChunk(
                chunk=c,
                dense=[float(x) for x in vec],
                sparse_indices=idx,
                sparse_values=val,
            ))
        return embedded

    def encode_query(self, text: str) -> EmbeddedChunk:
        """Один рядок запиту -> EmbeddedChunk (chunk=None). Використовує Phase 5 / check_isolation."""
        out = self._encode_raw([text])
        idx, val = self._sparse(out["lexical_weights"][0])
        return EmbeddedChunk(
            chunk=None,                                 # для query чанк не потрібен
            dense=[float(x) for x in out["dense_vecs"][0]],
            sparse_indices=idx,
            sparse_values=val,
        )
