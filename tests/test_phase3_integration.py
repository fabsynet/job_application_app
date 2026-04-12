"""Integration tests for Phase 3: pipeline, jobs routes, sources routes, dashboard.

Uses the ``live_app`` fixture pattern from Phase 1/2 integration tests:
reload ``app.config`` and ``app.db.base`` after pointing DATA_DIR at tmp_path,
create the schema, drive lifespan via ``app.router.lifespan_context``.

Covers:
  - Pipeline end-to-end: fetch, dedup, score, persist (DISC-05, DISC-06, MATCH-01..03)
  - Jobs page routes: list, sort, detail, queue
  - Sources settings routes: CRUD, toggle, delete, validation error
  - Dashboard discovery summary + anomaly banner
"""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def live_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Create an isolated app with fresh DB for integration tests."""
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

    app_instance = main_module.create_app()

    # Mark wizard as complete for post-wizard test surface
    from app.settings.service import set_setting

    async with base_module.async_session() as session:
        await set_setting(session, "wizard_complete", True)

    yield app_instance, base_module

    await base_module.engine.dispose()


async def _seed_source_and_keywords(base_module, keywords_csv="python|react|typescript", threshold=60):
    """Seed a source and keywords for pipeline tests."""
    from app.discovery.models import Source
    from app.settings.service import set_setting

    async with base_module.async_session() as session:
        source = Source(
            slug="test-co",
            source_type="greenhouse",
            display_name="test-co",
            enabled=True,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        source_id = source.id

    async with base_module.async_session() as session:
        await set_setting(session, "keywords_csv", keywords_csv)
        await set_setting(session, "match_threshold", threshold)

    return source_id


def _mock_greenhouse_response():
    """Return mock Greenhouse API JSON data."""
    return {
        "jobs": [
            {
                "id": 1001,
                "title": "Python Backend Engineer",
                "location": {"name": "Remote"},
                "content": "<p>Build with <b>Python</b> and <b>React</b></p>",
                "absolute_url": "https://boards.greenhouse.io/test-co/jobs/1001",
                "updated_at": "2026-03-15T12:00:00Z",
            },
            {
                "id": 1002,
                "title": "Marketing Manager",
                "location": {"name": "NYC"},
                "content": "<p>Lead marketing campaigns for B2B SaaS</p>",
                "absolute_url": "https://boards.greenhouse.io/test-co/jobs/1002",
                "updated_at": "2026-03-14T10:00:00Z",
            },
        ]
    }


# ─── Pipeline Integration Tests ───────────────────────────────────────


class TestPipelineIntegration:
    """Pipeline end-to-end: fetch, dedup, score, persist."""

    @pytest.mark.asyncio
    async def test_pipeline_persists_jobs_with_correct_fields(self, live_app):
        """Jobs persisted to DB with correct normalised fields (DISC-05)."""
        app_instance, base_module = live_app
        source_id = await _seed_source_and_keywords(base_module)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_greenhouse_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            # Create a run row
            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)
                run_id = run.id

            ctx = RunContext(
                run_id=run_id,
                started_at=datetime.utcnow(),
                dry_run=False,
                triggered_by="manual",
                tz="UTC",
            )

            counts = await run_discovery(ctx, base_module.async_session)

        assert counts["discovered"] == 2
        assert counts["new"] == 2

        # Verify persisted jobs
        from app.discovery.models import Job
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Job).order_by(Job.id))
            jobs = list(result.scalars().all())

        assert len(jobs) == 2
        python_job = [j for j in jobs if "Python" in j.title][0]
        assert python_job.company == "test-co"
        assert python_job.source == "greenhouse"
        assert python_job.source_id == source_id
        assert python_job.fingerprint  # non-empty SHA256

    @pytest.mark.asyncio
    async def test_dedup_prevents_duplicates(self, live_app):
        """Running pipeline twice with same data creates no duplicates (DISC-06)."""
        app_instance, base_module = live_app
        await _seed_source_and_keywords(base_module)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_greenhouse_response()
        mock_resp.raise_for_status = MagicMock()

        from app.discovery.pipeline import run_discovery
        from app.runs.context import RunContext
        from app.db.models import Run
        from app.discovery.models import Job
        from sqlalchemy import select

        async def run_once():
            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)
                run_id = run.id

            ctx = RunContext(
                run_id=run_id,
                started_at=datetime.utcnow(),
                dry_run=False,
                triggered_by="manual",
                tz="UTC",
            )

            with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
                client_instance = AsyncMock()
                client_instance.get.return_value = mock_resp
                MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
                return await run_discovery(ctx, base_module.async_session)

        counts1 = await run_once()
        counts2 = await run_once()

        assert counts1["new"] == 2
        assert counts2["new"] == 0  # All deduped

        async with base_module.async_session() as session:
            result = await session.execute(select(Job))
            jobs = list(result.scalars().all())
        assert len(jobs) == 2  # Still only 2 rows

    @pytest.mark.asyncio
    async def test_scoring_and_status_assignment(self, live_app):
        """Jobs scored correctly; above threshold=matched, below=discovered (MATCH-01, MATCH-02)."""
        app_instance, base_module = live_app
        # threshold=60: job1 has python+react (2/3=67%) → matched; job2 has 0/3=0% → discovered
        await _seed_source_and_keywords(base_module, "python|react|typescript", threshold=60)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_greenhouse_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)

            ctx = RunContext(
                run_id=run.id,
                started_at=datetime.utcnow(),
                dry_run=False,
                triggered_by="manual",
                tz="UTC",
            )
            counts = await run_discovery(ctx, base_module.async_session)

        assert counts["matched"] >= 1

        from app.discovery.models import Job
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Job).order_by(Job.id))
            jobs = list(result.scalars().all())

        python_job = [j for j in jobs if "Python" in j.title][0]
        marketing_job = [j for j in jobs if "Marketing" in j.title][0]

        assert python_job.status == "matched"
        assert python_job.score >= 60
        assert marketing_job.status == "discovered"
        assert marketing_job.score < 60

    @pytest.mark.asyncio
    async def test_matched_keywords_stored_pipe_delimited(self, live_app):
        """Score and matched_keywords stored in DB (MATCH-03)."""
        app_instance, base_module = live_app
        await _seed_source_and_keywords(base_module, "python|react", threshold=40)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_greenhouse_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)

            ctx = RunContext(
                run_id=run.id, started_at=datetime.utcnow(),
                dry_run=False, triggered_by="manual", tz="UTC",
            )
            await run_discovery(ctx, base_module.async_session)

        from app.discovery.models import Job
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Job).order_by(Job.id))
            jobs = list(result.scalars().all())

        python_job = [j for j in jobs if "Python" in j.title][0]
        # matched_keywords is pipe-delimited
        assert "|" in python_job.matched_keywords or python_job.matched_keywords in ("python", "react")
        assert python_job.score > 0

    @pytest.mark.asyncio
    async def test_discovery_run_stats_created(self, live_app):
        """DiscoveryRunStats rows created per source."""
        app_instance, base_module = live_app
        await _seed_source_and_keywords(base_module)

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = _mock_greenhouse_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.return_value = mock_resp
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)

            ctx = RunContext(
                run_id=run.id, started_at=datetime.utcnow(),
                dry_run=False, triggered_by="manual", tz="UTC",
            )
            await run_discovery(ctx, base_module.async_session)

        from app.discovery.models import DiscoveryRunStats
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(DiscoveryRunStats))
            stats = list(result.scalars().all())

        assert len(stats) >= 1
        assert stats[0].discovered_count == 2

    @pytest.mark.asyncio
    async def test_source_error_does_not_block_others(self, live_app):
        """One source failing does not prevent other sources from completing."""
        app_instance, base_module = live_app
        from app.discovery.models import Source
        from app.settings.service import set_setting

        # Create two sources
        async with base_module.async_session() as session:
            s1 = Source(slug="good-co", source_type="greenhouse", enabled=True)
            s2 = Source(slug="bad-co", source_type="lever", enabled=True)
            session.add_all([s1, s2])
            await session.commit()
            await session.refresh(s1)
            await session.refresh(s2)

        async with base_module.async_session() as session:
            await set_setting(session, "keywords_csv", "python")
            await set_setting(session, "match_threshold", 50)

        good_resp = MagicMock(spec=httpx.Response)
        good_resp.status_code = 200
        good_resp.json.return_value = _mock_greenhouse_response()
        good_resp.raise_for_status = MagicMock()

        bad_resp = MagicMock(spec=httpx.Response)
        bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found", request=MagicMock(), response=MagicMock()
        )

        async def mock_get(url, **kwargs):
            if "greenhouse" in url:
                return good_resp
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock())

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.side_effect = mock_get
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)

            ctx = RunContext(
                run_id=run.id, started_at=datetime.utcnow(),
                dry_run=False, triggered_by="manual", tz="UTC",
            )
            # Should not raise despite one source failing
            counts = await run_discovery(ctx, base_module.async_session)

        # Good source jobs still persisted
        assert counts["new"] >= 1

    @pytest.mark.asyncio
    async def test_source_error_status_updated_in_db(self, live_app):
        """Source with fetch error gets status=error in DB."""
        app_instance, base_module = live_app
        from app.discovery.models import Source
        from app.settings.service import set_setting

        async with base_module.async_session() as session:
            s = Source(slug="fail-co", source_type="greenhouse", enabled=True)
            session.add(s)
            await session.commit()
            await session.refresh(s)
            source_id = s.id

        async with base_module.async_session() as session:
            await set_setting(session, "keywords_csv", "python")

        with patch("app.discovery.pipeline.httpx.AsyncClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.get.side_effect = httpx.TimeoutException("timeout")
            MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.discovery.pipeline import run_discovery
            from app.runs.context import RunContext
            from app.db.models import Run

            async with base_module.async_session() as session:
                run = Run(status="running", triggered_by="manual")
                session.add(run)
                await session.commit()
                await session.refresh(run)

            ctx = RunContext(
                run_id=run.id, started_at=datetime.utcnow(),
                dry_run=False, triggered_by="manual", tz="UTC",
            )
            await run_discovery(ctx, base_module.async_session)

        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Source).where(Source.id == source_id))
            source = result.scalar_one()
        assert source.last_fetch_status == "error"
        assert source.last_error_message is not None


# ─── Jobs Route Integration Tests ─────────────────────────────────────


class TestJobsRoutes:
    """Jobs page routes: list, sort, detail, queue."""

    async def _seed_jobs(self, base_module):
        """Seed two jobs directly for route tests."""
        from app.discovery.models import Job
        from app.discovery.scoring import job_fingerprint

        async with base_module.async_session() as session:
            j1 = Job(
                fingerprint=job_fingerprint("https://ex.com/1", "Python Dev", "co-a"),
                external_id="1",
                title="Python Dev",
                company="co-a",
                description="python react",
                url="https://ex.com/1",
                source="greenhouse",
                score=80,
                matched_keywords="python|react",
                status="matched",
            )
            j2 = Job(
                fingerprint=job_fingerprint("https://ex.com/2", "Sales Rep", "co-b"),
                external_id="2",
                title="Sales Rep",
                company="co-b",
                description="b2b saas sales",
                url="https://ex.com/2",
                source="lever",
                score=10,
                matched_keywords="",
                status="discovered",
            )
            session.add_all([j1, j2])
            await session.commit()
            await session.refresh(j1)
            await session.refresh(j2)
            return j1.id, j2.id

    @pytest.mark.asyncio
    async def test_jobs_page_returns_200(self, live_app):
        app_instance, base_module = live_app
        await self._seed_jobs(base_module)

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/jobs")
        assert resp.status_code == 200
        assert "Discovered Jobs" in resp.text
        assert "Python Dev" in resp.text

    @pytest.mark.asyncio
    async def test_jobs_sorted_by_score_desc(self, live_app):
        app_instance, base_module = live_app
        await self._seed_jobs(base_module)

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/jobs?sort=score&dir=desc")
        assert resp.status_code == 200
        body = resp.text
        # Python Dev (score 80) should appear before Sales Rep (score 10)
        pos_python = body.find("Python Dev")
        pos_sales = body.find("Sales Rep")
        assert pos_python < pos_sales

    @pytest.mark.asyncio
    async def test_job_detail_returns_inline_partial(self, live_app):
        app_instance, base_module = live_app
        j1_id, _ = await self._seed_jobs(base_module)

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(f"/jobs/{j1_id}/detail")
        assert resp.status_code == 200
        # Should contain keyword breakdown
        assert "python" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_queue_job_changes_status(self, live_app):
        app_instance, base_module = live_app
        _, j2_id = await self._seed_jobs(base_module)

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(f"/jobs/{j2_id}/queue")
        assert resp.status_code == 200

        from app.discovery.models import Job
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Job).where(Job.id == j2_id))
            job = result.scalar_one()
        assert job.status == "queued"


# ─── Sources Route Integration Tests ──────────────────────────────────


class TestSourcesRoutes:
    """Sources settings routes: CRUD, toggle, delete."""

    @pytest.mark.asyncio
    async def test_get_sources_returns_200(self, live_app):
        app_instance, _ = live_app

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/settings/sources")
        assert resp.status_code == 200
        assert "Sources" in resp.text

    @pytest.mark.asyncio
    async def test_add_valid_source(self, live_app):
        """POST with valid slug creates source (mock validation to succeed)."""
        app_instance, base_module = live_app

        with patch("app.web.routers.sources.validate_source", new_callable=AsyncMock) as mock_val:
            mock_val.return_value = (True, "")

            async with app_instance.router.lifespan_context(app_instance):
                transport = httpx.ASGITransport(app=app_instance)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/settings/sources",
                        data={"slug_or_url": "https://boards.greenhouse.io/stripe"},
                    )

        assert resp.status_code == 200
        # Should show success flash or the source in the list
        body = resp.text
        assert "stripe" in body.lower()

        # Verify persisted
        from app.discovery.models import Source
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Source))
            sources = list(result.scalars().all())
        assert len(sources) == 1
        assert sources[0].slug == "stripe"
        assert sources[0].source_type == "greenhouse"

    @pytest.mark.asyncio
    async def test_add_invalid_source_shows_error(self, live_app):
        """POST with invalid slug (validation fails) returns error, no source created."""
        app_instance, base_module = live_app

        with patch("app.web.routers.sources.validate_source", new_callable=AsyncMock) as mock_val:
            mock_val.return_value = (False, "Not found on Greenhouse")

            async with app_instance.router.lifespan_context(app_instance):
                transport = httpx.ASGITransport(app=app_instance)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.post(
                        "/settings/sources",
                        data={"slug_or_url": "https://boards.greenhouse.io/nonexistent"},
                    )

        assert resp.status_code == 200
        assert "Not found" in resp.text or "error" in resp.text.lower()

        # No source created
        from app.discovery.models import Source
        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Source))
            sources = list(result.scalars().all())
        assert len(sources) == 0

    @pytest.mark.asyncio
    async def test_toggle_source(self, live_app):
        """POST toggle changes enabled state."""
        app_instance, base_module = live_app
        from app.discovery.models import Source

        async with base_module.async_session() as session:
            s = Source(slug="toggle-co", source_type="lever", enabled=True)
            session.add(s)
            await session.commit()
            await session.refresh(s)
            source_id = s.id

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/settings/sources/{source_id}/toggle",
                    data={"enabled": "false"},
                )
        assert resp.status_code == 200

        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Source).where(Source.id == source_id))
            s = result.scalar_one()
        assert s.enabled is False

    @pytest.mark.asyncio
    async def test_delete_source(self, live_app):
        """DELETE removes source permanently."""
        app_instance, base_module = live_app
        from app.discovery.models import Source

        async with base_module.async_session() as session:
            s = Source(slug="del-co", source_type="ashby", enabled=True)
            session.add(s)
            await session.commit()
            await session.refresh(s)
            source_id = s.id

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.delete(f"/settings/sources/{source_id}")
        assert resp.status_code == 200

        from sqlalchemy import select

        async with base_module.async_session() as session:
            result = await session.execute(select(Source).where(Source.id == source_id))
            s = result.scalar_one_or_none()
        assert s is None


# ─── Dashboard Integration Tests ──────────────────────────────────────


class TestDashboardDiscovery:
    """Dashboard discovery summary + anomaly banner."""

    @pytest.mark.asyncio
    async def test_dashboard_with_discovery_summary(self, live_app):
        """GET / after a discovery run shows discovery summary."""
        app_instance, base_module = live_app
        from app.db.models import Run
        from app.discovery.models import DiscoveryRunStats, Source

        # Seed completed run with stats
        async with base_module.async_session() as session:
            source = Source(slug="dash-co", source_type="greenhouse", enabled=True)
            session.add(source)
            await session.commit()
            await session.refresh(source)

            run = Run(
                status="succeeded",
                triggered_by="manual",
                counts={"discovered": 5, "new": 3, "matched": 2, "anomalies": []},
                ended_at=datetime.utcnow(),
                duration_ms=100,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            stats = DiscoveryRunStats(
                run_id=run.id,
                source_id=source.id,
                discovered_count=5,
                matched_count=2,
            )
            session.add(stats)
            await session.commit()

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.text
        # Discovery summary should be present
        assert "dash-co" in body

    @pytest.mark.asyncio
    async def test_anomaly_banner_shown(self, live_app):
        """Anomaly banner appears when run has anomalies."""
        app_instance, base_module = live_app
        from app.db.models import Run
        from app.discovery.models import DiscoveryRunStats, Source

        async with base_module.async_session() as session:
            source = Source(slug="anom-co", source_type="lever", enabled=True)
            session.add(source)
            await session.commit()
            await session.refresh(source)

            run = Run(
                status="succeeded",
                triggered_by="scheduler",
                counts={
                    "discovered": 1,
                    "new": 1,
                    "matched": 0,
                    "anomalies": [
                        {"source_id": source.id, "slug": "anom-co", "today_count": 1, "rolling_avg": 50.0}
                    ],
                },
                ended_at=datetime.utcnow(),
                duration_ms=50,
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            stats = DiscoveryRunStats(
                run_id=run.id,
                source_id=source.id,
                discovered_count=1,
                matched_count=0,
            )
            session.add(stats)
            await session.commit()

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.text
        # Anomaly warning text should be present
        assert "anom-co" in body
        assert "20%" in body or "threshold" in body.lower()

    @pytest.mark.asyncio
    async def test_dismiss_anomaly_sets_cookie(self, live_app):
        """POST /dismiss-anomaly returns empty HTML with cookie."""
        app_instance, base_module = live_app
        from app.db.models import Run

        async with base_module.async_session() as session:
            run = Run(
                status="succeeded",
                triggered_by="manual",
                counts={"anomalies": [{"slug": "x", "today_count": 0, "rolling_avg": 50}]},
                ended_at=datetime.utcnow(),
                duration_ms=10,
            )
            session.add(run)
            await session.commit()

        async with app_instance.router.lifespan_context(app_instance):
            transport = httpx.ASGITransport(app=app_instance)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/dismiss-anomaly")
        assert resp.status_code == 200
        assert resp.text == "" or len(resp.text.strip()) == 0
        # Cookie should be set
        assert "dismissed_anomaly_run_id" in resp.headers.get("set-cookie", "")
