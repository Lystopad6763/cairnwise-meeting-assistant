"""Конфіг застосунку — Pydantic settings із .env (наскрізний принцип: вибір через config).

URL-и за замовчуванням вказують на сервіси з docker-compose, прокинуті на localhost.
Коли API сам поїде в контейнер (Фаза 10) — переоприділиш host'и через .env.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Cairnwise"

    # Інфраструктура (docker-compose -> localhost)
    database_url: str = "postgresql+psycopg://cairnwise:cairnwise@localhost:5432/cairnwise"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    # Локальна LLM (Ollama) — на потім (Фаза 6)
    ollama_host: str = "http://localhost:11434"

    # Резюме (Агент-2, Фаза 7): рушій вибирається за приватністю зустрічі.
    #   local  -> Ollama (приватно, $0, нічого не покидає машину) — ДЕФОЛТ.
    #   cloud  -> OpenAI (краще резюме для «непублічних» зустрічей; лише ТЕКСТ, не аудіо).
    summary_model_local: str = "neural-chat"
    summary_model_cloud: str = "gpt-4o-mini"
    openai_api_key: str = ""                     # з .env; порожньо -> хмарний режим недоступний

    # Capture / сховище завантажених зустрічей (Фаза 1)
    storage_dir: str = "data/uploads"        # у контейнері перевизначається на /data/uploads
    max_upload_mb: int = 1024                 # ліміт розміру файлу зустрічі

    # STT-воркер (Фаза 2-3) — стек зафіксовано бенчмарком треку D
    whisper_model: str = "small"                            # 4 GB GPU -> лише small
    diarizer: str = "pyannote/speaker-diarization-3.1"
    use_glossary: bool = True                               # глосарій-prompt (тех-терміни)

    # RAG / ingestion (Фаза 4). Embedding-важке (torch/bge-m3) живе на ХОСТІ (.venv), не в API-образі.
    embed_model: str = "BAAI/bge-m3"            # dense(1024)+sparse в одній моделі
    embed_device: str = "auto"                  # auto -> cuda якщо є, інакше cpu (host)
    embed_batch_size: int = 8                    # 4 GB GPU; на CPU можна 16-32
    qdrant_collection: str = "cairnwise_memory"
    chunk_max_chars: int = 1100                  # ціль ~250-350 токенів вікна
    chunk_overlap_turns: int = 1                 # перекриття сусідніх вікон (репліки)
    chunk_max_gap_s: float = 45.0                # пауза > N сек -> межа теми (новий chunk)
    entity_model: str = "neural-chat"            # Ollama-модель витягання сутностей (reuse summarize)


settings = Settings()
