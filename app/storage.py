"""Сховище завантажених аудіофайлів зустрічей (Фаза 1).

Поки локальна ФС (`settings.storage_dir`, у контейнері — named volume). Пізніше за тим самим
інтерфейсом можна підкласти S3/MinIO. Файли кладемо під підкаталог проєкту: <storage>/<project_id>/.
"""
from __future__ import annotations

import os
import uuid

from fastapi import UploadFile


def save_upload(upload: UploadFile, project_id: str, storage_dir: str,
                max_bytes: int) -> tuple[str, int]:
    """Стрімом записує файл; обриває й чистить, якщо перевищує max_bytes.
    Повертає (шлях, розмір_байт). Кидає ValueError, якщо завеликий."""
    project_dir = os.path.join(storage_dir, project_id)
    os.makedirs(project_dir, exist_ok=True)
    ext = os.path.splitext(upload.filename or "")[1].lower()
    dest = os.path.join(project_dir, f"{uuid.uuid4().hex}{ext}")

    size = 0
    with open(dest, "wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                os.remove(dest)
                raise ValueError(f"файл завеликий (>{max_bytes // (1024 * 1024)} MB)")
            out.write(chunk)
    return dest, size
