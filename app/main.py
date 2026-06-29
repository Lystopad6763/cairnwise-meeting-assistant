"""Cairnwise API — Phase 0 скелет: /health (статус компонент) + CRUD проєктів.

Запуск (інфра вже піднята через docker compose):
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine, get_db, init_db
from app.jobs import enqueue_transcription
from app.models import ActionItem, Decision, Meeting, MeetingStatus, Project, Transcript
from app.storage import save_upload

ALLOWED_AUDIO = {".wav", ".mp4", ".m4a", ".mp3", ".webm", ".ogg", ".flac"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()          # створити таблиці, якщо ще нема
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# CORS — SPA (Vite dev на :5173) ходить до API (:8000) з ІНШОГО origin. Дозволяємо localhost-порти
# розробки (regex покриває будь-який порт). У проді SPA віддаватиметься з того ж origin -> CORS зайвий.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- health
def _check_postgres() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    try:
        import redis
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


def _check_qdrant() -> bool:
    try:
        from qdrant_client import QdrantClient
        QdrantClient(url=settings.qdrant_url, timeout=2).get_collections()
        return True
    except Exception:
        return False


@app.get("/health")
def health() -> dict:
    components = {
        "postgres": _check_postgres(),
        "redis": _check_redis(),
        "qdrant": _check_qdrant(),
    }
    return {
        "status": "ok" if all(components.values()) else "degraded",
        "app": settings.app_name,
        "components": components,
    }


# ---------------------------------------------------------------- projects
class ProjectIn(BaseModel):
    slug: str
    name: str
    description: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    slug: str
    name: str
    description: str | None
    created_at: datetime


@app.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectIn, db: Session = Depends(get_db)) -> Project:
    if db.scalar(select(Project).where(Project.slug == payload.slug)):
        raise HTTPException(status_code=409, detail=f"project slug '{payload.slug}' already exists")
    proj = Project(slug=payload.slug, name=payload.name, description=payload.description)
    db.add(proj)
    db.commit()
    db.refresh(proj)
    return proj


@app.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at)))


@app.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    proj = db.get(Project, project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="project not found")
    return proj


# ---------------------------------------------------------------- meetings (Фаза 1: capture)
import os  # noqa: E402


class MeetingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    title: str
    filename: str
    content_type: str | None
    size_bytes: int
    consent: bool
    status: MeetingStatus
    error: str | None = None
    created_at: datetime


class TranscriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    meeting_id: str
    language: str | None
    model: str
    diarizer: str | None
    glossary: bool
    num_speakers: int
    duration_s: float
    compute_secs: float | None
    segments: list[dict]
    created_at: datetime


@app.post("/projects/{project_id}/meetings", response_model=MeetingOut, status_code=201)
def upload_meeting(
    project_id: str,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    consent: bool = Form(False),
    db: Session = Depends(get_db),
) -> Meeting:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    # CONSENT-гейт: без згоди (учасників попереджено про запис) — не приймаємо. Legal-вимога.
    if not consent:
        raise HTTPException(status_code=400,
                            detail="consent required: учасники мають бути попереджені про запис")
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_AUDIO:
        raise HTTPException(status_code=415,
                            detail=f"непідтримуваний тип '{ext}'; дозволені: {sorted(ALLOWED_AUDIO)}")
    try:
        path, size = save_upload(file, project_id, settings.storage_dir,
                                 settings.max_upload_mb * 1024 * 1024)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))

    meeting = Meeting(
        project_id=project_id,
        title=title or (file.filename or "meeting"),
        filename=file.filename or "meeting",
        stored_path=path,
        content_type=file.content_type,
        size_bytes=size,
        consent=consent,
        status=MeetingStatus.uploaded,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    # Авто-постановка в чергу транскрипції (Фаза 2-3). Best-effort: якщо Redis недоступний —
    # зустріч лишається 'uploaded', її можна ретригернути через POST /meetings/{id}/transcribe.
    try:
        enqueue_transcription(meeting.id)
    except Exception as exc:  # noqa: BLE001
        print(f"[enqueue skipped] meeting={meeting.id}: {exc}")
    return meeting


@app.post("/meetings/{meeting_id}/transcribe", response_model=MeetingOut)
def trigger_transcription(meeting_id: str, db: Session = Depends(get_db)) -> Meeting:
    """(Ре)поставити зустріч у чергу транскрипції. Скидає error і повертає статус у 'uploaded';
    воркер підхопить і переведе у 'transcribing' -> 'transcribed'/'failed'."""
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    meeting.status = MeetingStatus.uploaded
    meeting.error = None
    db.commit()
    try:
        enqueue_transcription(meeting.id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"черга недоступна: {exc}")
    db.refresh(meeting)
    return meeting


@app.get("/meetings/{meeting_id}/transcript", response_model=TranscriptOut)
def get_transcript(meeting_id: str, db: Session = Depends(get_db)) -> Transcript:
    """Діаризований транскрипт зустрічі. 404 поки воркер не завершив (статус != transcribed)."""
    if db.get(Meeting, meeting_id) is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    tr = db.scalar(select(Transcript).where(Transcript.meeting_id == meeting_id))
    if tr is None:
        raise HTTPException(status_code=404, detail="транскрипт ще не готовий (див. status зустрічі)")
    return tr


@app.get("/projects/{project_id}/meetings", response_model=list[MeetingOut])
def list_meetings(project_id: str, db: Session = Depends(get_db)) -> list[Meeting]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    return list(db.scalars(
        select(Meeting).where(Meeting.project_id == project_id).order_by(Meeting.created_at)
    ))


@app.get("/meetings/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: str, db: Session = Depends(get_db)) -> Meeting:
    meeting = db.get(Meeting, meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    return meeting


# ---------------------------------------------------------------- memory stats (Фаза 4)
# Дешевий read-only погляд на per-project RAG-памʼять. TORCH-FREE: рахуємо чанки через
# VectorStore.count (qdrant-client уже в API-образі + у health-чеку), сутності — з Postgres.
# Жодного embedding тут немає (це host-only) — ендпойнт безпечний у CPU-only контейнері.
@app.get("/projects/{project_id}/memory")
def project_memory(project_id: str, db: Session = Depends(get_db)) -> dict:
    """Скільки чанків/сутностей у памʼяті проєкту. Чанки — через чокпойнт ізоляції
    (VectorStore.count інжектить project_id-фільтр); Qdrant-збій -> chunks=null, не 500."""
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    chunks: int | None
    try:
        from app.rag.vector_store import VectorStore  # torch-free; lazy щоб не чіпати на старті
        chunks = VectorStore().count(project_id)
    except Exception:  # noqa: BLE001 — Qdrant недоступний / колекції ще нема -> null, не помилка
        chunks = None

    action_items = (
        db.query(ActionItem).filter(ActionItem.project_id == project_id).count()
    )
    decisions = db.query(Decision).filter(Decision.project_id == project_id).count()
    ingested_meetings = (
        db.query(Meeting)
        .filter(Meeting.project_id == project_id, Meeting.status == MeetingStatus.ingested)
        .count()
    )
    return {
        "project_id": project_id,
        "chunks": chunks,                      # None якщо Qdrant недоступний
        "action_items": action_items,
        "decisions": decisions,
        "ingested_meetings": ingested_meetings,
    }
