"""Мінімальний лоадер .env (без зовнішніх залежностей) + фікс HF-кешу на Windows.

Читає <корінь проєкту>/.env у os.environ (не перетираючи вже задані змінні) і вимикає
symlink-режим huggingface_hub (інакше — WinError 1314 на Windows без Developer Mode).
"""
from __future__ import annotations

import os
import sys

# Прибрати лише ПОПЕРЕДЖЕННЯ про symlink (саме вимкнення робить _patch_hf_symlinks нижче).
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _ensure_venv_bin_on_path() -> None:
    """whisperx/pyannote шелять у ГОЛИЙ `ffmpeg` (decode аудіо). У нас ffmpeg.exe лежить у
    .venv\\Scripts поряд із python.exe — але ПРЯМИЙ запуск `python.exe scripts\\worker.py`
    (без активації venv) НЕ додає Scripts у PATH, тож процес його не знаходить -> WinError 2.
    Додаємо каталог інтерпретатора в PATH, щоб STT працював незалежно від PATH оболонки,
    яка запустила процес (інструмент-раннер, cron, сервіс тощо)."""
    bindir = os.path.dirname(os.path.abspath(sys.executable))
    if bindir and bindir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")


_ensure_venv_bin_on_path()  # best-effort на імпорті (до whisperx.load_audio)


def _patch_hf_symlinks() -> None:
    """huggingface_hub 0.36.x НЕ має env-важеля для вимкнення symlink, а його авто-детект
    `are_symlinks_supported()` подеколи хибно вважає symlink доступним і падає з WinError 1314
    на Windows без Developer Mode/адмін-прав. Примусово кажемо «symlink не підтримується» ->
    HF КОПІЮЄ файли в кеш (трохи більше місця, зате надійно). Замінюємо функцію в модулі —
    `_create_symlink` бере її як global, тож copy-гілка спрацює всюди (download_model,
    snapshot_download, diarization тощо)."""
    if os.name != "nt":
        return
    try:
        from huggingface_hub import file_download
        file_download.are_symlinks_supported = lambda *a, **k: False
    except Exception:
        pass


_patch_hf_symlinks()  # best-effort, якщо hub уже імпортовано до нас


def load_env() -> None:
    _patch_hf_symlinks()           # на випадок, якщо hub імпортували вже після старту скрипта
    _ensure_venv_bin_on_path()     # ffmpeg із .venv\Scripts -> PATH
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:   # реальна env-змінна має пріоритет
                os.environ[key] = val
