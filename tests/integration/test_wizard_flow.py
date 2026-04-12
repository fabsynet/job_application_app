"""Wizard flow integration tests.

Drives the setup wizard against a live ASGI app rebuilt at a fresh
``DATA_DIR`` per test, exactly like ``test_dashboard_routes.py``. These tests
assert:

* Fresh boot redirects ``GET /`` to ``/setup/1``.
* Step 1 validates that uploaded files are non-empty ``.docx``.
* Step 2 encrypts non-empty fields into ``Secret`` rows (or accepts blanks).
* Step 3 persists keywords and flips ``wizard_complete`` to True.
* The full happy path reaches the dashboard after step 3.
* ``POST /setup/skip`` short-circuits straight to the dashboard.
* ``wizard_complete`` survives a lifespan restart on the same data_dir.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select


def _reload_app_for(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str):
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


@pytest_asyncio.fixture
async def live_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    key = Fernet.generate_key().decode()
    base_module = _reload_app_for(tmp_path, monkeypatch, key)

    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    yield app, base_module, tmp_path, key

    await base_module.engine.dispose()


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    )


async def test_fresh_boot_redirects_to_wizard(live_app) -> None:
    app, *_ = live_app
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.get("/")
            assert resp.status_code == 307
            assert resp.headers["location"] == "/setup/1"


async def test_step_1_requires_docx(live_app) -> None:
    app, *_ = live_app
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            # Wrong extension.
            resp = await client.post(
                "/setup/1",
                files={"resume": ("resume.pdf", b"something", "application/pdf")},
            )
            assert resp.status_code == 400

            # Empty DOCX.
            resp = await client.post(
                "/setup/1",
                files={
                    "resume": (
                        "resume.docx",
                        b"",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert resp.status_code == 400


async def test_step_1_accepts_docx_and_persists(live_app) -> None:
    app, _, tmp_path, _ = live_app
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.post(
                "/setup/1",
                files={
                    "resume": (
                        "r.docx",
                        b"fakebinary",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/setup/2"

            target = tmp_path / "uploads" / "resume_base.docx"
            assert target.exists()
            assert target.read_bytes() == b"fakebinary"


async def test_step_2_encrypts_secrets(live_app) -> None:
    app, base_module, _, _ = live_app
    from app.db.models import Secret

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.post(
                "/setup/2",
                data={"anthropic_api_key": "sk-ant-test-SENTINEL-123"},
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/setup/3"

        async with base_module.async_session() as session:
            row = (
                await session.execute(
                    select(Secret).where(Secret.name == "anthropic_api_key")
                )
            ).scalar_one()
            assert row is not None
            # Decrypt via the app's vault to confirm it round-trips.
            plaintext = app.state.vault.decrypt(row.ciphertext)
            assert plaintext == "sk-ant-test-SENTINEL-123"


async def test_step_2_allows_blanks(live_app) -> None:
    app, base_module, *_ = live_app
    from app.db.models import Secret

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.post("/setup/2", data={})
            assert resp.status_code == 303
            assert resp.headers["location"] == "/setup/3"

        async with base_module.async_session() as session:
            rows = (await session.execute(select(Secret))).scalars().all()
            assert rows == []


async def test_step_3_sets_wizard_complete_and_keywords(live_app) -> None:
    app, base_module, *_ = live_app
    from app.db.models import Settings

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.post(
                "/setup/3", data={"keywords": "python\nrust\ngolang"}
            )
            assert resp.status_code == 303
            assert resp.headers["location"] == "/"

        async with base_module.async_session() as session:
            row = (
                await session.execute(select(Settings).where(Settings.id == 1))
            ).scalar_one()
            assert row.wizard_complete is True
            assert row.keywords_csv == "python,rust,golang"


async def test_full_happy_path_reaches_dashboard(live_app) -> None:
    app, *_ = live_app
    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post(
                "/setup/1",
                files={
                    "resume": (
                        "r.docx",
                        b"content",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            await client.post("/setup/2", data={"anthropic_api_key": "sk-key"})
            await client.post("/setup/3", data={"keywords": "python"})

            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Scheduler" in resp.text


async def test_skip_short_circuits(live_app) -> None:
    app, base_module, *_ = live_app
    from app.db.models import Secret, Settings

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            resp = await client.post("/setup/skip")
            assert resp.status_code == 303
            assert resp.headers["location"] == "/"

            # And subsequent GET / now goes straight to the dashboard.
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Scheduler" in resp.text

        async with base_module.async_session() as session:
            row = (
                await session.execute(select(Settings).where(Settings.id == 1))
            ).scalar_one()
            assert row.wizard_complete is True
            assert row.keywords_csv == ""
            secrets = (await session.execute(select(Secret))).scalars().all()
            assert secrets == []


async def test_wizard_complete_persists_across_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Complete the wizard, tear down the lifespan, restart it fresh."""
    key = Fernet.generate_key().decode()

    base_module = _reload_app_for(tmp_path, monkeypatch, key)
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    import app.main as main_module

    importlib.reload(main_module)
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        async with _client(app) as client:
            await client.post("/setup/skip")

    await base_module.engine.dispose()

    # --- second boot ---
    base_module = _reload_app_for(tmp_path, monkeypatch, key)
    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)  # no-op, idempotent

    importlib.reload(main_module)
    app2 = main_module.create_app()

    async with app2.router.lifespan_context(app2):
        async with _client(app2) as client:
            resp = await client.get("/")
            assert resp.status_code == 200
            assert "Scheduler" in resp.text

    await base_module.engine.dispose()
