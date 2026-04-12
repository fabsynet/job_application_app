"""Jobs router: sortable table, inline detail expansion, manual queue.

Displays all discovered jobs in a sortable table with color-coded score
badges.  Clicking a row expands inline to show the full description with
keyword highlighting.  Below-threshold jobs can be manually queued for
application via a button in the expanded view.

HTMX-powered: sort clicks swap the table body, row clicks toggle an
inline detail partial, queue button replaces the detail partial.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.service import get_job_detail, list_jobs, update_job_status
from app.settings.service import get_settings_row
from app.web.deps import get_session

router = APIRouter(prefix="/jobs", tags=["jobs"])

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


def _parse_keywords(keywords_csv: str) -> list[str]:
    """Split pipe-delimited keywords string into a cleaned list."""
    if not keywords_csv or not keywords_csv.strip():
        return []
    return [k.strip() for k in keywords_csv.split("|") if k.strip()]


@router.get("", response_class=HTMLResponse)
async def jobs_page(
    request: Request,
    sort: str = "score",
    dir: str = "desc",
    session: AsyncSession = Depends(get_session),
):
    """Full jobs page or HTMX table body partial (on sort click)."""
    settings = await get_settings_row(session)
    threshold = settings.match_threshold
    all_keywords = _parse_keywords(settings.keywords_csv)

    jobs = await list_jobs(session, sort_by=sort, sort_dir=dir, limit=500)

    ctx = {
        "jobs": jobs,
        "threshold": threshold,
        "all_keywords": all_keywords,
        "current_sort": sort,
        "current_dir": dir,
    }

    # HTMX partial swap for sorting
    is_htmx = request.headers.get("HX-Request") == "true"
    if is_htmx:
        return templates.TemplateResponse(
            request, "partials/jobs_table.html.j2", ctx
        )
    return templates.TemplateResponse(request, "jobs.html.j2", ctx)


@router.get("/{job_id}/detail", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Inline expansion partial with full description and keyword breakdown."""
    job = await get_job_detail(session, job_id)
    if job is None:
        return HTMLResponse("<tr><td colspan='6'>Job not found</td></tr>", status_code=404)

    settings = await get_settings_row(session)
    all_keywords = _parse_keywords(settings.keywords_csv)
    matched = _parse_keywords(job.matched_keywords) if job.matched_keywords else []
    matched_lower = {k.lower() for k in matched}
    unmatched = [k for k in all_keywords if k.lower() not in matched_lower]

    ctx = {
        "job": job,
        "matched_keywords": matched,
        "unmatched_keywords": unmatched,
        "threshold": settings.match_threshold,
    }
    return templates.TemplateResponse(
        request, "partials/job_detail_inline.html.j2", ctx
    )


@router.post("/{job_id}/queue", response_class=HTMLResponse)
async def queue_job(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Manually queue a below-threshold job for application."""
    job = await update_job_status(session, job_id, "queued")
    if job is None:
        return HTMLResponse("<tr><td colspan='6'>Job not found</td></tr>", status_code=404)

    settings = await get_settings_row(session)
    all_keywords = _parse_keywords(settings.keywords_csv)
    matched = _parse_keywords(job.matched_keywords) if job.matched_keywords else []
    matched_lower = {k.lower() for k in matched}
    unmatched = [k for k in all_keywords if k.lower() not in matched_lower]

    ctx = {
        "job": job,
        "matched_keywords": matched,
        "unmatched_keywords": unmatched,
        "threshold": settings.match_threshold,
    }
    return templates.TemplateResponse(
        request, "partials/job_detail_inline.html.j2", ctx
    )


__all__ = ["router"]
