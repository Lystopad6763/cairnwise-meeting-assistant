"""ORM-моделі. Phase 0: PROJECT — first-class сутність (диференціатор: per-project памʼять).

Кожна зустріч/embedding/approval згодом прив'язується до project_id (Qdrant namespace,
metadata, ізоляція). Тут — лише сам проєкт; решта сутностей додаються у відповідних фазах.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)   # стабільний ключ (namespace)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MeetingStatus(str, enum.Enum):
    uploaded = "uploaded"          # файл прийнято (Фаза 1)
    transcribing = "transcribing"  # STT у роботі (Фаза 2-3)
    transcribed = "transcribed"    # діаризований транскрипт готовий
    ingesting = "ingesting"        # інжестія у per-project памʼять у роботі (Фаза 4)
    ingested = "ingested"          # чанки в Qdrant + сутності в Postgres готові (Фаза 4)
    failed = "failed"


class Meeting(Base):
    """Зустріч проєкту: завантажений/записаний аудіофайл + статус обробки.
    Прив'язана до project_id (per-project ізоляція). Транскрипт/сутності — у наступних фазах."""
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    filename: Mapped[str] = mapped_column(String(500))        # оригінальна назва
    stored_path: Mapped[str] = mapped_column(String(1000))    # шлях у сховищі
    content_type: Mapped[str | None] = mapped_column(String(120), default=None)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)  # учасників попереджено про запис
    status: Mapped[MeetingStatus] = mapped_column(default=MeetingStatus.uploaded)
    error: Mapped[str | None] = mapped_column(Text, default=None)  # причина status=failed (Фаза 2-3)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Transcript(Base):
    """Діаризований транскрипт зустрічі (результат Агента 1, Фаза 2-3). One-to-one з Meeting.

    `segments` — масив `[{speaker, start, end, text}]` (JSONB) — артефакт, який далі
    інжеститься в per-project памʼять (Фаза 4) і годує summary/агента (Фаза 6-7).
    Решта полів — провенанс (яка модель/діаризатор/глосарій дали цей результат)."""
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id"), unique=True, index=True
    )
    segments: Mapped[list[dict]] = mapped_column(JSONB)            # [{speaker,start,end,text}]
    language: Mapped[str | None] = mapped_column(String(8), default=None)
    model: Mapped[str] = mapped_column(String(64))                # whisper-модель (напр. small)
    diarizer: Mapped[str | None] = mapped_column(String(120), default=None)
    glossary: Mapped[bool] = mapped_column(Boolean, default=False)  # чи застосовано глосарій-prompt
    num_speakers: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)   # тривалість (макс. end сегмента)
    compute_secs: Mapped[float | None] = mapped_column(Float, default=None)  # чистий inference (ASR+diar)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ActionItem(Base):
    """Завдання, витягнуте з транскрипту (Агент-2, Фаза 4). Лінк на project_id + meeting_id.

    Грунтування: citations — ті самі [#N]-індекси сегментів, що й chunk.seg_start/seg_end ->
    знайдений чанк відображається назад на span транскрипту. confidence — meeting-level (з LLM)."""
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    owner: Mapped[str | None] = mapped_column(String(200), default=None)
    task: Mapped[str] = mapped_column(Text)
    deadline: Mapped[str | None] = mapped_column(String(10), default=None)  # "YYYY-MM-DD" / null (рядок: толерує вивід LLM)
    citations: Mapped[list[int]] = mapped_column(JSONB, default=list)        # [#N] індекси сегментів
    confidence: Mapped[float | None] = mapped_column(Float, default=None)    # meeting-level conf
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Decision(Base):
    """Рішення, ухвалене на зустрічі (Агент-2, Фаза 4). Лінк на project_id + meeting_id."""
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(String(36), ForeignKey("projects.id"), index=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id"), index=True)
    decision: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[int]] = mapped_column(JSONB, default=list)        # [#N] індекси сегментів
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
