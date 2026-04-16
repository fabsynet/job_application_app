"""Tests for the /needs-info router endpoints (Plan 06-06 Task 1).

Uses the live_app fixture pattern from tests/review/test_router.py — reload
config + db against a fresh tmp DATA_DIR so each test runs isolated.
"""
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

    app_obj = main_module.create_app()
    yield app_obj, base_module, key, tmp_path

    await base_module.engine.dispose()


async def _seed_needs_info_job(
    base_module,
    *,
    job_id: int = 1,
    title: str = "Engineer",
    company: str = "Acme",
    status: str = "needs_info",
    fields: list[dict] | None = None,
) -> int:
    """Create a job with optional unknown fields."""
    from app.discovery.models import Job
    from app.learning.service import create_unknown_fields

    async with base_module.async_session() as session:
        job = Job(
            id=job_id,
            fingerprint=f"fp-{job_id}",
            external_id=f"ext-{job_id}",
            source="greenhouse",
            company=company,
            title=title,
            url=f"https://example.com/jobs/{job_id}",
            status=status,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        if fields:
            await create_unknown_fields(session, job.id, fields)
            await session.commit()

        return job.id


# =========================================================================
# GET /needs-info
# =========================================================================


@pytest.mark.asyncio
async def test_needs_info_list(live_app) -> None:
    app, base_module, _, tmp_path = live_app
    await _seed_needs_info_job(
        base_module,
        title="Backend Dev",
        company="TestCo",
        fields=[
            {"field_label": "Q1", "field_type": "text"},
            {"field_label": "Q2", "field_type": "select", "field_options": "a,b,c"},
        ],
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/needs-info")
            assert resp.status_code == 200
            assert "Backend Dev" in resp.text
            assert "TestCo" in resp.text
            assert "<table" in resp.text


@pytest.mark.asyncio
async def test_needs_info_list_empty(live_app) -> None:
    app, base_module, _, _ = live_app
    # No needs_info jobs exist

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/needs-info")
            assert resp.status_code == 200
            assert "No halted applications" in resp.text


# =========================================================================
# GET /needs-info/{job_id}
# =========================================================================


@pytest.mark.asyncio
async def test_needs_info_detail(live_app) -> None:
    app, base_module, _, _ = live_app
    job_id = await _seed_needs_info_job(
        base_module,
        title="Frontend Dev",
        company="WidgetCo",
        fields=[
            {"field_label": "Years of Experience", "field_type": "text", "is_required": True},
            {"field_label": "Salary", "field_type": "text"},
        ],
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get(f"/needs-info/{job_id}")
            assert resp.status_code == 200
            assert "Frontend Dev" in resp.text
            assert "WidgetCo" in resp.text
            assert "Years of Experience" in resp.text
            assert "Salary" in resp.text
            assert "Required" in resp.text  # is_required badge


@pytest.mark.asyncio
async def test_needs_info_detail_404(live_app) -> None:
    app, base_module, _, _ = live_app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # Non-existent job
            resp = await client.get("/needs-info/9999")
            assert resp.status_code == 404


@pytest.mark.asyncio
async def test_needs_info_detail_404_wrong_status(live_app) -> None:
    app, base_module, _, _ = live_app
    # Create a job with status 'approved' (not needs_info)
    job_id = await _seed_needs_info_job(
        base_module,
        job_id=2,
        status="approved",
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get(f"/needs-info/{job_id}")
            assert resp.status_code == 404


# =========================================================================
# POST /needs-info/{job_id}/answer
# =========================================================================


@pytest.mark.asyncio
async def test_answer_and_resolve(live_app) -> None:
    app, base_module, _, _ = live_app
    job_id = await _seed_needs_info_job(
        base_module,
        title="DevOps",
        company="CloudCo",
        fields=[
            {"field_label": "Q1", "field_type": "text"},
            {"field_label": "Q2", "field_type": "text"},
        ],
    )

    # Get field IDs
    from app.learning.models import UnknownField
    from sqlalchemy import select

    async with base_module.async_session() as session:
        result = await session.execute(
            select(UnknownField).where(UnknownField.job_id == job_id)
        )
        fields = result.scalars().all()
        field_ids = [f.id for f in fields]

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            form_data = {
                f"field_{field_ids[0]}": "Answer 1",
                f"field_{field_ids[1]}": "Answer 2",
            }
            resp = await client.post(
                f"/needs-info/{job_id}/answer",
                data=form_data,
                follow_redirects=False,
            )
            assert resp.status_code == 303

    # Verify job status flipped to approved
    from app.discovery.models import Job

    async with base_module.async_session() as session:
        job = await session.get(Job, job_id)
        assert job.status == "approved"


@pytest.mark.asyncio
async def test_answer_creates_saved_answers(live_app) -> None:
    app, base_module, _, _ = live_app
    job_id = await _seed_needs_info_job(
        base_module,
        job_id=3,
        title="SRE",
        company="InfraCo",
        fields=[
            {"field_label": "Availability", "field_type": "text"},
        ],
    )

    # Get field IDs
    from app.learning.models import UnknownField, SavedAnswer
    from sqlalchemy import select

    async with base_module.async_session() as session:
        result = await session.execute(
            select(UnknownField).where(UnknownField.job_id == job_id)
        )
        fields = result.scalars().all()
        field_id = fields[0].id

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/needs-info/{job_id}/answer",
                data={f"field_{field_id}": "2 weeks notice"},
                follow_redirects=False,
            )
            assert resp.status_code == 303

    # Verify SavedAnswer was created
    async with base_module.async_session() as session:
        result = await session.execute(select(SavedAnswer))
        answers = result.scalars().all()
        assert len(answers) == 1
        assert answers[0].field_label == "Availability"
        assert answers[0].answer_text == "2 weeks notice"

    # Verify UnknownField marked resolved
    async with base_module.async_session() as session:
        result = await session.execute(
            select(UnknownField).where(UnknownField.id == field_id)
        )
        uf = result.scalar_one()
        assert uf.resolved is True
        assert uf.saved_answer_id is not None
