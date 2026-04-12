"""Unit tests for ``app.scheduler.rate_limit``."""

from __future__ import annotations

import pytest
from freezegun import freeze_time

from app.db.models import RateLimitCounter
from app.scheduler.rate_limit import RateLimiter, RateLimitExceeded


def test_invalid_delay_range_constructor() -> None:
    with pytest.raises(ValueError):
        RateLimiter(daily_cap=20, delay_min=0, delay_max=60, tz="UTC")
    with pytest.raises(ValueError):
        RateLimiter(daily_cap=20, delay_min=120, delay_max=30, tz="UTC")
    with pytest.raises(ValueError):
        RateLimiter(daily_cap=20, delay_min=30, delay_max=700, tz="UTC")
    with pytest.raises(ValueError):
        RateLimiter(daily_cap=-1, delay_min=30, delay_max=120, tz="UTC")


def test_random_action_delay_in_range() -> None:
    rl = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="UTC")
    for _ in range(200):
        d = rl.random_action_delay()
        assert 30.0 <= d <= 120.0


async def test_below_cap_precheck_passes(async_session) -> None:
    rl = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="UTC")
    # Seed today's counter at 5 via record_submission path.
    for _ in range(5):
        await rl.record_submission(async_session)
    # Should not raise.
    await rl.await_precheck(async_session)


async def test_at_cap_raises(async_session) -> None:
    rl = RateLimiter(daily_cap=3, delay_min=30, delay_max=120, tz="UTC")
    for _ in range(3):
        await rl.record_submission(async_session)
    with pytest.raises(RateLimitExceeded):
        await rl.await_precheck(async_session)


async def test_record_submission_increments(async_session) -> None:
    rl = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="UTC")
    a = await rl.record_submission(async_session)
    b = await rl.record_submission(async_session)
    assert a == 1
    assert b == 2


def test_today_local_uses_configured_tz() -> None:
    # 2026-04-11 07:30 UTC:
    # - Los Angeles (-07:00) → 2026-04-11 00:30 local (still the 11th)
    # - Tokyo (+09:00)        → 2026-04-11 16:30 local (still the 11th)
    with freeze_time("2026-04-11T07:30:00Z"):
        la = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="America/Los_Angeles")
        jp = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="Asia/Tokyo")
        assert la.today_local().isoformat() == "2026-04-11"
        assert jp.today_local().isoformat() == "2026-04-11"

    # 2026-04-11 05:00 UTC:
    # - Los Angeles (-07:00) → 2026-04-10 22:00 (the 10th)
    with freeze_time("2026-04-11T05:00:00Z"):
        la = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="America/Los_Angeles")
        assert la.today_local().isoformat() == "2026-04-10"


async def test_midnight_reset_is_idempotent(async_session) -> None:
    rl = RateLimiter(daily_cap=20, delay_min=30, delay_max=120, tz="UTC")
    await rl.midnight_reset(async_session)
    await rl.midnight_reset(async_session)
    # Exactly one row exists for today.
    from sqlalchemy import select

    result = await async_session.execute(select(RateLimitCounter))
    rows = list(result.scalars().all())
    assert len(rows) == 1
    assert rows[0].submitted_count == 0
