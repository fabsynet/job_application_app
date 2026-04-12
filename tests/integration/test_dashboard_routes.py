"""Integration tests for the dashboard, fragments, runs list, and force-run.

Uses the same isolated ``create_app`` fixture pattern as
``test_scheduler_lifecycle.py``: reload ``app.config`` and ``app.db.base``
after pointing DATA_DIR at ``tmp_path``, create the schema on the freshly
bound engine, then drive the lifespan via ``app.router.lifespan_context``.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select


@pytest_asyncio.fixture
async def live_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("BIND_ADDRESS", "127.0.0.1")
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

    import app.main as main_module

    importlib.reload(main_module)

    app = main_module.create_app()
    yield app, base_module

    await base_module.engine.dispose()


async def test_dashboard_renders(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            body = resp.text
            assert "Scheduler" in body
            assert "Kill switch" in body
            assert "Dry run" in body
            assert "Force run now" in body
            # HTMX polling wiring present in the rendered page.
            assert 'hx-trigger="every 5s' in body
            assert 'hx-trigger="every 15s' in body
            # Pico.css linked.
            assert "/static/pico.min.css" in body


async def test_fragment_status_returns_pill(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/fragments/status")
            assert resp.status_code == 200
            body = resp.text
            assert "status-pill" in body
            # With the default Settings row, scheduler is running and not killed.
            assert "Running" in body


async def test_fragment_next_run(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/fragments/next-run")
            assert resp.status_code == 200
            # Either the countdown or "No scheduled run" should appear.
            assert "Next run in" in resp.text or "No scheduled run" in resp.text


async def test_runs_list_empty(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/runs")
            assert resp.status_code == 200
            assert "No runs yet" in resp.text


async def test_run_detail_404(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/runs/999999")
            assert resp.status_code == 404


async def test_force_run_creates_run_row(live_app) -> None:
    app, base_module = live_app
    from app.db.models import Run

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/runs/trigger")
            assert resp.status_code == 200

            # The stub pipeline is ~50ms; give the background task time to
            # run and finalize the Run row.
            for _ in range(50):
                await asyncio.sleep(0.02)
                async with base_module.async_session() as session:
                    rows = (await session.execute(select(Run))).scalars().all()
                    if rows and rows[-1].status in ("succeeded", "skipped", "failed"):
                        break

            async with base_module.async_session() as session:
                rows = (await session.execute(select(Run))).scalars().all()
                assert len(rows) >= 1
                assert rows[-1].triggered_by == "manual"


async def test_run_detail_renders_counts(live_app) -> None:
    app, base_module = live_app
    from app.db.models import Run

    async with app.router.lifespan_context(app):
        # Seed a finished run directly.
        from datetime import datetime

        async with base_module.async_session() as session:
            run = Run(
                status="succeeded",
                dry_run=True,
                triggered_by="manual",
                counts={"discovered": 3, "submitted": 1},
                ended_at=datetime.utcnow(),
                duration_ms=42,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/runs/{run_id}")
            assert resp.status_code == 200
            body = resp.text
            assert "succeeded" in body
            assert "DRY" in body  # dry_run badge
            assert "discovered" in body
            assert "submitted" in body
