"""Phase 5 plan 05-08 applied-jobs dashboard router.

Mounts ``/applied`` — the "what did we send?" dashboard with counts,
filterable / sortable table, detail view, artifact downloads (including
the SC-5 manual-completion path for ``approved``-but-unsent jobs), the
daily-cap raise-cap banner, and the notification-email banner refresh
fragment.

Follows the per-router ``Jinja2Templates(directory=...)`` convention
used by ``app.web.routers.jobs``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models import Run
from app.review.applied_service import (
    DEFAULT_APPLIED_STATUSES,
    applied_artifact_paths,
    get_applied_detail,
    list_applied_jobs,
    state_counts_for_window,
)
from app.settings.service import get_settings_row, set_setting
from app.tailoring.models import TailoringRecord
from app.web.deps import get_session

log = structlog.get_logger(__name__)


router = APIRouter(prefix="/applied", tags=["applied"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)

_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


async def _latest_tailoring_for(
    session: AsyncSession, job_id: int
) -> Optional[TailoringRecord]:
    stmt = (
        select(TailoringRecord)
        .where(TailoringRecord.job_id == job_id)
        .order_by(TailoringRecord.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def _build_banner_context(session: AsyncSession) -> dict:
    """Return ``{'rate_limited': bool, 'waiting': int, 'alerted': int}``.

    Reads the most-recent ``Run.counts`` JSON blob to detect a prior
    daily-cap halt. ``waiting`` is the number of jobs still sitting in
    ``approved`` right now (a live query, not the stale run snapshot).
    """
    latest_run_stmt = select(Run).order_by(Run.id.desc()).limit(1)
    latest = (await session.execute(latest_run_stmt)).scalar_one_or_none()
    rate_limited = False
    if latest is not None:
        counts = latest.counts or {}
        rate_limited = bool(counts.get("rate_limited"))

    # How many jobs are currently waiting for tomorrow's run? Live count
    # (not the stale run blob) — matches the SC-2 manual-completion
    # commitment.
    from app.discovery.models import Job
    from sqlalchemy import func as _func

    waiting_stmt = select(_func.count(Job.id)).where(Job.status == "approved")
    waiting = int((await session.execute(waiting_stmt)).scalar_one() or 0)

    return {
        "rate_limited": rate_limited,
        "waiting": waiting,
    }


async def _local_midnight(session: AsyncSession) -> datetime:
    """Return a naive UTC datetime corresponding to today's local midnight.

    Settings.timezone is user-configurable; we resolve it via ZoneInfo
    and convert back to a naive UTC datetime so the SQLite comparison
    (``Job.first_seen_at >= since``) stays aligned with the stored
    UTC-naive timestamps.
    """
    row = await get_settings_row(session)
    try:
        tz = ZoneInfo(row.timezone or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    now_local = datetime.now(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    # Convert to naive UTC
    return midnight_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# GET /applied  (full page + HTMX table swap)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def applied_index(
    request: Request,
    sort_by: str = "submitted_at",
    sort_dir: str = "desc",
    status: list[str] = Query(default_factory=list),
    source: list[str] = Query(default_factory=list),
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    rows, total = await list_applied_jobs(
        session,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_filter=status or None,
        source_filter=source or None,
        limit=limit,
        offset=offset,
    )

    today_midnight = await _local_midnight(session)
    week_ago = datetime.utcnow() - timedelta(days=7)
    counts_today = await state_counts_for_window(session, since=today_midnight)
    counts_week = await state_counts_for_window(session, since=week_ago)

    banner = await _build_banner_context(session)
    settings_row = await get_settings_row(session)

    ctx = {
        "rows": rows,
        "total": total,
        "counts_today": counts_today,
        "counts_week": counts_week,
        "banner": banner,
        "settings": settings_row,
        "current_sort": sort_by,
        "current_dir": sort_dir,
        "current_status": status or list(DEFAULT_APPLIED_STATUSES),
        "current_source": source,
        "default_statuses": DEFAULT_APPLIED_STATUSES,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "applied/_table.html.j2", ctx)
    return templates.TemplateResponse(request, "applied/index.html.j2", ctx)


# ---------------------------------------------------------------------------
# POST /applied/raise-cap
# ---------------------------------------------------------------------------


@router.post("/raise-cap", response_class=HTMLResponse)
async def applied_raise_cap(
    request: Request,
    raise_by: int = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    if raise_by <= 0 or raise_by > 1000:
        raise HTTPException(
            status_code=400, detail="raise_by must be 1..1000"
        )
    row = await get_settings_row(session)
    new_cap = (row.daily_cap or 0) + raise_by
    await set_setting(session, "daily_cap", new_cap)

    # Live update the in-memory RateLimiter so the bump takes effect on
    # the next pipeline tick without restarting the process — same
    # pattern as ``/settings/limits``.
    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        rate_limiter.daily_cap = new_cap

    log.info("applied.raise_cap", raise_by=raise_by, new_cap=new_cap)

    banner = await _build_banner_context(session)
    ctx = {"banner": banner, "settings": await get_settings_row(session)}
    return templates.TemplateResponse(request, "applied/_banner.html.j2", ctx)


# ---------------------------------------------------------------------------
# GET /applied/{job_id}  (detail view)
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_class=HTMLResponse)
async def applied_detail(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    data = await get_applied_detail(session, job_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return templates.TemplateResponse(request, "applied/detail.html.j2", data)


# ---------------------------------------------------------------------------
# GET /applied/{job_id}/download  (tailored resume — SC-5)
# ---------------------------------------------------------------------------


@router.get("/{job_id}/download")
async def applied_download_resume(
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Stream the latest tailored DOCX for this job.

    Works for ``approved``-but-unsent jobs (SC-5 manual-completion
    path) — does NOT require the job to be in ``submitted`` state.
    """
    record = await _latest_tailoring_for(session, job_id)
    paths = applied_artifact_paths(record)
    resume_path = paths["resume"]
    if resume_path is None or not resume_path.exists():
        raise HTTPException(status_code=404, detail="Tailored resume not found")
    # Friendly filename — use the record's company if we can grab it.
    from app.discovery.models import Job

    job = await session.get(Job, job_id)
    company = (job.company if job else "Resume").replace(" ", "_")
    return FileResponse(
        path=str(resume_path),
        media_type=_DOCX_MEDIA_TYPE,
        filename=f"{company}_tailored_resume.docx",
    )


# ---------------------------------------------------------------------------
# GET /applied/{job_id}/cover-letter
# ---------------------------------------------------------------------------


@router.get("/{job_id}/cover-letter")
async def applied_download_cover_letter(
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    record = await _latest_tailoring_for(session, job_id)
    paths = applied_artifact_paths(record)
    cl_path = paths["cover_letter"]
    if cl_path is None or not cl_path.exists():
        raise HTTPException(status_code=404, detail="Cover letter not found")
    from app.discovery.models import Job

    job = await session.get(Job, job_id)
    company = (job.company if job else "Cover").replace(" ", "_")
    return FileResponse(
        path=str(cl_path),
        media_type=_DOCX_MEDIA_TYPE,
        filename=f"{company}_cover_letter.docx",
    )


__all__ = ["router"]
