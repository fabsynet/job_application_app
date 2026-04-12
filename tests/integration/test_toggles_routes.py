"""Integration tests for /toggles/kill-switch and /toggles/dry-run routes.

Verifies the HTMX toggle routes flip the corresponding Settings fields,
persist, and — for the kill-switch — actually cancel an in-flight run via
the real KillSwitch primitive from plan 01-03.
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


async def test_kill_switch_toggle_engage_release(live_app) -> None:
    app, base_module = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Initially not engaged.
            assert app.state.killswitch.is_engaged() is False

            # Engage.
            resp = await client.post("/toggles/kill-switch")
            assert resp.status_code == 200
            assert "Release kill-switch" in resp.text
            assert app.state.killswitch.is_engaged() is True

            async with base_module.async_session() as session:
                row = (
                    await session.execute(select(Settings).where(Settings.id == 1))
                ).scalar_one()
                assert row.kill_switch is True

            # Release.
            resp = await client.post("/toggles/kill-switch")
            assert resp.status_code == 200
            assert "Kill switch" in resp.text
            assert app.state.killswitch.is_engaged() is False


async def test_dry_run_toggle(live_app) -> None:
    app, base_module = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/toggles/dry-run")
            assert resp.status_code == 200
            assert "Dry run: ON" in resp.text

            async with base_module.async_session() as session:
                row = (
                    await session.execute(select(Settings).where(Settings.id == 1))
                ).scalar_one()
                assert row.dry_run is True

            resp = await client.post("/toggles/dry-run")
            assert "Dry run: OFF" in resp.text

            async with base_module.async_session() as session:
                row = (
                    await session.execute(select(Settings).where(Settings.id == 1))
                ).scalar_one()
                assert row.dry_run is False


async def test_kill_switch_cancels_in_flight(live_app) -> None:
    """POST /toggles/kill-switch mid-run must produce a failed/killed Run row."""
    app, base_module = live_app
    from app.db.models import Run

    async with app.router.lifespan_context(app):
        svc = app.state.scheduler
        ks = app.state.killswitch

        # Monkey-patch the stub with a long loop that checkpoints the ks
        # so the toggle route gets a visible window to cancel.
        async def long_stub(ctx):
            for _ in range(500):
                await ks.raise_if_engaged()
                await asyncio.sleep(0.01)

        svc._execute_stub = long_stub  # type: ignore[method-assign]

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Kick off a manual run; fire-and-forget via POST /runs/trigger.
            resp = await client.post("/runs/trigger")
            assert resp.status_code == 200

            # Wait until the pipeline task is actually running.
            for _ in range(200):
                await asyncio.sleep(0.005)
                if svc._current_task is not None and not svc._current_task.done():
                    break
            assert svc._current_task is not None

            # Flip the kill switch via the HTTP route.
            resp = await client.post("/toggles/kill-switch")
            assert resp.status_code == 200

            # Wait for the in-flight run to be finalised.
            for _ in range(200):
                await asyncio.sleep(0.01)
                async with base_module.async_session() as session:
                    rows = (await session.execute(select(Run))).scalars().all()
                    if rows and rows[-1].status != "running":
                        break

            async with base_module.async_session() as session:
                rows = (await session.execute(select(Run))).scalars().all()
                assert len(rows) >= 1
                killed = rows[-1]
                assert killed.status == "failed"
                assert killed.failure_reason == "killed"
