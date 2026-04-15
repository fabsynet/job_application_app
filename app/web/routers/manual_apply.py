"""Phase 5 manual-apply router — paste-a-link flow (MANL-01..06).

Four endpoints drive the three-step paste → preview → confirm UX:

  GET  /manual-apply          — the paste form (full page)
  POST /manual-apply/preview  — fetch + parse + render the preview card
                                OR the fallback form on ``FetchError``
  POST /manual-apply/confirm  — commit a parsed preview via
                                :func:`create_manual_job` (idempotent)
  POST /manual-apply/fallback — direct-entry path from the textarea
                                form when URL fetch fails

Both ``/confirm`` and ``/fallback`` route through
:func:`app.manual_apply.service.create_manual_job`, which hits the
canonical :func:`job_fingerprint` dedup guard. The success fragment
links directly to ``/jobs/{id}`` so the operator can watch the job
progress through the tailoring → approved → submitted pipeline —
:func:`review_confirm` itself does not embed a live-status widget.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.manual_apply.fetcher import FetchError, ParsedJob, fetch_and_parse
from app.manual_apply.service import check_duplicate, create_manual_job
from app.web.deps import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/manual-apply", tags=["manual_apply"])
templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _fallback_ctx(
    url: str,
    *,
    error: str,
    title: str = "",
    company: str = "",
    description: str = "",
    source: str = "manual",
) -> dict:
    return {
        "url": url,
        "error": error,
        "title": title,
        "company": company,
        "description": description,
        "source": source,
    }


# ---------------------------------------------------------------------------
# GET /manual-apply  (full page)
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def manual_apply_index(request: Request):
    return templates.TemplateResponse(
        request, "manual_apply/index.html.j2", {}
    )


# ---------------------------------------------------------------------------
# POST /manual-apply/preview  (fetch + parse + render preview card)
# ---------------------------------------------------------------------------


@router.post("/preview", response_class=HTMLResponse)
async def manual_apply_preview(
    request: Request,
    url: str = Form(""),
):
    """Fetch the pasted URL and render the preview card.

    On :class:`FetchError`, renders the fallback form with the error
    reason so the user can paste the job description manually.
    """
    url = (url or "").strip()
    if not url:
        return templates.TemplateResponse(
            request,
            "manual_apply/_fallback.html.j2",
            _fallback_ctx("", error="empty_url"),
        )

    try:
        parsed = await fetch_and_parse(url)
    except FetchError as exc:
        log.info(
            "manual_apply.preview_fetch_error",
            url=url,
            reason=exc.reason,
            status=exc.status,
        )
        return templates.TemplateResponse(
            request,
            "manual_apply/_fallback.html.j2",
            _fallback_ctx(url, error=exc.reason),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("manual_apply.preview_unexpected", url=url, error=str(exc))
        return templates.TemplateResponse(
            request,
            "manual_apply/_fallback.html.j2",
            _fallback_ctx(url, error="unexpected_error"),
        )

    excerpt = (parsed.description or "")[:300]
    ctx = {
        "parsed": parsed,
        "excerpt": excerpt,
    }
    return templates.TemplateResponse(
        request, "manual_apply/_preview.html.j2", ctx
    )


# ---------------------------------------------------------------------------
# POST /manual-apply/confirm  (create Job from preview card)
# ---------------------------------------------------------------------------


async def _create_or_duplicate_response(
    request: Request,
    session: AsyncSession,
    parsed: ParsedJob,
) -> HTMLResponse:
    """Shared body for /confirm and /fallback.

    Looks up the dedup fingerprint first; if the job already exists,
    returns a fragment linking to the existing ``/jobs/{id}`` detail
    view. Otherwise creates a new manual job and returns the success
    fragment.
    """
    existing = await check_duplicate(session, parsed)
    if existing is not None:
        log.info(
            "manual_apply.duplicate",
            job_id=existing.id,
            fingerprint=existing.fingerprint,
        )
        ctx = {
            "existing": True,
            "job": existing,
        }
        return templates.TemplateResponse(
            request, "manual_apply/_result.html.j2", ctx
        )

    job = await create_manual_job(session, parsed)
    log.info(
        "manual_apply.created",
        job_id=job.id,
        source=job.source,
        title=job.title,
        company=job.company,
    )
    ctx = {"existing": False, "job": job}
    return templates.TemplateResponse(
        request, "manual_apply/_result.html.j2", ctx
    )


@router.post("/confirm", response_class=HTMLResponse)
async def manual_apply_confirm(
    request: Request,
    title: str = Form(...),
    company: str = Form(...),
    description: str = Form(""),
    source: str = Form("manual"),
    url: str = Form(...),
    description_html: Optional[str] = Form(None),
    external_id: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    parsed = ParsedJob(
        title=(title or "").strip() or "Unknown Role",
        company=(company or "").strip() or "Unknown",
        description=description or "",
        description_html=description_html or description or "",
        url=(url or "").strip(),
        source=(source or "manual").strip() or "manual",
        external_id=(external_id or url or "").strip(),
    )
    return await _create_or_duplicate_response(request, session, parsed)


# ---------------------------------------------------------------------------
# POST /manual-apply/fallback  (textarea-form direct-entry path)
# ---------------------------------------------------------------------------


@router.post("/fallback", response_class=HTMLResponse)
async def manual_apply_fallback(
    request: Request,
    title: str = Form(...),
    company: str = Form(...),
    description: str = Form(""),
    source: str = Form("manual"),
    url: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    title = (title or "").strip()
    company = (company or "").strip()
    if not title or not company:
        ctx = _fallback_ctx(
            url,
            error="title_and_company_required",
            title=title,
            company=company,
            description=description,
            source=source,
        )
        return templates.TemplateResponse(
            request, "manual_apply/_fallback.html.j2", ctx
        )

    # Best-effort URL so dedup keys differ across pastes. Use a stable
    # synthetic URL when the user had no URL to paste at all.
    effective_url = url.strip() or f"manual://{company.lower()}/{title.lower()}".replace(" ", "-")
    parsed = ParsedJob(
        title=title,
        company=company,
        description=description or "",
        description_html=description or "",
        url=effective_url,
        source=(source or "manual").strip() or "manual",
        external_id=effective_url,
    )
    return await _create_or_duplicate_response(request, session, parsed)


__all__ = ["router"]
