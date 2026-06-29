"""Postgres через SQLAlchemy 2.0. Engine + сесії + Base + init_db().

Phase 0: таблиці створюємо через create_all() на старті (Alembic-міграції — пізніше,
коли схема стабілізується). Postgres (не SQLite) бо знадобиться для approvals/Text-to-SQL.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Базовий клас ORM-моделей."""


# Легкі ідемпотентні міграції до повноцінного Alembic. `create_all` ДОДАЄ нові таблиці,
# але НЕ додає нові колонки до вже наявних — тож нові поля на існуючих таблицях докочуємо тут
# через ADD COLUMN IF NOT EXISTS (Postgres). Безпечно ганяти на кожному старті.
_COLUMN_MIGRATIONS = (
    "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS error TEXT",
)

# Нові значення нативного enum-типу. create_all НЕ розширює існуючий enum -> докочуємо вручну.
# `ALTER TYPE ... ADD VALUE` має йти в AUTOCOMMIT (не в транзакції) і не може бути використане
# в тій самій транзакції, де додане. IF NOT EXISTS -> ідемпотентно. BEFORE 'failed' -> логічний порядок.
_ENUM_MIGRATIONS = (
    "ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS 'ingesting' BEFORE 'failed'",
    "ALTER TYPE meetingstatus ADD VALUE IF NOT EXISTS 'ingested' BEFORE 'failed'",
)


def init_db() -> None:
    """Створити таблиці (ідемпотентно) + докотити нові колонки/enum-значення. Імпорт моделей — мапінги."""
    from app import models  # noqa: F401  — реєстрація мапінгів до create_all
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for ddl in _COLUMN_MIGRATIONS:
            conn.execute(text(ddl))
    # enum-значення — в autocommit (поза транзакцією)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for ddl in _ENUM_MIGRATIONS:
            conn.execute(text(ddl))


def get_db() -> Iterator[Session]:
    """FastAPI-залежність: сесія на запит."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
