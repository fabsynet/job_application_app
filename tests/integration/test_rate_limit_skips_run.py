"""Integration: rate limiter blocks run at entry with a visible skipped row."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.models import RateLimitCounter, Run
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
async def svc_low_cap(async_session_factory):
    sched = _mock_apscheduler()
    ks = KillSwitch()
    rl = RateLimiter(daily_cap=2, delay_min=30, delay_max=120, tz="UTC")
    service = SchedulerService(
        scheduler=sched,
        killswitch=ks,
        rate_limiter=rl,
        session_factory=async_session_factory,
        tz="UTC",
    )
    yield service, rl, async_session_factory


async def test_under_cap_run_succeeds(svc_low_cap) -> None:
    service, _, session_factory = svc_low_cap
    await service.run_pipeline(triggered_by="manual")
    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "succeeded"


async def test_at_cap_run_is_skipped(svc_low_cap) -> None:
    service, rl, session_factory = svc_low_cap
    async with session_factory() as session:
        await rl.record_submission(session)
        await rl.record_submission(session)

    await service.run_pipeline(triggered_by="scheduler")

    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "skipped"
        assert rows[0].failure_reason == "rate_limit"
        assert rows[0].triggered_by == "scheduler"
        assert rows[0].ended_at is not None


async def test_record_submission_moves_counter(svc_low_cap) -> None:
    service, rl, session_factory = svc_low_cap
    async with session_factory() as session:
        n1 = await rl.record_submission(session)
        n2 = await rl.record_submission(session)
    assert (n1, n2) == (1, 2)

    await service.run_pipeline(triggered_by="manual")
    async with session_factory() as session:
        rows = (await session.execute(select(Run))).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "skipped"


async def test_midnight_reset_creates_new_day_row(
    async_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Across a simulated midnight boundary, reset creates a fresh counter.

    freezegun interacts poorly with asyncio's monotonic clock on Windows, so
    instead of freezing wall-clock time we monkeypatch ``today_local`` — the
    one method that feeds a local-TZ date into the counter row.
    """
    sched = _mock_apscheduler()
    ks = KillSwitch()
    rl = RateLimiter(daily_cap=2, delay_min=30, delay_max=120, tz="UTC")
    service = SchedulerService(
        scheduler=sched,
        killswitch=ks,
        rate_limiter=rl,
        session_factory=async_session_factory,
        tz="UTC",
    )

    # Day 1: simulate 2026-04-11 with one submission.
    from datetime import date as _date

    monkeypatch.setattr(rl, "today_local", lambda: _date(2026, 4, 11))
    async with async_session_factory() as session:
        await rl.record_submission(session)

    async with async_session_factory() as session:
        rows = (
            await session.execute(select(RateLimitCounter))
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].day == "2026-04-11"
        assert rows[0].submitted_count == 1

    # Day 2: advance to 2026-04-12, call midnight_reset.
    monkeypatch.setattr(rl, "today_local", lambda: _date(2026, 4, 12))
    async with async_session_factory() as session:
        await rl.midnight_reset(session)

    async with async_session_factory() as session:
        rows = (
            await session.execute(
                select(RateLimitCounter).order_by(RateLimitCounter.day)
            )
        ).scalars().all()
        days = [r.day for r in rows]
        assert "2026-04-11" in days
        assert "2026-04-12" in days
        new_day = next(r for r in rows if r.day == "2026-04-12")
        assert new_day.submitted_count == 0

    # New day → cap is fresh → run_pipeline succeeds.
    await service.run_pipeline(triggered_by="scheduler")
    async with async_session_factory() as session:
        runs = (await session.execute(select(Run))).scalars().all()
        assert len(runs) == 1
        assert runs[0].status == "succeeded"
