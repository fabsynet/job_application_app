"""Needs-info aggregation: jobs with unresolved unknown fields.

Provides the data behind the "needs info" dashboard section — a list
of jobs that have at least one unknown field the user hasn't answered,
plus a detail view for resolving them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, func, select

from app.discovery.models import Job
from app.learning.models import UnknownField

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def get_needs_info_jobs(
    session: "AsyncSession",
) -> list[dict]:
    """Return jobs with status ``needs_info``, each with unknown-field count.

    Each dict contains:
    - ``job_id``, ``title``, ``company``, ``url``
    - ``field_count``: total unknown fields
    - ``unresolved_count``: fields still unresolved
    """
    # Subquery: count fields per job.
    total_sq = (
        select(
            UnknownField.job_id,
            func.count(UnknownField.id).label("field_count"),
            func.sum(
                # SQLite doesn't have native bool; resolved is 0/1.
                case((UnknownField.resolved == False, 1), else_=0)  # noqa: E712
            ).label("unresolved_count"),
        )
        .group_by(UnknownField.job_id)
        .subquery()
    )

    stmt = (
        select(
            Job.id.label("job_id"),
            Job.title,
            Job.company,
            Job.url,
            total_sq.c.field_count,
            total_sq.c.unresolved_count,
        )
        .outerjoin(total_sq, Job.id == total_sq.c.job_id)
        .where(Job.status == "needs_info")
        .order_by(Job.id.desc())
    )

    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "job_id": r.job_id,
            "title": r.title,
            "company": r.company,
            "url": r.url,
            "field_count": r.field_count or 0,
            "unresolved_count": r.unresolved_count or 0,
        }
        for r in rows
    ]


async def get_needs_info_detail(
    session: "AsyncSession",
    job_id: int,
) -> dict | None:
    """Return a single job with all its unknown fields (resolved + unresolved).

    Returns None if the job doesn't exist.
    """
    job_result = await session.execute(
        select(Job).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        return None

    fields_result = await session.execute(
        select(UnknownField)
        .where(UnknownField.job_id == job_id)
        .order_by(UnknownField.page_number, UnknownField.id)
    )
    fields = fields_result.scalars().all()

    resolved_count = sum(1 for f in fields if f.resolved)
    unresolved_count = sum(1 for f in fields if not f.resolved)

    return {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "url": job.url,
        "status": job.status,
        "fields": [
            {
                "id": f.id,
                "field_label": f.field_label,
                "field_type": f.field_type,
                "field_options": f.field_options,
                "screenshot_path": f.screenshot_path,
                "page_number": f.page_number,
                "is_required": f.is_required,
                "resolved": f.resolved,
                "saved_answer_id": f.saved_answer_id,
            }
            for f in fields
        ],
        "resolved_count": resolved_count,
        "unresolved_count": unresolved_count,
    }


__all__ = [
    "get_needs_info_jobs",
    "get_needs_info_detail",
]
