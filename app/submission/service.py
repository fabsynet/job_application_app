"""Phase 5 submission service — DB CRUD + idempotency guards + state transitions.

This module owns every write against ``submissions`` plus the single
point of truth for ``Job.status`` writes during Plan 05-04's submission
pipeline stage. Strategies (05-03) and notification senders (05-07) are
stateless — they do not touch the DB — so every side effect generated
by a submit attempt funnels through the helpers below.

Three groups of helpers:

1. **Submission row CRUD** — :func:`insert_pending`, :func:`mark_sent`,
   :func:`mark_failed`. Each function owns exactly one UPDATE/INSERT and
   is wrapped to interoperate with the partial UNIQUE index
   ``ux_submissions_job_sent`` from Plan 05-01 (SC-7). Idempotent
   duplicate detections surface as :class:`IdempotentDuplicate` rather
   than raw SQLAlchemy errors so the pipeline can no-op cleanly.

2. **Queue reads** — :func:`list_approved_jobs` and
   :func:`list_tailored_jobs` return the rows ``run_submission``
   iterates over. Both are ordered by ``first_seen_at`` ASC so the
   oldest job in the queue drains first (predictable + fair).

3. **State transition** — :func:`flip_job_status` is the only place in
   Phase 5 code that is allowed to write ``Job.status``. It validates
   the transition via :func:`app.review.states.assert_valid_transition`
   before persisting, and skips the write entirely if the current
   value equals the target (another idempotency belt).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.review.states import assert_valid_transition
from app.submission.models import Submission
from app.tailoring.models import TailoringRecord

log = structlog.get_logger(__name__)


class IdempotentDuplicate(Exception):
    """Raised when a ``status='sent'`` write races the partial UNIQUE index.

    The partial UNIQUE index ``ux_submissions_job_sent`` on
    ``submissions (job_id) WHERE status = 'sent'`` guarantees at most
    one successful row per job. Normally the pipeline serialises
    through ``SchedulerService._lock`` so this cannot fire, but if a
    future code path adds a second submission entry point (or a
    manual force-run races the scheduler) the second ``mark_sent``
    call trips the index and surfaces as this exception. The pipeline
    catches it, logs ``submission_idempotent_duplicate`` at WARN, and
    returns without emitting a second notification.
    """


# ---------------------------------------------------------------------------
# Submission row CRUD
# ---------------------------------------------------------------------------


async def insert_pending(
    session: AsyncSession,
    *,
    job_id: int,
    tailoring_record_id: int,
    smtp_from: str,
    smtp_to: str,
    subject: str,
    attachment_filename: str,
    attempt: int = 1,
    submitter: str = "email",
) -> Submission:
    """Insert a fresh ``Submission`` row with ``status='pending'``.

    Commits on success. The row persists even if the subsequent send
    fails so the audit trail always contains the attempt. The pipeline
    immediately transitions the row to ``sent`` or ``failed`` via the
    matching helper below — pending rows are transient by design and
    any that survive a crash are surfaced in the dashboard under
    ``status='pending'``.
    """
    row = Submission(
        job_id=job_id,
        tailoring_record_id=tailoring_record_id,
        attempt=attempt,
        status="pending",
        smtp_from=smtp_from,
        smtp_to=smtp_to,
        subject=subject,
        attachment_filename=attachment_filename,
        submitter=submitter,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise RuntimeError(
            f"failed to insert pending submission for job_id={job_id}: {exc}"
        ) from exc
    await session.refresh(row)
    return row


async def mark_sent(session: AsyncSession, submission_id: int) -> None:
    """Flip a pending submission row to ``status='sent'``.

    Stamps ``sent_at`` with ``datetime.utcnow()``. On IntegrityError
    (the partial UNIQUE index fires when another row already holds
    ``status='sent'`` for the same job), rolls back and raises
    :class:`IdempotentDuplicate` so the pipeline can no-op.
    """
    row = await session.get(Submission, submission_id)
    if row is None:
        raise ValueError(f"submission {submission_id} not found")
    row.status = "sent"
    row.sent_at = datetime.utcnow()
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        log.warning(
            "submission_idempotent_duplicate",
            submission_id=submission_id,
            job_id=row.job_id,
        )
        raise IdempotentDuplicate(
            f"another submission already marked sent for job_id={row.job_id}"
        ) from exc


async def mark_failed(
    session: AsyncSession,
    submission_id: int,
    *,
    error_class: str,
    error_message: str,
    failure_signature: Optional[str] = None,
) -> None:
    """Flip a pending submission row to ``status='failed'``.

    Records the classified ``error_class`` (stable string) and the
    canonicalised ``failure_signature`` (sha256 hex digest from
    :func:`app.submission.suppression.build_signature`). The raw
    ``error_message`` is stored verbatim for forensic value — the
    signature itself is the canonicalised hash.
    """
    row = await session.get(Submission, submission_id)
    if row is None:
        raise ValueError(f"submission {submission_id} not found")
    row.status = "failed"
    row.error_class = error_class
    row.error_message = error_message
    row.failure_signature = failure_signature
    await session.commit()


# ---------------------------------------------------------------------------
# Queue reads
# ---------------------------------------------------------------------------


async def list_tailored_jobs(
    session: AsyncSession,
) -> list[tuple[Job, TailoringRecord]]:
    """Return ``(Job, latest_record)`` pairs for every ``status='tailored'`` job.

    Used by the auto-mode branch of ``run_submission`` to decide which
    jobs pass the holdout check and can be auto-approved. Each pair's
    ``TailoringRecord`` is the latest *completed* record for that job;
    jobs without a completed record are skipped.
    """
    stmt = (
        select(Job)
        .where(Job.status == "tailored")
        .order_by(Job.first_seen_at.asc())
    )
    result = await session.execute(stmt)
    jobs = list(result.scalars().all())

    pairs: list[tuple[Job, TailoringRecord]] = []
    for job in jobs:
        rec_stmt = (
            select(TailoringRecord)
            .where(
                TailoringRecord.job_id == job.id,
                TailoringRecord.status == "completed",
            )
            .order_by(TailoringRecord.version.desc())
            .limit(1)
        )
        record = (await session.execute(rec_stmt)).scalar_one_or_none()
        if record is not None:
            pairs.append((job, record))
    return pairs


async def list_approved_jobs(
    session: AsyncSession,
) -> list[tuple[Job, TailoringRecord]]:
    """Return ``(Job, latest_record)`` pairs for the drainable approved queue.

    Ordered by ``Job.first_seen_at`` ASC so the oldest approved job
    goes first — this makes daily-cap-halt predictable (tomorrow's
    run resumes where today stopped). Jobs without a completed
    tailoring record are dropped because there is nothing to send.
    """
    stmt = (
        select(Job)
        .where(Job.status == "approved")
        .order_by(Job.first_seen_at.asc())
    )
    result = await session.execute(stmt)
    jobs = list(result.scalars().all())

    pairs: list[tuple[Job, TailoringRecord]] = []
    for job in jobs:
        rec_stmt = (
            select(TailoringRecord)
            .where(
                TailoringRecord.job_id == job.id,
                TailoringRecord.status == "completed",
            )
            .order_by(TailoringRecord.version.desc())
            .limit(1)
        )
        record = (await session.execute(rec_stmt)).scalar_one_or_none()
        if record is not None:
            pairs.append((job, record))
    return pairs


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


async def flip_job_status(
    session: AsyncSession,
    job_id: int,
    target_status: str,
    *,
    reason: Optional[str] = None,
) -> None:
    """Transition ``Job.status`` to ``target_status`` with guard.

    Single point of truth for ``Job.status`` writes in Phase 5. Reads
    the current value, validates the transition via
    :func:`app.review.states.assert_valid_transition`, then writes.
    If current equals target, it is a no-op (idempotent).
    """
    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    current = job.status
    if current == target_status:
        return  # idempotent no-op
    assert_valid_transition(current, target_status)
    job.status = target_status
    await session.commit()
    log.info(
        "job_status_flipped",
        job_id=job_id,
        from_status=current,
        to_status=target_status,
        reason=reason,
    )


__all__ = [
    "IdempotentDuplicate",
    "insert_pending",
    "mark_sent",
    "mark_failed",
    "list_tailored_jobs",
    "list_approved_jobs",
    "flip_job_status",
]
