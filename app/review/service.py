"""Phase 5 review queue service layer.

Owns every read/write that backs the review-queue UI: list/sort/filter,
single + batch approve, reject (skip / re-tailor), inline DOCX edit, and
drawer detail (diff + edit form). Every status write goes through
:func:`app.review.states.assert_valid_transition` so the UI cannot drive
the state machine into an illegal transition (e.g. ``submitted -> matched``).

Plan 05-05 Task 1.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.review.docx_edit import apply_user_edits, extract_sections_from_docx
from app.review.states import assert_valid_transition
from app.tailoring.models import TailoringRecord

log = structlog.get_logger(__name__)


# Statuses surfaced in the review queue table by default.
DEFAULT_REVIEW_STATUSES: tuple[str, ...] = (
    "tailored",
    "pending_review",
    "approved",
    "retailoring",
)


# Whitelisted sort columns. Anything else falls back to ``tailored_at desc``
# (no exception — same forgiving pattern as ``app.discovery.service.list_jobs``).
REVIEW_SORT_COLUMNS: dict[str, Any] = {
    "company": Job.company,
    "title": Job.title,
    "score": Job.score,
    "tailored_at": TailoringRecord.created_at,
    "status": Job.status,
}


# ---------------------------------------------------------------------------
# Queue listing
# ---------------------------------------------------------------------------


async def list_review_queue(
    session: AsyncSession,
    *,
    sort_by: str = "tailored_at",
    sort_dir: str = "desc",
    status_filter: Optional[list[str]] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Job, TailoringRecord]], int]:
    """List ``(job, latest_tailoring_record)`` rows for the review queue.

    Joins each Job to its highest-id ``TailoringRecord`` via a per-job
    ``MAX(id)`` subquery (one record per job, the most recent attempt).

    Returns ``(rows, total_count)``. Unknown ``sort_by`` columns silently
    fall back to ``tailored_at desc`` so a tampered query string never
    500s the page.
    """
    statuses = list(status_filter) if status_filter else list(DEFAULT_REVIEW_STATUSES)

    # Latest TailoringRecord per job_id via MAX(id) subquery.
    latest_subq = (
        select(
            TailoringRecord.job_id.label("job_id"),
            func.max(TailoringRecord.id).label("max_id"),
        )
        .group_by(TailoringRecord.job_id)
        .subquery()
    )

    base_stmt = (
        select(Job, TailoringRecord)
        .join(latest_subq, latest_subq.c.job_id == Job.id)
        .join(TailoringRecord, TailoringRecord.id == latest_subq.c.max_id)
        .where(Job.status.in_(statuses))
    )

    column = REVIEW_SORT_COLUMNS.get(sort_by, TailoringRecord.created_at)
    direction = "desc" if (sort_dir or "desc").lower() != "asc" else "asc"
    if direction == "desc":
        ordered_stmt = base_stmt.order_by(column.desc())
    else:
        ordered_stmt = base_stmt.order_by(column.asc())

    paged_stmt = ordered_stmt.limit(limit).offset(offset)
    result = await session.execute(paged_stmt)
    rows: list[tuple[Job, TailoringRecord]] = [
        (j, r) for j, r in result.all()
    ]

    count_stmt = (
        select(func.count())
        .select_from(latest_subq)
        .join(Job, Job.id == latest_subq.c.job_id)
        .where(Job.status.in_(statuses))
    )
    total = int((await session.execute(count_stmt)).scalar_one() or 0)
    return rows, total


# ---------------------------------------------------------------------------
# Drawer detail
# ---------------------------------------------------------------------------


async def get_drawer_data(session: AsyncSession, job_id: int) -> Optional[dict]:
    """Load the data the review drawer needs for one job.

    Returns ``None`` when the job (or its tailoring record) is missing.
    Drawer payload::

        {
          "job": Job,
          "record": TailoringRecord,
          "diff_html": str,
          "edit_sections": [{"heading": str, "content": [str, ...]}, ...],
          "cover_letter_text": str,   # may be ""
        }
    """
    # Latest record for this job.
    rec_stmt = (
        select(TailoringRecord)
        .where(TailoringRecord.job_id == job_id)
        .order_by(TailoringRecord.id.desc())
        .limit(1)
    )
    record = (await session.execute(rec_stmt)).scalar_one_or_none()
    if record is None:
        return None

    job = await session.get(Job, job_id)
    if job is None:
        return None

    diff_html = ""
    edit_sections: list[dict[str, Any]] = []
    if record.tailored_resume_path:
        try:
            from app.resume.service import extract_resume_text
            from app.tailoring.preview import format_diff_html, generate_section_diff

            tailored_path = Path(record.tailored_resume_path)
            base_path = Path(record.base_resume_path) if record.base_resume_path else None

            extracted = extract_sections_from_docx(tailored_path)
            edit_sections = list(extracted.get("sections", []))

            if base_path is not None and base_path.exists():
                base_data = extract_resume_text(base_path)
                base_sections = base_data["sections"]
                diffs = generate_section_diff(base_sections, extracted)
                diff_html = format_diff_html(diffs)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "review.drawer_diff_failed",
                job_id=job_id,
                error=str(exc),
            )

    cover_letter_text = ""
    if record.cover_letter_path:
        try:
            from app.submission.builder import extract_cover_letter_plaintext

            cover_letter_text = extract_cover_letter_plaintext(record.cover_letter_path)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning(
                "review.drawer_cover_letter_failed",
                job_id=job_id,
                error=str(exc),
            )

    return {
        "job": job,
        "record": record,
        "diff_html": diff_html,
        "edit_sections": edit_sections,
        "cover_letter_text": cover_letter_text,
    }


# ---------------------------------------------------------------------------
# Status writes (every one guarded by assert_valid_transition)
# ---------------------------------------------------------------------------


async def _set_status(
    session: AsyncSession, job: Job, target: str
) -> Job:
    assert_valid_transition(job.status, target)
    job.status = target
    session.add(job)
    return job


async def approve_one(session: AsyncSession, job_id: int) -> Job:
    """Flip a job to ``approved``. Raises ValueError on illegal transitions."""
    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    await _set_status(session, job, "approved")
    await session.commit()
    log.info("review.approved", job_id=job_id)
    return job


async def approve_batch(session: AsyncSession, job_ids: list[int]) -> int:
    """Approve many jobs in one transaction. All-or-nothing.

    Any illegal transition raises ValueError and rolls back every change
    in the batch — the caller surfaces a toast and leaves all jobs in
    their original state.
    """
    if not job_ids:
        return 0
    try:
        approved = 0
        for jid in job_ids:
            job = await session.get(Job, jid)
            if job is None:
                raise ValueError(f"job {jid} not found")
            await _set_status(session, job, "approved")
            approved += 1
        await session.commit()
        log.info("review.batch_approved", count=approved)
        return approved
    except Exception:
        await session.rollback()
        raise


async def reject_job(
    session: AsyncSession, job_id: int, *, mode: str
) -> Job:
    """Reject a job — ``mode='skip'`` or ``mode='retailor'``.

    ``skip``: terminal, job vanishes from the default queue filter.
    ``retailor``: flips to ``retailoring``; the next pipeline run picks
    it up via ``app.tailoring.service.get_queued_jobs`` (extended in
    Task 1 to include both ``matched`` and ``retailoring`` statuses).
    """
    if mode not in ("skip", "retailor"):
        raise ValueError(f"unknown reject mode: {mode!r}")
    job = await session.get(Job, job_id)
    if job is None:
        raise ValueError(f"job {job_id} not found")
    target = "skipped" if mode == "skip" else "retailoring"
    await _set_status(session, job, target)
    await session.commit()
    log.info("review.rejected", job_id=job_id, mode=mode, target=target)
    return job


async def retailor_job(session: AsyncSession, job_id: int) -> Job:
    """Convenience wrapper — equivalent to ``reject_job(... mode='retailor')``."""
    return await reject_job(session, job_id, mode="retailor")


# ---------------------------------------------------------------------------
# Inline edit -> new TailoringRecord
# ---------------------------------------------------------------------------


async def save_user_edits(
    session: AsyncSession,
    job_id: int,
    edited_sections: dict[str, Any],
) -> TailoringRecord:
    """Apply user edits as a new ``TailoringRecord`` with intensity ``manual_edit``.

    Pulls the latest record for this job to find the base resume path,
    bumps the version via ``app.tailoring.service.get_next_version``,
    writes a fresh DOCX via :func:`apply_user_edits`, and inserts a new
    ``TailoringRecord`` with zero token cost (no LLM call). Does NOT
    debit the BudgetGuard. Does NOT change ``Job.status`` — the user
    will approve afterwards.
    """
    from app.tailoring.service import get_next_version, resume_artifact_path

    # Latest record for the base path lookup.
    latest_stmt = (
        select(TailoringRecord)
        .where(TailoringRecord.job_id == job_id)
        .order_by(TailoringRecord.id.desc())
        .limit(1)
    )
    latest = (await session.execute(latest_stmt)).scalar_one_or_none()
    if latest is None:
        raise ValueError(f"no tailoring record for job {job_id}")

    if not latest.base_resume_path:
        raise ValueError(f"job {job_id} latest record has no base_resume_path")

    base_path = Path(latest.base_resume_path)
    version = await get_next_version(session, job_id)
    output_path = resume_artifact_path(job_id, version)

    apply_user_edits(
        base_resume_path=base_path,
        edited_sections=edited_sections,
        output_path=output_path,
    )

    new_record = TailoringRecord(
        job_id=job_id,
        version=version,
        intensity="manual_edit",
        status="completed",
        base_resume_path=str(base_path),
        tailored_resume_path=str(output_path),
        cover_letter_path=latest.cover_letter_path,  # unchanged on edits
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
        estimated_cost_dollars=0.0,
        validation_passed=None,
        validation_warnings="[]",
        retry_count=0,
        prompt_hash=None,
        error_message="user_edit",
        created_at=datetime.utcnow(),
    )
    session.add(new_record)
    await session.commit()
    await session.refresh(new_record)
    log.info(
        "review.user_edits_saved",
        job_id=job_id,
        version=version,
        path=str(output_path),
    )
    return new_record


__all__ = [
    "REVIEW_SORT_COLUMNS",
    "DEFAULT_REVIEW_STATUSES",
    "list_review_queue",
    "get_drawer_data",
    "approve_one",
    "approve_batch",
    "reject_job",
    "retailor_job",
    "save_user_edits",
]
