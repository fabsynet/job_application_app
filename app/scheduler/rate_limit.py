"""Global rate limiter: 20/day cap + 30-120s action delays + TZ-aware reset.

RESEARCH.md Pattern 5. Per CONTEXT.md: the cap is a single global number
(not per-source), the action delay is a uniform jitter picked per action, and
the counter resets at local-TZ midnight via an APScheduler cron job calling
:meth:`RateLimiter.midnight_reset`. The DB-backed counter lives in
``rate_limit_counters`` keyed by ISO date string in the container's local
timezone, so "today's row" is a cheap lookup by primary key.
"""

from __future__ import annotations

import random
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RateLimitCounter


class RateLimitExceeded(Exception):
    """Raised by :meth:`RateLimiter.await_precheck` when today's cap is met."""


class RateLimiter:
    """Daily submission cap + randomised action delay.

    Instances are per-process singletons owned by the FastAPI lifespan. The
    class is deliberately small — it holds config, reads/writes one DB row
    per call, and exposes :meth:`random_action_delay` for Phase 6 browser
    stages to sleep between UI actions.
    """

    def __init__(
        self,
        daily_cap: int,
        delay_min: int,
        delay_max: int,
        tz: str,
    ) -> None:
        if daily_cap < 0:
            raise ValueError("daily_cap must be >= 0")
        if delay_min <= 0:
            raise ValueError(f"delay_min must be > 0, got {delay_min}")
        if delay_max <= delay_min:
            raise ValueError(
                f"delay_max ({delay_max}) must be > delay_min ({delay_min})"
            )
        if delay_max > 600:
            raise ValueError(f"delay_max must be <= 600s, got {delay_max}")
        self.daily_cap = daily_cap
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.tz = ZoneInfo(tz)

    def today_local(self) -> date:
        """Return today's date in the configured local timezone."""
        return datetime.now(self.tz).date()

    async def _get_or_create_counter(
        self, session: AsyncSession
    ) -> RateLimitCounter:
        day_str = self.today_local().isoformat()
        row = (
            await session.execute(
                select(RateLimitCounter).where(RateLimitCounter.day == day_str)
            )
        ).scalar_one_or_none()
        if row is None:
            row = RateLimitCounter(day=day_str, submitted_count=0)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def await_precheck(self, session: AsyncSession) -> None:
        """Raise :class:`RateLimitExceeded` if today's cap has been met.

        Called by :meth:`SchedulerService.run_pipeline` before any Run row is
        created so the operator sees a clean ``status='skipped'`` entry rather
        than a phantom running row.
        """
        row = await self._get_or_create_counter(session)
        if row.submitted_count >= self.daily_cap:
            raise RateLimitExceeded(
                f"daily cap {self.daily_cap} reached "
                f"({row.submitted_count} submitted)"
            )

    async def record_submission(self, session: AsyncSession) -> int:
        """Increment today's counter by one and return the new value.

        Phase 6 browser stages call this after each successful application
        submission. Phase 1 tests exercise it directly.
        """
        row = await self._get_or_create_counter(session)
        row.submitted_count += 1
        await session.commit()
        await session.refresh(row)
        return row.submitted_count

    def random_action_delay(self) -> float:
        """Return a uniformly-random delay in ``[delay_min, delay_max]``.

        Phase 6 stages ``await asyncio.sleep(rate_limiter.random_action_delay())``
        between UI actions. Phase 1 only verifies the range via unit tests.
        """
        return random.uniform(self.delay_min, self.delay_max)

    async def midnight_reset(self, session: AsyncSession) -> None:
        """Ensure today's counter row exists with count 0.

        Registered as an APScheduler cron job at ``hour=0 minute=0`` in the
        local timezone. The implementation is deliberately idempotent: if
        today's row already exists (from an earlier :meth:`await_precheck`
        call in the first second of the new day), this is a no-op.
        """
        await self._get_or_create_counter(session)


__all__ = ["RateLimiter", "RateLimitExceeded"]
