"""Phase 5 plan 05-06 Task 2 — manual-apply router integration tests.

Mirrors the ``live_app`` fixture pattern established in
``tests/review/test_router.py``: reload ``app.config`` + ``app.db.base``
against a fresh tmp DATA_DIR, create tables, build the FastAPI app
inside the lifespan context, drive it with ``httpx.AsyncClient``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import func, select


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

    app_obj = main_module.create_app()
    yield app_obj, base_module, key, tmp_path

    await base_module.engine.dispose()


def _install_parsed(monkeypatch: pytest.MonkeyPatch, parsed):
    """Force ``fetch_and_parse`` to return ``parsed`` — no network."""
    from app.manual_apply import fetcher as fetcher_module
    from app.web.routers import manual_apply as router_module

    async def _fake(url: str):
        return parsed

    monkeypatch.setattr(fetcher_module, "fetch_and_parse", _fake)
    monkeypatch.setattr(router_module, "fetch_and_parse", _fake)


def _install_fetch_error(monkeypatch: pytest.MonkeyPatch, reason: str, status=None):
    from app.manual_apply import fetcher as fetcher_module
    from app.manual_apply.fetcher import FetchError
    from app.web.routers import manual_apply as router_module

    async def _fake(url: str):
        raise FetchError(reason, status=status)

    monkeypatch.setattr(fetcher_module, "fetch_and_parse", _fake)
    monkeypatch.setattr(router_module, "fetch_and_parse", _fake)


def _sample_parsed(**overrides):
    from app.manual_apply.fetcher import ParsedJob

    defaults = dict(
        title="Senior Platform Engineer",
        company="Acme",
        description="Build distributed systems in Python and Rust.",
        description_html="<p>Build distributed systems in Python and Rust.</p>",
        url="https://boards.greenhouse.io/acme/jobs/42",
        source="greenhouse",
        external_id="/acme/jobs/42",
    )
    defaults.update(overrides)
    return ParsedJob(**defaults)


# ---------------------------------------------------------------------------
# GET /manual-apply
# ---------------------------------------------------------------------------


async def test_get_manual_apply_renders(live_app) -> None:
    app, *_ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.get("/manual-apply")
            assert resp.status_code == 200
            assert '<input' in resp.text
            assert 'name="url"' in resp.text
            assert "Manual Apply" in resp.text


# ---------------------------------------------------------------------------
# POST /manual-apply/preview
# ---------------------------------------------------------------------------


async def test_post_preview_success_returns_preview_card(
    live_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, *_ = live_app
    parsed = _sample_parsed()
    _install_parsed(monkeypatch, parsed)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/preview",
                data={"url": parsed.url},
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert parsed.title in resp.text
            assert parsed.company in resp.text
            assert "greenhouse" in resp.text
            assert "Tailor this job" in resp.text


async def test_post_preview_fetch_error_returns_fallback_with_reason(
    live_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, *_ = live_app
    _install_fetch_error(monkeypatch, "auth_wall", status=403)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/preview",
                data={"url": "https://www.linkedin.com/jobs/view/1"},
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "auth_wall" in resp.text
            assert "<textarea" in resp.text
            assert "manual-apply-fallback" in resp.text


async def test_post_preview_empty_url_returns_fallback(
    live_app,
) -> None:
    app, *_ = live_app
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/preview",
                data={"url": ""},
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "empty_url" in resp.text


# ---------------------------------------------------------------------------
# POST /manual-apply/confirm
# ---------------------------------------------------------------------------


async def test_post_confirm_creates_job_with_status_matched(live_app) -> None:
    app, base_module, *_ = live_app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/confirm",
                data={
                    "title": "Staff SRE",
                    "company": "Stripe",
                    "description": "Own our SRE practice.",
                    "source": "greenhouse",
                    "url": "https://boards.greenhouse.io/stripe/jobs/123",
                    "external_id": "/stripe/jobs/123",
                },
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "Queued for tailoring" in resp.text
            assert "Staff SRE" in resp.text

    from app.discovery.models import Job

    async with base_module.async_session() as session:
        row = (
            await session.execute(select(Job).where(Job.title == "Staff SRE"))
        ).scalar_one()
        assert row.status == "matched"
        assert row.score == 100
        assert row.matched_keywords == "manual_paste"
        assert row.source == "greenhouse"


async def test_post_confirm_duplicate_shows_existing_job(live_app) -> None:
    app, base_module, *_ = live_app
    from app.discovery.models import Job
    from app.discovery.scoring import job_fingerprint

    url = "https://boards.greenhouse.io/acme/jobs/1"
    title = "Engineer"
    company = "Acme"
    fp = job_fingerprint(url, title, company)

    async with base_module.async_session() as session:
        session.add(
            Job(
                fingerprint=fp,
                external_id="/acme/jobs/1",
                title=title,
                company=company,
                description="Existing",
                description_html="<p>Existing</p>",
                url=url,
                source="greenhouse",
                score=42,
                matched_keywords="python",
                status="matched",
            )
        )
        await session.commit()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/confirm",
                data={
                    "title": title,
                    "company": company,
                    "description": "Different body",
                    "source": "greenhouse",
                    "url": url,
                    "external_id": "/acme/jobs/1",
                },
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "Already in the queue" in resp.text

    async with base_module.async_session() as session:
        count = (
            await session.execute(select(func.count()).select_from(Job))
        ).scalar_one()
        assert count == 1


# ---------------------------------------------------------------------------
# POST /manual-apply/fallback
# ---------------------------------------------------------------------------


async def test_post_fallback_creates_job_without_url_fetch(
    live_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, base_module, *_ = live_app

    # Sentinel to prove the router never calls fetch_and_parse.
    called = {"hit": False}

    async def _fail(url: str):
        called["hit"] = True
        raise AssertionError("fetch_and_parse must not be called in fallback path")

    from app.manual_apply import fetcher as fetcher_module
    from app.web.routers import manual_apply as router_module

    monkeypatch.setattr(fetcher_module, "fetch_and_parse", _fail)
    monkeypatch.setattr(router_module, "fetch_and_parse", _fail)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/fallback",
                data={
                    "title": "Fullstack Developer",
                    "company": "SmallCo",
                    "description": "Ship features end to end.",
                    "source": "manual",
                    "url": "",
                },
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "Queued for tailoring" in resp.text

    assert called["hit"] is False

    from app.discovery.models import Job

    async with base_module.async_session() as session:
        row = (
            await session.execute(
                select(Job).where(Job.title == "Fullstack Developer")
            )
        ).scalar_one()
        assert row.status == "matched"
        assert row.source == "manual"


async def test_linkedin_url_degrades_to_fallback(
    live_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A LinkedIn auth-walled URL must not 5xx — it must render the fallback."""
    app, *_ = live_app
    _install_fetch_error(monkeypatch, "auth_wall", status=403)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            resp = await client.post(
                "/manual-apply/preview",
                data={"url": "https://www.linkedin.com/jobs/view/987654"},
                headers={"HX-Request": "true"},
            )
            assert resp.status_code == 200
            assert "auth_wall" in resp.text
            assert "manual-apply-fallback" in resp.text
