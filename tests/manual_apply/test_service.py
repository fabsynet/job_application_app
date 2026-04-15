"""Unit tests for :mod:`app.manual_apply.service`."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.discovery.models import Job
from app.discovery.scoring import job_fingerprint
from app.manual_apply.fetcher import ParsedJob
from app.manual_apply.service import check_duplicate, create_manual_job


def _sample(**overrides) -> ParsedJob:
    defaults = dict(
        title="Senior Backend Engineer",
        company="Stripe",
        description="Build payment APIs in Python.",
        description_html="<p>Build payment APIs in Python.</p>",
        url="https://boards.greenhouse.io/stripe/jobs/123",
        source="greenhouse",
        external_id="/stripe/jobs/123",
    )
    defaults.update(overrides)
    return ParsedJob(**defaults)


@pytest.mark.asyncio
async def test_create_manual_job_sets_status_matched_and_score_100(
    async_session,
):
    parsed = _sample()
    job = await create_manual_job(async_session, parsed)
    assert job.id is not None
    assert job.status == "matched"
    assert job.score == 100
    assert job.matched_keywords == "manual_paste"
    assert job.source == "greenhouse"
    assert job.title == "Senior Backend Engineer"
    assert job.company == "Stripe"
    assert job.fingerprint == job_fingerprint(
        parsed.url, parsed.title, parsed.company
    )


@pytest.mark.asyncio
async def test_create_manual_job_dedupes_via_fingerprint(async_session):
    parsed = _sample()
    first = await create_manual_job(async_session, parsed)
    second = await create_manual_job(async_session, parsed)
    assert first.id == second.id

    count = (
        await async_session.execute(select(func.count()).select_from(Job))
    ).scalar_one()
    assert count == 1


@pytest.mark.asyncio
async def test_check_duplicate_returns_existing_job(async_session):
    parsed = _sample()
    first = await create_manual_job(async_session, parsed)
    found = await check_duplicate(async_session, parsed)
    assert found is not None
    assert found.id == first.id


@pytest.mark.asyncio
async def test_check_duplicate_returns_none_for_unseen(async_session):
    parsed = _sample()
    found = await check_duplicate(async_session, parsed)
    assert found is None


@pytest.mark.asyncio
async def test_create_manual_job_bypasses_keyword_threshold(async_session):
    """Even with an empty description, the Job lands as ``matched``.

    This locks in MANL-04 — manual-apply jobs skip the discovery score
    gate so they enter the tailoring pipeline regardless of keyword
    overlap.
    """
    parsed = _sample(description="")
    job = await create_manual_job(async_session, parsed)
    assert job.status == "matched"
    assert job.score == 100
