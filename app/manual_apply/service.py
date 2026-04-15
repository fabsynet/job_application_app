"""Manual-apply service: dedup-respecting Job row creation.

The single :func:`create_manual_job` entry point is idempotent by
design — it looks up the canonical ``job_fingerprint`` (the same hash
Phase 3 discovery uses) before inserting, so a user who pastes the
same URL twice gets the same Job back instead of a duplicate row.

Key contract:
  - A manual-apply Job is inserted with ``status='matched'`` regardless
    of keyword match score. This bypasses the match-threshold gate
    (MANL-04) but keeps the standard tailoring pipeline untouched:
    ``app.tailoring.service.get_queued_jobs`` already selects
    ``status IN ('matched', 'retailoring')`` so the next scheduler run
    picks the job up automatically.
  - ``score`` is stamped at 100 and ``matched_keywords`` at
    ``manual_paste`` so the Jobs list UI distinguishes pasted jobs from
    high-score auto-discovered ones at a glance.
  - No status transition is validated here because a new row has no
    prior state — ``assert_valid_transition`` applies to existing Job
    rows, not fresh inserts.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.discovery.scoring import job_fingerprint
from app.discovery.service import get_job_by_fingerprint
from app.manual_apply.fetcher import ParsedJob


async def check_duplicate(
    session: AsyncSession, parsed: ParsedJob
) -> Optional[Job]:
    """Return the existing Job for ``parsed`` if one already exists."""
    fp = job_fingerprint(parsed.url, parsed.title, parsed.company)
    return await get_job_by_fingerprint(session, fp)


async def create_manual_job(
    session: AsyncSession, parsed: ParsedJob
) -> Job:
    """Create (or return existing) Job for a manually-pasted URL.

    Idempotent: if a Job with the same canonical fingerprint already
    exists, returns it unchanged. Otherwise inserts a new row with
    ``status='matched'`` and commits.
    """
    fp = job_fingerprint(parsed.url, parsed.title, parsed.company)
    existing = await get_job_by_fingerprint(session, fp)
    if existing is not None:
        return existing

    job = Job(
        fingerprint=fp,
        external_id=parsed.external_id or parsed.url,
        title=parsed.title,
        company=parsed.company,
        description=parsed.description,
        description_html=parsed.description_html,
        url=parsed.url,
        source=parsed.source,
        score=100,
        matched_keywords="manual_paste",
        status="matched",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


__all__ = ["create_manual_job", "check_duplicate"]
