"""Applied-jobs service — counts, list, detail, download helpers.

All downstream of 05-01's state machine constants and 05-04's Submission
rows. No writes — this module is read-only for the dashboard.

Plan 05-08 Task 1. Backs the ``/applied`` dashboard (REVW-05..10, SC-5, SC-6).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.submission.models import Submission
from app.tailoring.models import TailoringRecord

log = structlog.get_logger(__name__)


# Whitelisted sort columns for the applied-jobs table. Anything else
# silently falls back to ``submitted_at desc`` — same forgiving pattern
# as ``app.review.service.REVIEW_SORT_COLUMNS``.
APPLIED_SORT_COLUMNS: dict[str, Any] = {
    "company": Job.company,
    "title": Job.title,
    "score": Job.score,
    "submitted_at": Submission.sent_at,
    "status": Job.status,
    "source": Job.source,
}


# Default statuses surfaced in the applied-jobs table.  Includes
# ``approved`` so unsent jobs (held by the daily cap or the
# manual-completion path) show up alongside genuinely submitted jobs —
# SC-5 explicit requirement.
DEFAULT_APPLIED_STATUSES: tuple[str, ...] = (
    "submitted",
    "approved",
    "failed",
    "skipped",
    "needs_info",
)


@dataclass
class StateCounts:
    """Per-status counts for one time window."""

    submitted: int = 0
    approved: int = 0
    failed: int = 0
    skipped: int = 0
    needs_info: int = 0
    tailored: int = 0


async def state_counts_for_window(
    session: AsyncSession,
    *,
    since: datetime,
) -> StateCounts:
    """Counts per ``Job.status`` for jobs whose ``first_seen_at >= since``.

    'Today' = ``since=midnight-local``; 'Last 7 days' = ``since=now-7d``.
    """
    stmt = (
        select(Job.status, func.count(Job.id))
        .where(Job.first_seen_at >= since)
        .group_by(Job.status)
    )
    rows = (await session.execute(stmt)).all()
    counts = StateCounts()
    for status, count in rows:
        if hasattr(counts, status):
            setattr(counts, status, int(count))
    return counts


async def list_applied_jobs(
    session: AsyncSession,
    *,
    sort_by: str = "submitted_at",
    sort_dir: str = "desc",
    status_filter: Optional[list[str]] = None,
    source_filter: Optional[list[str]] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Job, Optional[Submission], Optional[TailoringRecord]]], int]:
    """Return ``(rows, total)`` for the applied-jobs dashboard table.

    Includes BOTH ``submitted`` jobs (which have a ``Submission`` row)
    and ``approved`` jobs (which do not yet — manual-completion path per
    SC-5). The join is a LEFT OUTER on the latest ``Submission`` per job
    and on the latest ``TailoringRecord`` per job.
    """
    filter_states = list(status_filter) if status_filter else list(DEFAULT_APPLIED_STATUSES)

    # Latest Submission per job via a MAX(id) subquery.
    latest_sub_subq = (
        select(Submission.job_id, func.max(Submission.id).label("max_id"))
        .group_by(Submission.job_id)
        .subquery()
    )
    # Latest TailoringRecord per job via the same pattern.
    latest_rec_subq = (
        select(TailoringRecord.job_id, func.max(TailoringRecord.id).label("max_id"))
        .group_by(TailoringRecord.job_id)
        .subquery()
    )

    stmt = (
        select(Job, Submission, TailoringRecord)
        .join(latest_sub_subq, latest_sub_subq.c.job_id == Job.id, isouter=True)
        .join(
            Submission,
            Submission.id == latest_sub_subq.c.max_id,
            isouter=True,
        )
        .join(latest_rec_subq, latest_rec_subq.c.job_id == Job.id, isouter=True)
        .join(
            TailoringRecord,
            TailoringRecord.id == latest_rec_subq.c.max_id,
            isouter=True,
        )
        .where(Job.status.in_(filter_states))
    )
    if source_filter:
        stmt = stmt.where(Job.source.in_(source_filter))

    column = APPLIED_SORT_COLUMNS.get(sort_by, Submission.sent_at)
    direction = "desc" if (sort_dir or "desc").lower() != "asc" else "asc"
    if direction == "desc":
        stmt = stmt.order_by(column.desc().nullslast(), Job.id.desc())
    else:
        stmt = stmt.order_by(column.asc().nullslast(), Job.id.asc())
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    rows: list[tuple[Job, Optional[Submission], Optional[TailoringRecord]]] = [
        (r[0], r[1], r[2]) for r in result.all()
    ]

    # Separate total query — correct at v1 scale (<500 applied jobs).
    total_stmt = select(func.count(Job.id)).where(Job.status.in_(filter_states))
    if source_filter:
        total_stmt = total_stmt.where(Job.source.in_(source_filter))
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    return rows, total


async def get_applied_detail(
    session: AsyncSession, job_id: int
) -> dict:
    """Detail view — full JD, latest tailoring artifact, submission info.

    Returns an empty dict when the job does not exist so callers can 404.
    """
    job = await session.get(Job, job_id)
    if job is None:
        return {}

    # Latest tailoring record (reuse an inline query rather than
    # get_latest_tailoring to keep this module's dependency surface
    # narrow).
    rec_stmt = (
        select(TailoringRecord)
        .where(TailoringRecord.job_id == job_id)
        .order_by(TailoringRecord.id.desc())
        .limit(1)
    )
    record = (await session.execute(rec_stmt)).scalar_one_or_none()

    # Latest submission — may be None for approved-but-unsent jobs.
    sub_stmt = (
        select(Submission)
        .where(Submission.job_id == job_id)
        .order_by(Submission.id.desc())
        .limit(1)
    )
    submission = (await session.execute(sub_stmt)).scalar_one_or_none()

    cover_letter_text = ""
    if record is not None and record.cover_letter_path:
        try:
            from app.submission.builder import extract_cover_letter_plaintext

            cover_letter_text = extract_cover_letter_plaintext(record.cover_letter_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "applied.detail_cover_letter_failed",
                job_id=job_id,
                error=str(exc),
            )
            cover_letter_text = "(unable to read cover letter file)"

    tailored_preview_html = ""
    if record is not None and record.tailored_resume_path:
        try:
            from app.tailoring.preview import docx_to_html

            tailored_preview_html = docx_to_html(Path(record.tailored_resume_path))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "applied.detail_preview_failed",
                job_id=job_id,
                error=str(exc),
            )
            tailored_preview_html = "<p>(preview unavailable)</p>"

    return {
        "job": job,
        "record": record,
        "submission": submission,
        "cover_letter_text": cover_letter_text,
        "tailored_preview_html": tailored_preview_html,
    }


def applied_artifact_paths(
    record: Optional[TailoringRecord],
) -> dict[str, Optional[Path]]:
    """Return ``{'resume': Path|None, 'cover_letter': Path|None}``.

    Safe to call with ``record=None`` — both values come back as
    ``None`` rather than raising.
    """
    if record is None:
        return {"resume": None, "cover_letter": None}
    return {
        "resume": Path(record.tailored_resume_path) if record.tailored_resume_path else None,
        "cover_letter": Path(record.cover_letter_path) if record.cover_letter_path else None,
    }


__all__ = [
    "APPLIED_SORT_COLUMNS",
    "DEFAULT_APPLIED_STATUSES",
    "StateCounts",
    "state_counts_for_window",
    "list_applied_jobs",
    "get_applied_detail",
    "applied_artifact_paths",
]
