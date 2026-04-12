"""Async SQLAlchemy engine + session factory + init_db helper.

Production schema is owned by Alembic (see ``app/db/migrations/``); this
module only provides runtime wiring and a one-shot startup routine that
turns on WAL mode and backfills crashed-mid-run rows.

Contracts:

* ``engine`` - process-wide async engine bound to ``${DATA_DIR}/app.db``.
* ``async_session`` - ``async_sessionmaker`` with ``expire_on_commit=False``
  so objects survive past ``await session.commit()`` (required for the
  dashboard which reads freshly-committed rows without re-fetching).
* ``init_db()`` - called from FastAPI lifespan. Ensures the data directory
  exists, switches SQLite into WAL journal mode, and imports the models
  module so the tables register on ``SQLModel.metadata``.
* ``mark_orphans_failed()`` - heals ``Run(status='running')`` rows left
  behind by a hard kill, per the RESEARCH.md "DB sentinel orphan rows"
  pitfall.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_settings = get_settings()

# SQLite-over-aiosqlite. The trailing triple-slash is intentional: the fourth
# slash would indicate an absolute path on POSIX, but here ``data_dir`` already
# carries the leading slash.
DB_URL = f"sqlite+aiosqlite:///{_settings.data_dir}/app.db"

engine = create_async_engine(DB_URL, echo=False, future=True)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Prepare the database for serving traffic.

    Steps:
      1. Ensure the host-mounted ``data_dir`` exists (first-boot case).
      2. Switch SQLite into WAL journal mode so HTMX dashboard polls do not
         block the scheduler writing ``runs`` rows.
      3. Import the models module so SQLModel registers tables on the
         shared metadata. Real schema is created by Alembic; the
         ``create_all`` call is left intentionally commented out for tests
         that spin up an in-memory DB.
    """
    _settings.data_dir.mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        # RESEARCH.md pitfall: default journal_mode=DELETE blocks readers.
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        # Importing models registers them on SQLModel.metadata.
        from app.db import models  # noqa: F401
        # Alembic owns production schema creation; tests use an in-memory
        # fixture that calls SQLModel.metadata.create_all explicitly.
        # await conn.run_sync(SQLModel.metadata.create_all)


async def mark_orphans_failed() -> None:
    """Heal ``Run`` rows that were ``status='running'`` when the container died.

    Called once on startup from ``SchedulerService.start()`` (Plan 01-03).
    The UPDATE is idempotent and safe under concurrent boots because
    ``--workers 1`` guarantees a single owner of the scheduler.
    """
    async with async_session() as session:
        await session.execute(
            text(
                "UPDATE runs "
                "SET status='failed', "
                "    failure_reason='crashed', "
                "    ended_at=CURRENT_TIMESTAMP "
                "WHERE status='running'"
            )
        )
        await session.commit()


__all__ = ["engine", "async_session", "init_db", "mark_orphans_failed", "DB_URL"]
