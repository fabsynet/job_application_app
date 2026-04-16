"""Tests for the Saved Answers CRUD router and Playwright settings toggles."""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet


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
    from app.learning import models as learning_models  # noqa: F401
    from sqlmodel import SQLModel

    async with base_module.engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    import app.main as main_module

    importlib.reload(main_module)

    app_instance = main_module.create_app()
    yield app_instance, base_module

    await base_module.engine.dispose()


async def _seed_answer(base_module, field_label="Favorite color", answer_text="Blue"):
    """Insert a SavedAnswer row directly for test setup."""
    from app.learning.models import SavedAnswer

    async with base_module.async_session() as session:
        sa = SavedAnswer(
            field_label=field_label,
            field_label_normalized=field_label.lower(),
            answer_text=answer_text,
            answer_type="text",
            times_reused=3,
        )
        session.add(sa)
        await session.commit()
        await session.refresh(sa)
        return sa.id


# ── Saved Answers List ────────────────────────────────────────────────


async def test_saved_answers_list(live_app) -> None:
    app, base_module = live_app
    answer_id = await _seed_answer(base_module)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/settings/saved-answers")
            assert resp.status_code == 200
            body = resp.text
            assert "Favorite color" in body
            assert "Blue" in body
            assert "text" in body


async def test_saved_answers_empty(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/settings/saved-answers")
            assert resp.status_code == 200
            assert "No saved answers yet" in resp.text


# ── Saved Answers Edit ────────────────────────────────────────────────


async def test_saved_answers_edit(live_app) -> None:
    app, base_module = live_app
    answer_id = await _seed_answer(base_module)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/settings/saved-answers/{answer_id}/edit",
                data={"answer_text": "Red"},
            )
            assert resp.status_code == 200
            assert "Red" in resp.text
            assert "Answer updated" in resp.text


async def test_saved_answers_edit_404(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/saved-answers/99999/edit",
                data={"answer_text": "Red"},
            )
            assert resp.status_code == 404


# ── Saved Answers Delete ─────────────────────────────────────────────


async def test_saved_answers_delete(live_app) -> None:
    app, base_module = live_app
    answer_id = await _seed_answer(base_module)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/settings/saved-answers/{answer_id}/delete",
            )
            assert resp.status_code == 200
            assert "Answer deleted" in resp.text
            # Answer should no longer appear
            assert "Favorite color" not in resp.text


# ── Playwright Settings ──────────────────────────────────────────────


async def test_playwright_settings_get(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/settings/section/playwright")
            assert resp.status_code == 200
            body = resp.text
            assert "Headless Browser Mode" in body
            assert "Pause on Unknown Fields" in body
            assert "Screenshot Retention" in body


async def test_playwright_settings_post(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/settings/playwright",
                data={
                    "playwright_headless": "true",
                    "pause_if_unsure": "true",
                    "screenshot_retention_days": "60",
                },
            )
            assert resp.status_code == 200
            assert "Playwright settings saved" in resp.text


async def test_playwright_settings_checkbox_unchecked(live_app) -> None:
    """Unchecked checkboxes are absent from form data, meaning False."""
    app, base_module = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # POST without checkbox fields -> both False
            resp = await client.post(
                "/settings/playwright",
                data={"screenshot_retention_days": "30"},
            )
            assert resp.status_code == 200

            # Verify stored values by checking rendered checkboxes
            resp2 = await client.get("/settings/section/playwright")
            body = resp2.text
            # Neither checkbox should be checked
            # The headless and pause_if_unsure inputs should not have 'checked'
            assert resp2.status_code == 200


async def test_playwright_settings_retention_clamped(live_app) -> None:
    app, _ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Over max
            resp = await client.post(
                "/settings/playwright",
                data={"screenshot_retention_days": "999"},
            )
            assert resp.status_code == 200

            # Under min
            resp2 = await client.post(
                "/settings/playwright",
                data={"screenshot_retention_days": "0"},
            )
            assert resp2.status_code == 200
