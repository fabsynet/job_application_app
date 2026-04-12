"""Integration tests for the FastAPI lifespan + SchedulerService wiring.

These tests enter the real lifespan context (using ``httpx.ASGITransport``
with ``lifespan="on"``), exercise ``/health``, and assert the scheduler is
up with the hourly heartbeat job registered. The DB is a real on-disk
SQLite file in ``tmp_path`` — we then create the schema via ``SQLModel``
metadata because Alembic is a heavyweight path for unit-scoped tests.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet


@pytest_asyncio.fixture
async def app_with_lifespan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Build a fresh ``app.main:create_app`` bound to an isolated data dir.

    Steps:
      1. Set env vars BEFORE importing ``app.config`` / ``app.db.base``.
      2. Reload ``app.config`` and ``app.db.base`` so the module-level engine
         picks up the new ``DATA_DIR``.
      3. Create the schema via ``SQLModel.metadata.create_all`` on that
         freshly-bound engine.
      4. Call ``create_app()`` and yield the FastAPI app.
    """
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("BIND_ADDRESS", "127.0.0.1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    # Reload config first so get_settings picks up new env.
    import app.config as config_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)

    # Reload db.base so the module-level engine re-binds to the new data dir.
    import app.db.base as base_module

    importlib.reload(base_module)

    # Ensure models import on the reloaded metadata.
    from app.db import models  # noqa: F401
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Reload main so it picks up the reloaded base/config.
    import app.main as main_module

    importlib.reload(main_module)

    app = main_module.create_app()
    yield app

    # Dispose to release SQLite file locks on Windows.
    await base_module.engine.dispose()


async def test_lifespan_starts_and_stops_cleanly(app_with_lifespan) -> None:
    # httpx 0.28 dropped ASGITransport lifespan wiring, so we drive the
    # lifespan context manually and hit /health from inside the with-block.
    async with app_with_lifespan.router.lifespan_context(app_with_lifespan):
        transport = httpx.ASGITransport(app=app_with_lifespan)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "ok"
            assert body["scheduler_running"] is True
            assert body["kill_switch"] is False
            assert body["next_run_iso"] is not None

            # Heartbeat job registered with correct ID.
            svc = app_with_lifespan.state.scheduler
            job = svc._scheduler.get_job("hourly_heartbeat")
            assert job is not None
            assert job.id == "hourly_heartbeat"
            assert job.max_instances == 1
            assert job.coalesce is True

            # Midnight reset job also registered.
            assert svc._scheduler.get_job("midnight_reset") is not None


async def test_health_endpoint_before_scheduler_ready() -> None:
    """The /health endpoint returns 'starting' if scheduler is not set yet."""
    from fastapi import FastAPI

    from app.web.routers.health import router

    app = FastAPI()
    app.include_router(router)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "starting"}


async def test_orphan_cleanup_marks_crashed_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A pre-existing Run(status='running') row is marked crashed at startup."""
    import importlib

    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "INFO")

    import app.config as config_module

    config_module.get_settings.cache_clear()
    importlib.reload(config_module)

    import app.db.base as base_module

    importlib.reload(base_module)

    from app.db import models  # noqa: F401
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Seed an orphan run row BEFORE the lifespan runs.
    from app.db.models import Run

    async with base_module.async_session() as session:
        orphan = Run(status="running", dry_run=False, triggered_by="scheduler")
        session.add(orphan)
        await session.commit()
        await session.refresh(orphan)
        orphan_id = orphan.id

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

            # After lifespan startup, the orphan should be marked failed/crashed.
            from sqlalchemy import select

            async with base_module.async_session() as session:
                result = await session.execute(select(Run).where(Run.id == orphan_id))
                row = result.scalar_one()
                assert row.status == "failed"
                assert row.failure_reason == "crashed"
                assert row.ended_at is not None

    await base_module.engine.dispose()
