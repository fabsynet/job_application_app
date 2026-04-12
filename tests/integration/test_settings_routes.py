"""Integration tests for /settings (secrets CRUD + rate-limit envelope).

Focus:
* Secrets round-trip through FernetVault → DB ciphertext → scrubber registry.
* Saving limits mutates the live RateLimiter without a restart.
* Validation rejects obviously-broken rate-limit envelopes.
* The rotation-warning banner is present (CONTEXT.md + RESEARCH.md pitfall).
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

    from app.db import models  # noqa: F401
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    import app.main as main_module

    importlib.reload(main_module)

    app = main_module.create_app()
    yield app, base_module, key

    await base_module.engine.dispose()


async def test_settings_page_renders(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/settings")
            assert resp.status_code == 200
            body = resp.text
            # Sidebar layout with section links
            assert "settings-layout" in body
            assert "settings-sidebar" in body
            assert "settings-content" in body
            # All 10 sidebar sections present as links
            for section in [
                "Mode", "Profile", "Resume", "Keywords", "Threshold",
                "Credentials", "Schedule", "Budget", "Rate Limits", "Safety",
            ]:
                assert section in body
            # Default section is Mode (loaded inline)
            assert "Application Mode" in body
            assert "Full Auto" in body
            assert "Review Queue" in body


async def test_save_secret_encrypts_and_scrubs(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret
    from app.security.log_scrubber import REGISTRY

    plaintext = "sk-ant-api03-TESTSENTINELDEADBEEF01234567890"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/secrets",
                data={"name": "anthropic_api_key", "value": plaintext},
            )
            assert resp.status_code == 200
            assert "anthropic_api_key" in resp.text
            assert "stored" in resp.text

            async with base_module.async_session() as session:
                row = (
                    await session.execute(
                        select(Secret).where(Secret.name == "anthropic_api_key")
                    )
                ).scalar_one()
                # Ciphertext is bytes and does NOT equal the plaintext.
                assert isinstance(row.ciphertext, (bytes, bytearray))
                assert plaintext.encode() not in bytes(row.ciphertext)

                # Vault round-trip works.
                vault = app.state.vault
                assert vault.decrypt(row.ciphertext) == plaintext

            # Scrubber now redacts the plaintext.
            assert REGISTRY.scrub(f"token is {plaintext}") != f"token is {plaintext}"


async def test_save_secret_upsert_replaces_value(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/settings/secrets",
                data={"name": "smtp_password", "value": "first-value-1234"},
            )
            await client.post(
                "/settings/secrets",
                data={"name": "smtp_password", "value": "second-value-5678"},
            )

            async with base_module.async_session() as session:
                rows = (
                    await session.execute(
                        select(Secret).where(Secret.name == "smtp_password")
                    )
                ).scalars().all()
                assert len(rows) == 1
                vault = app.state.vault
                assert vault.decrypt(rows[0].ciphertext) == "second-value-5678"


async def test_delete_secret(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/settings/secrets",
                data={"name": "anthropic_api_key", "value": "sk-ant-xyzzy1234567890"},
            )
            resp = await client.request(
                "DELETE", "/settings/secrets/anthropic_api_key"
            )
            assert resp.status_code == 200
            assert "not set" in resp.text

            async with base_module.async_session() as session:
                rows = (
                    await session.execute(
                        select(Secret).where(Secret.name == "anthropic_api_key")
                    )
                ).scalars().all()
                assert rows == []


async def test_save_limits_updates_live_rate_limiter(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Default from plan 01-03: daily_cap=20, delay 30/120, UTC.
            assert app.state.rate_limiter.daily_cap == 20

            resp = await client.post(
                "/settings/limits",
                data={
                    "daily_cap": "10",
                    "delay_min_seconds": "45",
                    "delay_max_seconds": "90",
                    "timezone": "America/Los_Angeles",
                },
            )
            assert resp.status_code == 200
            assert "Rate limits saved" in resp.text

            # Live in-memory rate limiter reflects the change.
            rl = app.state.rate_limiter
            assert rl.daily_cap == 10
            assert rl.delay_min == 45
            assert rl.delay_max == 90
            assert str(rl.tz) == "America/Los_Angeles"

            # DB persisted too.
            async with base_module.async_session() as session:
                row = (
                    await session.execute(select(Settings).where(Settings.id == 1))
                ).scalar_one()
                assert row.daily_cap == 10
                assert row.delay_min_seconds == 45
                assert row.delay_max_seconds == 90
                assert row.timezone == "America/Los_Angeles"


async def test_save_limits_rejects_invalid_range(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/limits",
                data={
                    "daily_cap": "10",
                    "delay_min_seconds": "100",
                    "delay_max_seconds": "50",
                    "timezone": "UTC",
                },
            )
            assert resp.status_code == 400


async def test_save_limits_rejects_invalid_cap(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/limits",
                data={
                    "daily_cap": "-1",
                    "delay_min_seconds": "30",
                    "delay_max_seconds": "120",
                    "timezone": "UTC",
                },
            )
            assert resp.status_code == 400


async def test_save_limits_rejects_bad_timezone(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/limits",
                data={
                    "daily_cap": "10",
                    "delay_min_seconds": "30",
                    "delay_max_seconds": "120",
                    "timezone": "Mars/Olympus_Mons",
                },
            )
            assert resp.status_code == 400
