"""Phase 2 integration tests: credential save + validation (CONF-07, CONF-08).

Mocks the validation functions at the router import level so no real network
calls are made. Verifies save-first-validate-second pattern and status display.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


# ── Anthropic credential tests ─────────────────────────────────────────


async def test_anthropic_key_save_valid(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    mock_validate = AsyncMock(return_value=(True, "API key is valid"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_anthropic_key", mock_validate):
                resp = await client.post(
                    "/settings/credentials/anthropic",
                    data={"api_key": "sk-ant-test-valid-key-1234567890"},
                )
            assert resp.status_code == 200
            assert "Saved" in resp.text
            assert "valid" in resp.text.lower()
            assert "Configured" in resp.text

            async with base_module.async_session() as session:
                row = (await session.execute(
                    select(Secret).where(Secret.name == "anthropic_api_key")
                )).scalar_one()
                assert row.ciphertext is not None


async def test_anthropic_key_save_invalid(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    mock_validate = AsyncMock(return_value=(False, "Invalid API key"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_anthropic_key", mock_validate):
                resp = await client.post(
                    "/settings/credentials/anthropic",
                    data={"api_key": "sk-ant-bad-key-invalid"},
                )
            assert resp.status_code == 200
            assert "Invalid" in resp.text

            # Key still saved despite invalid validation
            async with base_module.async_session() as session:
                row = (await session.execute(
                    select(Secret).where(Secret.name == "anthropic_api_key")
                )).scalar_one_or_none()
                assert row is not None


async def test_anthropic_key_save_network_error(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    mock_validate = AsyncMock(return_value=(False, "Validation timed out -- key saved but not verified"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_anthropic_key", mock_validate):
                resp = await client.post(
                    "/settings/credentials/anthropic",
                    data={"api_key": "sk-ant-timeout-key-abcdef"},
                )
            assert resp.status_code == 200
            assert "saved" in resp.text.lower() or "Saved" in resp.text

            # Key saved despite timeout
            async with base_module.async_session() as session:
                row = (await session.execute(
                    select(Secret).where(Secret.name == "anthropic_api_key")
                )).scalar_one_or_none()
                assert row is not None


# ── SMTP credential tests ─────────────────────────────────────────────


async def test_smtp_save_valid(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    mock_validate = AsyncMock(return_value=(True, "SMTP credentials valid"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_smtp_credentials", mock_validate):
                resp = await client.post(
                    "/settings/credentials/smtp",
                    data={
                        "smtp_host": "smtp.gmail.com",
                        "smtp_port": "587",
                        "smtp_user": "test@gmail.com",
                        "smtp_password": "app-password-1234",
                    },
                )
            assert resp.status_code == 200
            assert "Saved" in resp.text
            assert "Configured" in resp.text

            # All 4 secrets saved
            async with base_module.async_session() as session:
                for name in ("smtp_host", "smtp_port", "smtp_user", "smtp_password"):
                    row = (await session.execute(
                        select(Secret).where(Secret.name == name)
                    )).scalar_one_or_none()
                    assert row is not None, f"Secret {name} not found"


async def test_smtp_save_invalid(live_app) -> None:
    app, base_module, _ = live_app
    from app.db.models import Secret

    mock_validate = AsyncMock(return_value=(False, "Authentication failed"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_smtp_credentials", mock_validate):
                resp = await client.post(
                    "/settings/credentials/smtp",
                    data={
                        "smtp_host": "smtp.gmail.com",
                        "smtp_port": "587",
                        "smtp_user": "test@gmail.com",
                        "smtp_password": "wrong-password",
                    },
                )
            assert resp.status_code == 200
            assert "Authentication failed" in resp.text

            # Saved anyway
            async with base_module.async_session() as session:
                row = (await session.execute(
                    select(Secret).where(Secret.name == "smtp_host")
                )).scalar_one_or_none()
                assert row is not None


# ── Status display tests ──────────────────────────────────────────────


async def test_credentials_status_configured(live_app) -> None:
    app, _, _ = live_app

    mock_validate = AsyncMock(return_value=(True, "API key is valid"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Save a key first
            with patch("app.credentials.validation.validate_anthropic_key", mock_validate):
                await client.post(
                    "/settings/credentials/anthropic",
                    data={"api_key": "sk-ant-configured-key-1234"},
                )

            # Load section
            resp = await client.get("/settings/section/credentials")
            assert resp.status_code == 200
            assert "Configured" in resp.text


async def test_credentials_status_not_set(live_app) -> None:
    app, _, _ = live_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/settings/section/credentials")
            assert resp.status_code == 200
            assert "Not set" in resp.text


async def test_credentials_never_revealed(live_app) -> None:
    app, _, _ = live_app
    secret_value = "sk-ant-super-secret-key-9876543210-DEADBEEF"

    mock_validate = AsyncMock(return_value=(True, "API key is valid"))

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            with patch("app.credentials.validation.validate_anthropic_key", mock_validate):
                await client.post(
                    "/settings/credentials/anthropic",
                    data={"api_key": secret_value},
                )

            resp = await client.get("/settings/section/credentials")
            assert resp.status_code == 200
            assert secret_value not in resp.text
