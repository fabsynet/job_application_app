"""Phase 5 review queue router.

Renders ``/review`` (sortable / filterable table), the row drawer with
inline edit form and base-vs-tailored diff, single + batch approval, and
the skip / re-tailor reject path. Mirrors the per-router
``Jinja2Templates(directory=...)`` shape established by
``app.web.routers.jobs``.

Every status-writing endpoint catches ``ValueError`` from
``assert_valid_transition`` and returns a 422 toast fragment — never a
500 — so the UI surfaces a friendly message when an illegal transition
slips through (e.g. user double-clicks Approve on a row that was just
submitted by another tab).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.discovery.models import Job
from app.review.service import (
    DEFAULT_REVIEW_STATUSES,
    approve_batch,
    approve_one,
    get_drawer_data,
    list_review_queue,
    reject_job,
    save_user_edits,
)
from app.web.deps import get_session

log = structlog.get_logger(__name__)


router = APIRouter(prefix="/review", tags=["review"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


async def _render_table(request: Request, session: AsyncSession) -> HTMLResponse:
    """Render the review-table partial fragment with default sort/filter.

    Used as the HTMX swap target after any mutation endpoint succeeds —
    callers do NOT pass through ``review_index`` because that handler's
    parameters carry FastAPI ``Query`` defaults that are not iterable
    when called as a plain Python function.
    """
    rows, total = await list_review_queue(session)
    ctx = {
        "rows": rows,
        "total": total,
        "current_sort": "tailored_at",
        "current_dir": "desc",
        "current_status": list(DEFAULT_REVIEW_STATUSES),
        "default_statuses": DEFAULT_REVIEW_STATUSES,
    }
    return templates.TemplateResponse(request, "review/_table.html.j2", ctx)


def _toast(request: Request, message: str, status_code: int = 422) -> HTMLResponse:
    """Return a small HTML toast fragment with an error class."""
    body = (
        f'<div class="toast toast-error" role="alert" '
        f'data-status="{status_code}">{message}</div>'
    )
    return HTMLResponse(body, status_code=status_code)


# ---------------------------------------------------------------------------
# GET /review
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def review_index(
    request: Request,
    sort_by: str = "tailored_at",
    sort_dir: str = "desc",
    status: list[str] = Query(default_factory=list),
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """Full review queue page or HTMX table-only swap."""
    rows, total = await list_review_queue(
        session,
        sort_by=sort_by,
        sort_dir=sort_dir,
        status_filter=status or None,
        limit=limit,
        offset=offset,
    )
    ctx = {
        "rows": rows,
        "total": total,
        "current_sort": sort_by,
        "current_dir": sort_dir,
        "current_status": status or list(DEFAULT_REVIEW_STATUSES),
        "default_statuses": DEFAULT_REVIEW_STATUSES,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(request, "review/_table.html.j2", ctx)
    return templates.TemplateResponse(request, "review/index.html.j2", ctx)


# ---------------------------------------------------------------------------
# GET /review/confirm-approve  (HTMX modal fragment)
# ---------------------------------------------------------------------------


@router.get("/confirm-approve", response_class=HTMLResponse)
async def review_confirm_batch(
    request: Request,
    job_ids: list[int] = Query(default_factory=list),
    session: AsyncSession = Depends(get_session),
):
    """Render the batch-approve confirmation modal fragment."""
    if not job_ids:
        return HTMLResponse(
            '<div class="toast toast-error">No jobs selected.</div>',
            status_code=400,
        )
    rows = (
        await session.execute(select(Job).where(Job.id.in_(job_ids)))
    ).scalars().all()
    ctx = {"jobs": list(rows), "job_ids": [j.id for j in rows]}
    return templates.TemplateResponse(
        request, "review/_confirm_batch.html.j2", ctx
    )


# ---------------------------------------------------------------------------
# POST /review/approve-batch
# ---------------------------------------------------------------------------


@router.post("/approve-batch", response_class=HTMLResponse)
async def review_approve_batch(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    raw_ids = form.getlist("job_ids")
    try:
        job_ids = [int(x) for x in raw_ids]
    except ValueError:
        return _toast(request, "Invalid job ids.", status_code=400)
    try:
        approved = await approve_batch(session, job_ids)
    except ValueError as exc:
        return _toast(request, f"Cannot approve batch: {exc}")
    log.info("review.batch_approve_endpoint", count=approved)
    if _is_htmx(request):
        return await _render_table(request, session)
    return RedirectResponse("/review", status_code=303)


# ---------------------------------------------------------------------------
# GET /review/{job_id}  (drawer)
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_class=HTMLResponse)
async def review_drawer(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    data = await get_drawer_data(session, job_id)
    if data is None:
        return _toast(request, f"Job {job_id} not found.", status_code=404)
    if _is_htmx(request):
        return templates.TemplateResponse(
            request, "review/drawer.html.j2", data
        )
    # Full page: render the index with the drawer pre-populated below.
    rows, total = await list_review_queue(session)
    ctx = {
        "rows": rows,
        "total": total,
        "current_sort": "tailored_at",
        "current_dir": "desc",
        "current_status": list(DEFAULT_REVIEW_STATUSES),
        "default_statuses": DEFAULT_REVIEW_STATUSES,
        "drawer": data,
    }
    return templates.TemplateResponse(request, "review/index.html.j2", ctx)


# ---------------------------------------------------------------------------
# POST /review/{job_id}/save-edits
# ---------------------------------------------------------------------------


def _reconstruct_edited_sections(form_items: list[tuple[str, str]]) -> dict:
    """Rebuild ``{sections: [{heading, content}, ...]}`` from form data.

    Form field naming convention from ``_edit_form.html.j2``:

    - ``heading_<index>`` — the section heading hidden input
    - ``section_<index>`` — the textarea body (one bullet per line)
    """
    headings: dict[int, str] = {}
    bodies: dict[int, str] = {}
    for k, v in form_items:
        if k.startswith("heading_"):
            try:
                idx = int(k.split("_", 1)[1])
            except ValueError:
                continue
            headings[idx] = v
        elif k.startswith("section_"):
            try:
                idx = int(k.split("_", 1)[1])
            except ValueError:
                continue
            bodies[idx] = v

    sections: list[dict] = []
    for idx in sorted(set(headings) | set(bodies)):
        body = bodies.get(idx, "") or ""
        content = [line.rstrip() for line in body.splitlines() if line.strip()]
        sections.append(
            {"heading": headings.get(idx, ""), "content": content}
        )
    return {"sections": sections}


@router.post("/{job_id}/save-edits", response_class=HTMLResponse)
async def review_save_edits(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    form = await request.form()
    form_items = [(k, str(v)) for k, v in form.multi_items()]
    edited = _reconstruct_edited_sections(form_items)
    try:
        new_record = await save_user_edits(session, job_id, edited)
    except ValueError as exc:
        return _toast(request, f"Save failed: {exc}", status_code=400)
    log.info(
        "review.save_edits_endpoint",
        job_id=job_id,
        record_id=new_record.id,
        version=new_record.version,
    )
    if _is_htmx(request):
        # Re-render the edit form with fresh sections + a saved toast.
        data = await get_drawer_data(session, job_id)
        ctx = dict(data or {})
        ctx["saved_toast"] = "Saved"
        return templates.TemplateResponse(
            request, "review/_edit_form.html.j2", ctx
        )
    return RedirectResponse(f"/review/{job_id}", status_code=303)


# ---------------------------------------------------------------------------
# POST /review/{job_id}/approve
# ---------------------------------------------------------------------------


@router.post("/{job_id}/approve", response_class=HTMLResponse)
async def review_approve_one(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        await approve_one(session, job_id)
    except ValueError as exc:
        return _toast(request, f"Cannot approve: {exc}")
    if _is_htmx(request):
        return await _render_table(request, session)
    return RedirectResponse("/review", status_code=303)


# ---------------------------------------------------------------------------
# POST /review/{job_id}/reject  (form field: mode=skip|retailor)
# ---------------------------------------------------------------------------


@router.post("/{job_id}/reject", response_class=HTMLResponse)
async def review_reject(
    request: Request,
    job_id: int,
    mode: str = Form("skip"),
    session: AsyncSession = Depends(get_session),
):
    try:
        await reject_job(session, job_id, mode=mode)
    except ValueError as exc:
        return _toast(request, f"Cannot reject: {exc}")
    if _is_htmx(request):
        return await _render_table(request, session)
    return RedirectResponse("/review", status_code=303)


# ---------------------------------------------------------------------------
# POST /review/{job_id}/retailor  (thin wrapper)
# ---------------------------------------------------------------------------


@router.post("/{job_id}/retailor", response_class=HTMLResponse)
async def review_retailor(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        await reject_job(session, job_id, mode="retailor")
    except ValueError as exc:
        return _toast(request, f"Cannot re-tailor: {exc}")
    if _is_htmx(request):
        return await _render_table(request, session)
    return RedirectResponse("/review", status_code=303)


__all__ = ["router"]
