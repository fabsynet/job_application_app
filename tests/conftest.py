"""Shared pytest fixtures for the Phase 1 test suite.

Only small, opt-in fixtures live here. Nothing is auto-used — tests must
request fixtures explicitly so each case remains legible.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel


@pytest.fixture
def tmp_fernet_key() -> str:
    """Yield a freshly generated Fernet key (string form)."""
    return Fernet.generate_key().decode()


@pytest.fixture
def env_with_fernet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_fernet_key: str,
    tmp_path: Path,
) -> Iterator[str]:
    """Set the minimum env vars required to construct ``Settings`` cleanly.

    Yields the Fernet key so tests can assert on it or reuse it. Ensures the
    settings cache is cleared on entry and exit so neighbouring tests do not
    see a stale ``Settings`` instance from a previous case.
    """
    from app.config import get_settings

    monkeypatch.setenv("FERNET_KEY", tmp_fernet_key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("BIND_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    try:
        yield tmp_fernet_key
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def async_session() -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession bound to an in-memory SQLite DB.

    Importing ``app.db.models`` registers the Phase 1 tables on the shared
    SQLModel metadata; we then create them on a fresh engine per test so
    cases are fully isolated. The returned session uses
    ``expire_on_commit=False`` to match the production session factory.
    """
    # Register tables on the metadata before create_all.
    from app.db import models  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session_factory():
    """Yield an in-memory async_sessionmaker for tests that need multiple sessions."""
    from app.db import models  # noqa: F401

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        yield session_factory
    finally:
        await engine.dispose()
