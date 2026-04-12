"""Phase 2 integration tests: settings sections (mode, keywords, threshold, schedule, budget, profile).

Covers CONF-01 through CONF-06 requirements. Uses the same fixture pattern as
Phase 1 integration tests: tmp_path data dir, module reloads, lifespan-driven
httpx.AsyncClient against the real FastAPI app.
"""

from __future__ import annotations

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

    import app.web.routers.wizard as wizard_module

    importlib.reload(wizard_module)

    from app.db import models  # noqa: F401
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    import app.main as main_module

    importlib.reload(main_module)

    application = main_module.create_app()
    yield application, base_module, key

    await base_module.engine.dispose()


async def _client(app_obj):
    """Return an httpx.AsyncClient within the app lifespan."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_obj),
        base_url="http://test",
    )


# ── Sidebar ────────────────────────────────────────────────────────────


async def test_sidebar_renders_all_sections(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/settings")
            assert resp.status_code == 200
            body = resp.text
            for section in [
                "Mode", "Profile", "Resume", "Keywords", "Threshold",
                "Credentials", "Schedule", "Budget", "Rate Limits", "Safety",
            ]:
                assert section in body, f"Sidebar missing section: {section}"


async def test_section_navigation(live_app) -> None:
    app, _, _ = live_app
    section_names = [
        "mode", "profile", "resume", "keywords", "threshold",
        "credentials", "schedule", "budget", "limits", "safety",
    ]
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            for name in section_names:
                resp = await client.get(f"/settings/section/{name}")
                assert resp.status_code == 200, f"Section {name} returned {resp.status_code}"


# ── Mode ───────────────────────────────────────────────────────────────


async def test_mode_toggle_save_auto(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/mode", data={"auto_mode": "true"})
            assert resp.status_code == 200
            assert "Application mode saved" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.auto_mode is True


async def test_mode_toggle_save_review(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/mode", data={"auto_mode": "false"})
            assert resp.status_code == 200

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.auto_mode is False


# ── Keywords ───────────────────────────────────────────────────────────


async def test_keywords_add(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/keywords", data={"keyword": "python"})
            assert resp.status_code == 200
            assert "python" in resp.text
            assert "Added" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert "python" in row.keywords_csv


async def test_keywords_add_dedup(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/settings/keywords", data={"keyword": "python"})
            resp = await client.post("/settings/keywords", data={"keyword": "Python"})
            assert resp.status_code == 200
            assert "already exists" in resp.text


async def test_keywords_remove(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/settings/keywords", data={"keyword": "python"})

            resp = await client.request("DELETE", "/settings/keywords/python")
            assert resp.status_code == 200
            assert "python" not in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert "python" not in (row.keywords_csv or "")


async def test_keywords_empty_rejected(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/keywords", data={"keyword": "  "})
            assert resp.status_code == 200
            assert "cannot be blank" in resp.text


# ── Threshold ──────────────────────────────────────────────────────────


async def test_threshold_save(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/threshold", data={"match_threshold": "75"})
            assert resp.status_code == 200
            assert "75%" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.match_threshold == 75


async def test_threshold_validation(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/threshold", data={"match_threshold": "150"})
            assert resp.status_code == 400


# ── Schedule ───────────────────────────────────────────────────────────


async def test_schedule_save(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/settings/schedule",
                data={
                    "schedule_enabled": "true",
                    "quiet_hours_start": "22",
                    "quiet_hours_end": "7",
                },
            )
            assert resp.status_code == 200
            assert "Schedule settings saved" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.schedule_enabled is True
                assert row.quiet_hours_start == 22
                assert row.quiet_hours_end == 7


async def test_schedule_disable(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # First enable
            await client.post(
                "/settings/schedule",
                data={
                    "schedule_enabled": "true",
                    "quiet_hours_start": "22",
                    "quiet_hours_end": "7",
                },
            )
            # Then disable (no schedule_enabled field)
            resp = await client.post(
                "/settings/schedule",
                data={
                    "quiet_hours_start": "22",
                    "quiet_hours_end": "7",
                },
            )
            assert resp.status_code == 200

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.schedule_enabled is False


# ── Budget ─────────────────────────────────────────────────────────────


async def test_budget_save(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/budget", data={"budget_cap_dollars": "20.0"})
            assert resp.status_code == 200
            assert "Budget cap saved" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(select(Settings).where(Settings.id == 1))).scalar_one()
                assert row.budget_cap_dollars == 20.0


async def test_budget_zero_means_no_limit(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/settings/budget", data={"budget_cap_dollars": "0"})
            assert resp.status_code == 200
            assert "No limit" in resp.text
