"""Fernet rotation banner integration tests.

Asserts that when ``FERNET_KEY`` changes between container restarts:

* The dashboard shows a visible remediation banner.
* ``/health`` still returns 200 (rotation is a remediation condition, not a
  fatal error — the app keeps running).
* Unreadable Secret rows are preserved (NOT auto-deleted) per RESEARCH.md
  pitfall: operators may want to recover them by restoring the old key.
* With an unrotated key, no banner appears.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select


def _reload_with_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, key: str):
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

    from sqlmodel import SQLModel

    from app.db import models  # noqa: F401

    return base_module


async def _ensure_schema(base_module) -> None:
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    )


async def test_rotated_key_surfaces_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    assert key_a != key_b

    base_module = _reload_with_key(monkeypatch, tmp_path, key_a)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            # Skip wizard and save a secret.
            await client.post("/setup/skip")
            resp = await client.post(
                "/settings/secrets",
                data={"name": "anthropic_api_key", "value": "sk-ant-BEFORE-ROTATE"},
            )
            assert resp.status_code == 200

    await base_module.engine.dispose()

    # --- restart with a different FERNET_KEY ---
    base_module = _reload_with_key(monkeypatch, tmp_path, key_b)
    await _ensure_schema(base_module)
    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        async with _client(app2) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            body = resp.text
            assert "Stored secrets cannot be decrypted" in body
            assert "FERNET_KEY" in body

        # The row should still be in the DB — forensic preservation.
        from app.db.models import Secret

        async with base_module.async_session() as session:
            rows = (await session.execute(select(Secret))).scalars().all()
            assert len(rows) == 1
            assert rows[0].name == "anthropic_api_key"

    await base_module.engine.dispose()


async def test_non_rotated_key_no_banner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key = Fernet.generate_key().decode()
    base_module = _reload_with_key(monkeypatch, tmp_path, key)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/setup/skip")
            await client.post(
                "/settings/secrets",
                data={"name": "anthropic_api_key", "value": "sk-steady"},
            )
    await base_module.engine.dispose()

    # --- restart with the SAME key ---
    base_module = _reload_with_key(monkeypatch, tmp_path, key)
    await _ensure_schema(base_module)
    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        async with _client(app2) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Stored secrets cannot be decrypted" not in resp.text

    await base_module.engine.dispose()


async def test_health_still_200_after_rotation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    base_module = _reload_with_key(monkeypatch, tmp_path, key_a)
    await _ensure_schema(base_module)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/setup/skip")
            await client.post(
                "/settings/secrets",
                data={"name": "smtp_password", "value": "hunter2-wins"},
            )
    await base_module.engine.dispose()

    base_module = _reload_with_key(monkeypatch, tmp_path, key_b)
    await _ensure_schema(base_module)
    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        async with _client(app2) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200

    await base_module.engine.dispose()
