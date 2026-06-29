"""Черга фонових задач через Redis-список (Фаза 2-3).

Розподіл праці: API (контейнер, БЕЗ torch) кладе meeting_id у чергу `LPUSH`; воркер на хості
(із GPU + whisperx) забирає `BRPOP`, транскрибує/діаризує і пише результат назад у Postgres.
Список Redis — мінімальна, але надійна черга: переживає рестарт API, не блокує upload-запит.

Ключ і зʼєднання визначені тут, щоб і API, і воркер (scripts/worker.py) брали ОДНЕ джерело правди.
"""
from __future__ import annotations

import redis

from app.config import settings

TRANSCRIBE_QUEUE = "cairnwise:transcribe"   # черга задач транскрипції (meeting_id як значення)
INGEST_QUEUE = "cairnwise:ingest"           # черга задач інжестії в RAG-памʼять (Фаза 4)
SUMMARIZE_QUEUE = "cairnwise:summarize"     # черга задач резюме (Агент-2, Фаза 7); host-воркер + Ollama


def get_redis() -> redis.Redis:
    """Клієнт Redis із конфігу (decode_responses -> працюємо рядками, не байтами)."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


def enqueue_transcription(meeting_id: str) -> None:
    """Поставити зустріч у чергу на транскрипцію (викликає API одразу після upload)."""
    get_redis().lpush(TRANSCRIBE_QUEUE, meeting_id)


def enqueue_ingestion(meeting_id: str) -> None:
    """Поставити зустріч у чергу на інжестію (STT-воркер після transcribed / POST .../ingest)."""
    get_redis().lpush(INGEST_QUEUE, meeting_id)


def enqueue_summary(meeting_id: str) -> None:
    """Поставити зустріч у чергу на резюме. Рушій (local/cloud) воркер читає з рядка Summary
    (API виставив status=pending + engine ПЕРЕД enqueue), тож у черзі — лише meeting_id."""
    get_redis().lpush(SUMMARIZE_QUEUE, meeting_id)
