"""Integration: dry-run snapshot semantics through SchedulerService.run_pipeline.

The scheduler service is constructed directly against an in-memory DB with a
mock APScheduler, so these tests stay pure-python (no real cron firing).
"""

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
from app.settings.service import set_setting


def _mock_apscheduler() -> MagicMock:
    sched = MagicMock(name="AsyncIOScheduler")
    sched.running = True
    sched.pause_job = MagicMock()
    sched.resume_job = MagicMock()
    sched.get_job = MagicMock(return_value=None)
    return sched


@pytest_asyncio.fixture
async def svc(async_session_factory):
    """Build a real SchedulerService bound to an in-memory DB + mock scheduler."""
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
    yield service, async_session_factory


async def test_dry_run_false_stamps_false(svc) -> None:
    service, session_factory = svc
    async with session_factory() as session:
        await set_setting(session, "dry_run", False)

    await service.run_pipeline(triggered_by="manual")

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].dry_run is False
        assert rows[0].status == "succeeded"
        assert rows[0].triggered_by == "manual"


async def test_dry_run_true_stamps_true(svc) -> None:
    service, session_factory = svc
    async with session_factory() as session:
        await set_setting(session, "dry_run", True)

    await service.run_pipeline(triggered_by="scheduler")

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].dry_run is True
        assert rows[0].status == "succeeded"


async def test_mid_run_toggle_does_not_retroactively_change_current_run(svc) -> None:
    """A toggle of Settings.dry_run mid-run must not relabel the in-flight row."""
    service, session_factory = svc
    async with session_factory() as session:
        await set_setting(session, "dry_run", False)

    # Kick off a run; while its _execute_stub is in its 0.05s sleep, flip the
    # dry_run flag. The already-created Run row should stay dry_run=False.
    run_task = asyncio.create_task(service.run_pipeline(triggered_by="manual"))
    # Wait for the run to create its row and enter _execute_stub.
    for _ in range(50):
        await asyncio.sleep(0.005)
        if service._current_task is not None:
            break
    async with session_factory() as session:
        await set_setting(session, "dry_run", True)
    await run_task

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].dry_run is False  # snapshot, not mid-run toggle
        assert rows[0].status == "succeeded"
