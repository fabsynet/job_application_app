"""Discovery service: CRUD for sources, jobs, dedup, anomaly detection.

Provides all database operations for the discovery subsystem. Sources are
ATS boards the user wants to monitor; jobs are normalised postings fetched
from those sources; DiscoveryRunStats tracks per-source counts per run for
rolling-average anomaly detection.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import DiscoveryRunStats, Job, Source


# ---------------------------------------------------------------------------
# Source CRUD
# ---------------------------------------------------------------------------

async def get_enabled_sources(session: AsyncSession) -> list[Source]:
    """Return all Source rows where ``enabled=True``."""
    result = await session.execute(
        select(Source).where(Source.enabled == True).order_by(Source.created_at)  # noqa: E712
    )
    return list(result.scalars().all())


async def get_all_sources(session: AsyncSession) -> list[Source]:
    """Return all Source rows ordered by creation date (newest first)."""
    result = await session.execute(
        select(Source).order_by(Source.created_at.desc())
    )
    return list(result.scalars().all())


async def create_source(
    session: AsyncSession,
    slug: str,
    source_type: str,
    display_name: str,
) -> Source:
    """Create and persist a new Source row."""
    source = Source(
        slug=slug,
        source_type=source_type,
        display_name=display_name,
        enabled=True,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def toggle_source(
    session: AsyncSession,
    source_id: int,
    enabled: bool,
) -> Optional[Source]:
    """Toggle the enabled flag on a Source row."""
    result = await session.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        source.enabled = enabled
        await session.commit()
        await session.refresh(source)
    return source


async def delete_source(
    session: AsyncSession,
    source_id: int,
) -> None:
    """Delete a Source row by ID."""
    result = await session.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        await session.delete(source)
        await session.commit()


async def update_source_fetch_status(
    session: AsyncSession,
    source_id: int,
    status: str,
    error_msg: Optional[str] = None,
) -> None:
    """Mark a source with its last fetch status (``ok`` or ``error``)."""
    result = await session.execute(
        select(Source).where(Source.id == source_id)
    )
    source = result.scalar_one_or_none()
    if source is not None:
        source.last_fetched_at = datetime.utcnow()
        source.last_fetch_status = status
        source.last_error_message = error_msg
        await session.commit()


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

async def get_job_by_fingerprint(
    session: AsyncSession, fingerprint: str,
) -> Optional[Job]:
    """Look up a job by its dedup fingerprint. Returns None if not found."""
    result = await session.execute(
        select(Job).where(Job.fingerprint == fingerprint)
    )
    return result.scalar_one_or_none()


async def create_job(session: AsyncSession, **kwargs: Any) -> Job:
    """Insert a normalised job row."""
    job = Job(**kwargs)
    session.add(job)
    # Caller is responsible for committing (batch commit after loop)
    return job


async def list_jobs(
    session: AsyncSession,
    *,
    sort_by: str = "first_seen_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[Job]:
    """Return jobs for the UI table with server-side sorting."""
    # Whitelist of sortable columns
    column_map = {
        "title": Job.title,
        "company": Job.company,
        "location": Job.location,
        "source": Job.source,
        "score": Job.score,
        "posted_date": Job.posted_date,
        "first_seen_at": Job.first_seen_at,
        "status": Job.status,
    }
    col = column_map.get(sort_by, Job.first_seen_at)
    order = col.desc() if sort_dir == "desc" else col.asc()

    stmt = select(Job).order_by(order).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_job_detail(
    session: AsyncSession, job_id: int,
) -> Optional[Job]:
    """Fetch a single job with all fields for the inline detail view."""
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    return result.scalar_one_or_none()


async def update_job_status(
    session: AsyncSession, job_id: int, status: str,
) -> Optional[Job]:
    """Update a job's status (e.g. manual queue action)."""
    result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is not None:
        job.status = status
        await session.commit()
        await session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# DiscoveryRunStats
# ---------------------------------------------------------------------------

async def save_discovery_stats(
    session: AsyncSession,
    run_id: int,
    source_id: int,
    discovered: int,
    matched: int,
    error: Optional[str] = None,
) -> DiscoveryRunStats:
    """Persist per-source run stats for anomaly detection."""
    stats = DiscoveryRunStats(
        run_id=run_id,
        source_id=source_id,
        discovered_count=discovered,
        matched_count=matched,
        error=error,
    )
    session.add(stats)
    await session.commit()
    await session.refresh(stats)
    return stats


async def get_rolling_average(
    session: AsyncSession,
    source_id: int,
    days: int = 7,
) -> Optional[float]:
    """Return the rolling average of discovered_count for a source.

    Returns ``None`` if fewer than 3 data points exist (to avoid false
    positives on newly added sources per RESEARCH.md Pitfall 7).
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(
            func.count(DiscoveryRunStats.id).label("cnt"),
            func.avg(DiscoveryRunStats.discovered_count).label("avg"),
        )
        .where(
            DiscoveryRunStats.source_id == source_id,
            DiscoveryRunStats.created_at >= cutoff,
            DiscoveryRunStats.error.is_(None),  # exclude errored runs
        )
    )
    result = await session.execute(stmt)
    row = result.one()
    count = row.cnt or 0
    if count < 3:
        return None
    return float(row.avg)


__all__ = [
    "get_enabled_sources",
    "get_all_sources",
    "create_source",
    "toggle_source",
    "delete_source",
    "update_source_fetch_status",
    "get_job_by_fingerprint",
    "create_job",
    "list_jobs",
    "get_job_detail",
    "update_job_status",
    "save_discovery_stats",
    "get_rolling_average",
]
