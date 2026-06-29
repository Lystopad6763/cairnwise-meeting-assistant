"""STT-воркер (Фаза 2-3): Redis-черга -> діаризований транскрипт у Postgres.

Розподіл праці (наскрізний принцип «pluggable» + 4 GB GPU):
  API (контейнер, CPU-only) кладе meeting_id у чергу `cairnwise:transcribe`.
  Цей воркер крутиться на ХОСТІ (із GPU + whisperx), `BRPOP` забирає задачу, проганяє
  той самий стек, що зафіксував бенчмарк треку D (Whisper small + pyannote-3.1 + глосарій),
  і пише `Transcript` назад у БД, переводячи зустріч transcribing -> transcribed/failed.

Чому окремий процес, а не у запиті API: (1) STT важкий і довгий — не можна блокувати HTTP;
(2) torch/whisperx НЕ в образі API (тримаємо його ~250 MB); (3) GPU живе на хості.

Запуск (інфра вже піднята через docker compose up):
    .\.venv\Scripts\python scripts\worker.py
Стек і підключення — з .env (WHISPER_MODEL / DIARIZER / USE_GLOSSARY / REDIS_URL / DATABASE_URL).
"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))   # _env / transcribe / benchmark
sys.path.insert(0, ROOT)                             # пакет app

from _env import load_env  # noqa: E402
load_env()                 # HF_TOKEN + фікс HF-symlink на Windows ДО будь-якого імпорту whisperx

from app.config import settings                              # noqa: E402
from app.db import SessionLocal, init_db                     # noqa: E402
from app.jobs import TRANSCRIBE_QUEUE, get_redis             # noqa: E402
from app.models import Meeting, MeetingStatus, Transcript    # noqa: E402
from benchmark import DEFAULT_GLOSSARY                        # noqa: E402
from benchmark import diarize as run_diarize                 # noqa: E402
from benchmark import transcribe as run_asr                  # noqa: E402
from transcribe import _cuda, _normalize                     # noqa: E402

LANG = os.environ.get("STT_LANG", "uk")          # датасет україномовний; "" -> авто-визначення
BATCH_SIZE = int(os.environ.get("STT_BATCH_SIZE", "8"))   # на 4 GB GPU зменш до 4/2 проти OOM
POLL_TIMEOUT = 5                                  # сек BRPOP — щоб реагувати на Ctrl+C


def _host_audio_path(meeting: Meeting) -> str:
    """Шлях до аудіо з боку ХОСТА. stored_path у БД — контейнерний (/data/uploads/...),
    тож реконструюємо за розкладкою <storage>/<project_id>/<файл> (bind-mount показує той самий
    каталог). Фолбек — сам stored_path (якщо API ганяли локально, не в контейнері)."""
    storage = settings.storage_dir
    if not os.path.isabs(storage):
        storage = os.path.join(ROOT, storage)
    candidate = os.path.join(storage, meeting.project_id, os.path.basename(meeting.stored_path))
    if os.path.exists(candidate):
        return candidate
    if os.path.exists(meeting.stored_path):
        return meeting.stored_path
    raise FileNotFoundError(
        f"аудіо не знайдено: {candidate} (ні за stored_path={meeting.stored_path}). "
        f"Чи піднятий стек із bind-mount ./data/uploads?"
    )


def process_job(meeting_id: str, device: str, token: str) -> None:
    """Один цикл: зустріч -> транскрипт. Винятки ловить виклик (set status=failed)."""
    db = SessionLocal()
    try:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            print(f"  [skip] зустріч {meeting_id} не знайдено в БД")
            return
        meeting.status = MeetingStatus.transcribing
        meeting.error = None
        db.commit()
        print(f"  transcribing  «{meeting.title}»  ({meeting.filename})")

        audio = _host_audio_path(meeting)
        prompt = DEFAULT_GLOSSARY if settings.use_glossary else None

        # 1) ASR (Whisper) — чистий inference у asr_secs; 2) діаризація (pyannote) — diar_secs.
        result, asr_secs = run_asr(audio, settings.whisper_model, device, LANG, BATCH_SIZE, prompt)
        rlang = result.get("language", LANG)
        df, diar_secs = run_diarize(audio, settings.diarizer, token, device, None)

        # 3) злиття «слово -> спікер» + нормалізація SPEAKER_xx -> «Speaker N»
        import whisperx
        if df is not None and len(df):
            result = whisperx.assign_word_speakers(df, result)
        segments = _normalize(result["segments"])

        num_speakers = len({s["speaker"] for s in segments})
        duration_s = max((s["end"] for s in segments), default=0.0)

        # upsert: при ретригері перезаписуємо попередній транскрипт цієї зустрічі
        existing = (
            db.query(Transcript).filter(Transcript.meeting_id == meeting_id).one_or_none()
        )
        if existing is not None:
            db.delete(existing)
            db.flush()
        db.add(Transcript(
            meeting_id=meeting_id,
            segments=segments,
            language=rlang,
            model=settings.whisper_model,
            diarizer=settings.diarizer,
            glossary=bool(prompt),
            num_speakers=num_speakers,
            duration_s=round(float(duration_s), 2),
            compute_secs=round(float(asr_secs + diar_secs), 2),
        ))
        meeting.status = MeetingStatus.transcribed
        db.commit()
        print(f"  OK  {len(segments)} сегментів · {num_speakers} спікер(и) · "
              f"{duration_s:.0f}s аудіо · {asr_secs + diar_secs:.1f}s inference -> status=transcribed")
    except Exception as exc:  # noqa: BLE001 — будь-яка помилка job -> failed, воркер живе далі
        db.rollback()
        m = db.get(Meeting, meeting_id)
        if m is not None:
            m.status = MeetingStatus.failed
            m.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        print(f"  FAIL {meeting_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        db.close()


def main() -> int:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        print("ERROR: HF_TOKEN не заданий (.env) — діаризація неможлива.", file=sys.stderr)
        return 1
    device = "cuda" if _cuda() else "cpu"
    init_db()                       # переконатися, що таблиці/колонки на місці (ідемпотентно)
    r = get_redis()
    print(f"STT-воркер готовий · device={device} · whisper={settings.whisper_model} · "
          f"diar={settings.diarizer.replace('pyannote/speaker-diarization-', 'pa-')} · "
          f"glossary={'on' if settings.use_glossary else 'off'} · черга={TRANSCRIBE_QUEUE}")
    print("чекаю на задачі (Ctrl+C — вихід) ...")
    try:
        while True:
            item = r.brpop(TRANSCRIBE_QUEUE, timeout=POLL_TIMEOUT)
            if item is None:
                continue                      # таймаут — просто чекаємо далі
            _, meeting_id = item              # (ключ, значення) бо decode_responses=True
            print(f"\n[{time.strftime('%H:%M:%S')}] job meeting={meeting_id}")
            process_job(meeting_id, device, token)
    except KeyboardInterrupt:
        print("\nзупинено (Ctrl+C).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
