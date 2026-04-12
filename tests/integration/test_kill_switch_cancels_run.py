"""Integration: kill-switch cancels the in-flight task and marks Run failed/killed."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import Run
from app.scheduler.killswitch import KillSwitch
from app.scheduler.rate_limit import RateLimiter
from app.scheduler.service import SchedulerService


def _mock_apscheduler() -> MagicMock:
    sched = MagicMock(name="AsyncIOScheduler")
    sched.running = True
    sched.pause_job = MagicMock()
    sched.resume_job = MagicMock()
    sched.get_job = MagicMock(return_value=None)
    return sched


@pytest_asyncio.fixture
async def svc(async_session_factory):
    sched = _mock_apscheduler()
    ks = KillSwitch()
    rl = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="UTC")
    service = SchedulerService(
        scheduler=sched,
        killswitch=ks,
        rate_limiter=rl,
        session_factory=async_session_factory,
        tz="UTC",
    )
    yield service, ks, async_session_factory


async def test_engage_cancels_in_flight(svc) -> None:
    service, ks, session_factory = svc

    # Replace _execute_stub with a long-running coroutine that checkpoints
    # the kill-switch every 10ms.
    async def long_stub(ctx):
        for _ in range(500):
            await ks.raise_if_engaged()
            await asyncio.sleep(0.01)

    service._execute_stub = long_stub  # type: ignore[method-assign]

    run_task = asyncio.create_task(service.run_pipeline(triggered_by="manual"))

    # Wait for the inner task to exist.
    for _ in range(100):
        await asyncio.sleep(0.005)
        if service._current_task is not None:
            break
    assert service._current_task is not None

    async with session_factory() as session:
        await ks.engage(service, session)

    # run_pipeline swallows CancelledError at its boundary, so awaiting
    # returns None cleanly.
    await run_task

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert rows[0].failure_reason == "killed"
        assert rows[0].ended_at is not None


async def test_engage_before_run_skips_entirely(svc) -> None:
    service, ks, session_factory = svc
    async with session_factory() as session:
        await ks.engage(service, session)

    await service.run_pipeline(triggered_by="scheduler")

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert rows == []  # no Run row created at all


async def test_release_allows_new_runs(svc) -> None:
    service, ks, session_factory = svc
    async with session_factory() as session:
        await ks.engage(service, session)
        await ks.release(service, session)

    await service.run_pipeline(triggered_by="manual")

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "succeeded"
