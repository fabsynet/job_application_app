"""Phase 6 needs-info queue router.

Provides the /needs-info endpoints where users review halted applications
with unknown form fields, provide answers, and trigger immediate Playwright
retry.  Mirrors the per-router Jinja2Templates pattern from review.py.
"""
from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.learning.needs_info import get_needs_info_detail, get_needs_info_jobs
from app.learning.service import resolve_all_for_job
from app.submission.service import flip_job_status
from app.web.deps import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/needs-info", tags=["needs-info"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


# ---------------------------------------------------------------------------
# GET /needs-info — Queue listing
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def needs_info_index(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """List all jobs with status needs_info and their unknown field counts."""
    jobs = await get_needs_info_jobs(session)
    return templates.TemplateResponse(
        request,
        "needs_info/index.html.j2",
        {"jobs": jobs},
    )


# ---------------------------------------------------------------------------
# GET /needs-info/{job_id} — Job detail with unknown fields
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_class=HTMLResponse)
async def needs_info_detail(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Show job context and all unknown fields for resolution."""
    detail = await get_needs_info_detail(session, job_id)
    if detail is None or detail["status"] != "needs_info":
        raise HTTPException(status_code=404, detail="Job not found or not in needs_info status")

    # Separate unresolved fields for the answer form
    unresolved_fields = [f for f in detail["fields"] if not f["resolved"]]
    ctx = {**detail, "unresolved_fields": unresolved_fields}
    return templates.TemplateResponse(
        request,
        "needs_info/detail.html.j2",
        ctx,
    )


# ---------------------------------------------------------------------------
# POST /needs-info/{job_id}/answer — Submit answers for all unknown fields
# ---------------------------------------------------------------------------


@router.post("/{job_id}/answer", response_class=HTMLResponse)
async def needs_info_answer(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Parse form answers, resolve unknown fields, flip job to approved."""
    detail = await get_needs_info_detail(session, job_id)
    if detail is None or detail["status"] != "needs_info":
        raise HTTPException(status_code=404, detail="Job not found or not in needs_info status")

    form = await request.form()

    # Build answers dict: field_id -> answer_text
    answers: dict[int, str] = {}
    for key, value in form.items():
        if key.startswith("field_") and value:
            try:
                field_id = int(key.split("_", 1)[1])
                answers[field_id] = str(value)
            except (ValueError, IndexError):
                continue

    if answers:
        await resolve_all_for_job(session, job_id, answers)
        await session.commit()

    # Flip status: needs_info -> approved
    await flip_job_status(
        session, job_id, "approved", reason="user_answered_unknowns"
    )

    log.info(
        "needs_info.answered",
        job_id=job_id,
        fields_answered=len(answers),
    )
    return RedirectResponse(f"/needs-info", status_code=303)


# ---------------------------------------------------------------------------
# POST /needs-info/{job_id}/retry — Immediate Playwright retry
# ---------------------------------------------------------------------------


@router.post("/{job_id}/retry", response_class=HTMLResponse)
async def needs_info_retry(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Trigger an immediate Playwright retry for a resolved needs_info job.

    This is a placeholder implementation that flips the job to approved
    so the regular submission pipeline picks it up on its next run.
    Full inline Playwright submission requires a running browser context
    which is managed by the scheduler pipeline, not the web layer.
    """
    detail = await get_needs_info_detail(session, job_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # If still needs_info, flip to approved for pipeline pickup
    if detail["status"] == "needs_info":
        await flip_job_status(
            session, job_id, "approved", reason="retry_requested"
        )

    log.info("needs_info.retry_requested", job_id=job_id)
    return RedirectResponse("/needs-info", status_code=303)


__all__ = ["router"]
