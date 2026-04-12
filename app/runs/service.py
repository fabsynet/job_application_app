"""CRUD for the ``runs`` table plus orphan cleanup.

These functions are the only path that writes to ``runs``. The scheduler
service calls :func:`create_run` at the start of every pipeline invocation,
:func:`finalize_run` on success/skip/error, :func:`mark_run_killed` from the
kill-switch cancellation path, and :func:`mark_orphans_failed` once at
lifespan startup to heal rows left as ``status='running'`` by a crashed
container.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Run

_EMPTY_COUNTS: dict[str, int] = {
    "discovered": 0,
    "matched": 0,
    "tailored": 0,
    "submitted": 0,
    "failed": 0,
}


async def create_run(
    session: AsyncSession,
    *,
    dry_run: bool,
    triggered_by: str,
) -> Run:
    """Insert a new ``Run`` row in ``status='running'`` and return it.

    The counts dict is pre-initialised with every canonical key at zero so
    downstream stages can ``counts["submitted"] += 1`` without a defensive
    ``setdefault``.
    """
    run = Run(
        status="running",
        dry_run=dry_run,
        triggered_by=triggered_by,
        counts=dict(_EMPTY_COUNTS),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def finalize_run(
    session: AsyncSession,
    run_id: int,
    *,
    status: str,
    failure_reason: Optional[str] = None,
    counts: Optional[dict[str, Any]] = None,
) -> None:
    """Close out a Run row with terminal state.

    Computes ``duration_ms`` from ``started_at``. If ``counts`` is supplied,
    it is *merged* into the existing counts dict (not replaced) so individual
    stages can finalise independently.
    """
    result = await session.execute(select(Run).where(Run.id == run_id))
    row = result.scalar_one()
    now = datetime.utcnow()
    row.ended_at = now
    if row.started_at is not None:
        delta = (now - row.started_at).total_seconds() * 1000.0
        row.duration_ms = int(delta)
    row.status = status
    if failure_reason is not None:
        row.failure_reason = failure_reason
    if counts:
        merged = dict(row.counts or {})
        merged.update(counts)
        row.counts = merged
    await session.commit()


async def mark_run_killed(session: AsyncSession, run_id: int) -> None:
    """Finalise a run as killed via the kill switch."""
    await finalize_run(
        session,
        run_id,
        status="failed",
        failure_reason="killed",
    )


async def mark_orphans_failed(session: AsyncSession) -> int:
    """Mark every ``Run(status='running')`` row as failed/crashed.

    Called exactly once during lifespan startup. Returns the number of rows
    updated, which lifespan logs for audit. The raw ``UPDATE`` is used instead
    of a per-row ORM path because we want the operation atomic and cheap.
    """
    result = await session.execute(
        text(
            "UPDATE runs "
            "SET status='failed', "
            "    failure_reason='crashed', "
            "    ended_at=CURRENT_TIMESTAMP "
            "WHERE status='running'"
        )
    )
    await session.commit()
    return int(result.rowcount or 0)


async def list_recent_runs(
    session: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Run]:
    """Return the most-recent Run rows ordered by ``started_at`` desc."""
    stmt = (
        select(Run)
        .order_by(Run.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "create_run",
    "finalize_run",
    "mark_run_killed",
    "mark_orphans_failed",
    "list_recent_runs",
]
