"""Tests for app.learning.needs_info — needs-info aggregation queries."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.needs_info import get_needs_info_detail, get_needs_info_jobs
from app.learning.service import (
    create_unknown_fields,
    resolve_unknown_field,
    save_answer,
)


# =========================================================================
# Helper
# =========================================================================

async def _create_job(
    session: AsyncSession, job_id: int = 1, status: str = "needs_info"
) -> int:
    from app.discovery.models import Job

    job = Job(
        id=job_id,
        fingerprint=f"fp-{job_id}",
        external_id=f"ext-{job_id}",
        source="test",
        company="TestCo",
        title=f"Job {job_id}",
        url=f"https://example.com/jobs/{job_id}",
        status=status,
    )
    session.add(job)
    await session.flush()
    return job.id


# =========================================================================
# get_needs_info_jobs
# =========================================================================


class TestGetNeedsInfoJobs:
    @pytest.mark.asyncio
    async def test_returns_needs_info_jobs(self, async_session: AsyncSession):
        j1 = await _create_job(async_session, 1, "needs_info")
        j2 = await _create_job(async_session, 2, "applied")

        await create_unknown_fields(
            async_session, j1,
            [{"field_label": "Q1"}, {"field_label": "Q2"}],
        )
        # Resolve one field
        sa = await save_answer(async_session, "Q1", "A1")
        from sqlalchemy import select
        from app.learning.models import UnknownField
        res = await async_session.execute(
            select(UnknownField).where(UnknownField.job_id == j1)
        )
        fields = res.scalars().all()
        await resolve_unknown_field(async_session, fields[0].id, sa.id)

        jobs = await get_needs_info_jobs(async_session)
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == j1
        assert jobs[0]["field_count"] == 2
        assert jobs[0]["unresolved_count"] == 1

    @pytest.mark.asyncio
    async def test_empty_when_no_needs_info(self, async_session: AsyncSession):
        await _create_job(async_session, 1, "applied")
        jobs = await get_needs_info_jobs(async_session)
        assert jobs == []

    @pytest.mark.asyncio
    async def test_job_with_no_fields(self, async_session: AsyncSession):
        await _create_job(async_session, 1, "needs_info")
        jobs = await get_needs_info_jobs(async_session)
        assert len(jobs) == 1
        assert jobs[0]["field_count"] == 0
        assert jobs[0]["unresolved_count"] == 0


# =========================================================================
# get_needs_info_detail
# =========================================================================


class TestGetNeedsInfoDetail:
    @pytest.mark.asyncio
    async def test_returns_job_with_fields(self, async_session: AsyncSession):
        j1 = await _create_job(async_session, 1)
        await create_unknown_fields(
            async_session, j1,
            [
                {"field_label": "Q1", "page_number": 1, "is_required": True},
                {"field_label": "Q2", "page_number": 2},
            ],
        )
        detail = await get_needs_info_detail(async_session, j1)
        assert detail is not None
        assert detail["job_id"] == j1
        assert len(detail["fields"]) == 2
        assert detail["unresolved_count"] == 2
        assert detail["resolved_count"] == 0
        # Ordered by page_number
        assert detail["fields"][0]["field_label"] == "Q1"
        assert detail["fields"][1]["field_label"] == "Q2"

    @pytest.mark.asyncio
    async def test_returns_none_for_nonexistent_job(self, async_session: AsyncSession):
        detail = await get_needs_info_detail(async_session, 999)
        assert detail is None

    @pytest.mark.asyncio
    async def test_shows_resolved_and_unresolved(self, async_session: AsyncSession):
        j1 = await _create_job(async_session, 1)
        created = await create_unknown_fields(
            async_session, j1,
            [{"field_label": "Q1"}, {"field_label": "Q2"}],
        )
        sa = await save_answer(async_session, "Q1", "A1")
        await resolve_unknown_field(async_session, created[0].id, sa.id)

        detail = await get_needs_info_detail(async_session, j1)
        assert detail["resolved_count"] == 1
        assert detail["unresolved_count"] == 1
