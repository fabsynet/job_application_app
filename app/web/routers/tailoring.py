"""Tailoring review UI: detail view, HTML preview, diff, and DOCX download.

The review queue lets the user inspect a job's tailored resume before
(or instead of) auto-submission.  Every route renders or serves data
for a single ``job_id``; version numbers map to the
``v{N}.docx`` / ``cover_letter_v{N}.docx`` artifacts written by the
Phase 4 pipeline (see ``app.tailoring.service.resume_artifact_path``).

Routes:

* ``GET /tailoring/{job_id}``                     — full detail page
* ``GET /tailoring/{job_id}/preview/{version}``   — HTMX preview partial
* ``GET /tailoring/{job_id}/download/{version}``  — DOCX download
* ``GET /tailoring/{job_id}/cover-letter/{version}`` — cover-letter download

The detail page shows a side-by-side diff of the base and tailored
resumes (``generate_section_diff`` + ``format_diff_html``), the
validator findings carried on ``TailoringRecord.validation_warnings``,
the ATS-friendly audit (``check_ats_friendly`` + keyword-coverage
percentage), and a per-call cost breakdown that surfaces
``cache_read_tokens`` and the estimated savings from prompt caching —
the UI proof of SC-5 (prompt caching visibly reduces cost).

All handlers follow the Jinja2 ``templates.TemplateResponse(request,
name, ctx)`` positional form used by the rest of ``app/web/routers``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TailoringRecord
from app.discovery.service import get_job_detail
from app.resume.service import extract_resume_text, get_resume_path
from app.tailoring.docx_writer import check_ats_friendly, compute_keyword_coverage
from app.tailoring.preview import (
    docx_to_html,
    format_diff_html,
    generate_section_diff,
)
from app.tailoring.service import (
    cover_letter_artifact_path,
    get_latest_tailoring,
    get_tailoring_records_for_job,
    resume_artifact_path,
)
from app.web.deps import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/tailoring", tags=["tailoring"])

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


# Claude Sonnet 4.5 pricing (per million tokens) — must stay in sync with
# ``app.tailoring.budget.BudgetGuard.PRICING``. Duplicated here only for
# the "estimated cache savings" display math.
_INPUT_PRICE_PER_MTOK = 3.00
_CACHE_READ_PRICE_PER_MTOK = 0.30


def _docx_sections_as_tailored_json(docx_path: Path) -> dict:
    """Shim the tailored DOCX back into the dict shape the diff expects.

    ``generate_section_diff`` is designed to consume the structured JSON
    the engine produced (``{"sections": [{"heading", "content"}, ...]}``)
    but tailoring records only persist the DOCX artifact — not the raw
    JSON — so for the detail view we re-extract the text and re-shape
    it.  Each section becomes ``{"heading": ..., "content": text}`` and
    ``_tailored_section_text`` flattens it back for the diff line-level
    markup.
    """
    data = extract_resume_text(docx_path)
    shaped: list[dict] = []
    for sec in data.get("sections") or []:
        heading = sec.get("heading") or ""
        text = sec.get("text") or ""
        shaped.append({"heading": heading, "content": text})
    return {"sections": shaped}


def _estimate_cache_savings(cache_read_tokens: int) -> float:
    """Dollar amount saved by prompt caching on one record.

    Savings = cache_read_tokens * (input_price - cache_read_price),
    priced against Claude Sonnet 4.5.  Returned in dollars rounded to
    six decimals so the template can format with ``'%.4f'``.
    """
    if not cache_read_tokens:
        return 0.0
    saved_per_mtok = _INPUT_PRICE_PER_MTOK - _CACHE_READ_PRICE_PER_MTOK
    return round(cache_read_tokens / 1_000_000 * saved_per_mtok, 6)


def _parse_validation_warnings(raw: Optional[str]) -> list:
    """Decode the JSON blob stored on ``TailoringRecord.validation_warnings``.

    Returns an empty list on missing / malformed data so the template
    can always iterate safely.
    """
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _find_record(records: list[TailoringRecord], version: int) -> Optional[TailoringRecord]:
    for rec in records:
        if rec.version == version:
            return rec
    return None


# ---------------------------------------------------------------------------
# Detail view
# ---------------------------------------------------------------------------


@router.get("/{job_id}", response_class=HTMLResponse)
async def tailoring_detail(
    request: Request,
    job_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Render the full tailoring detail page for ``job_id``.

    Loads the job, every tailoring attempt in version order, and the
    latest completed record.  If a completed record exists and its
    tailored DOCX is on disk, the page ships with the HTML preview,
    side-by-side diff, validator warnings, ATS audit, and the per-call
    cost breakdown that highlights cache savings.
    """
    job = await get_job_detail(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    records = await get_tailoring_records_for_job(session, job_id)
    latest = await get_latest_tailoring(session, job_id)

    preview_html: Optional[str] = None
    diff_html: Optional[str] = None
    validation_warnings: list = []
    ats_checks: Optional[dict] = None
    keyword_coverage: Optional[float] = None
    cover_letter_preview: Optional[str] = None
    cache_savings_dollars: float = 0.0

    if latest is not None:
        validation_warnings = _parse_validation_warnings(latest.validation_warnings)
        cache_savings_dollars = _estimate_cache_savings(latest.cache_read_tokens or 0)

        tailored_path_str = latest.tailored_resume_path
        tailored_path = Path(tailored_path_str) if tailored_path_str else None
        if tailored_path and tailored_path.exists():
            try:
                preview_html = docx_to_html(tailored_path)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "tailoring_preview_failed",
                    job_id=job_id,
                    path=str(tailored_path),
                    error=str(exc),
                )

            # Build diff against the current base resume if available.
            base_path = get_resume_path()
            if base_path is not None:
                try:
                    base_data = extract_resume_text(base_path)
                    tailored_shape = _docx_sections_as_tailored_json(tailored_path)
                    diffs = generate_section_diff(
                        base_data["sections"], tailored_shape
                    )
                    diff_html = format_diff_html(diffs)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "tailoring_diff_failed",
                        job_id=job_id,
                        error=str(exc),
                    )

            try:
                ats_checks = check_ats_friendly(tailored_path)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "tailoring_ats_check_failed",
                    job_id=job_id,
                    error=str(exc),
                )

            # Keyword coverage from tailored DOCX text vs job description.
            # The record itself does not persist this value so we recompute
            # on demand — cheap enough for a single view render.
            try:
                tailored_data = extract_resume_text(tailored_path)
                tailored_text = tailored_data.get("full_text", "")
                if job.description and tailored_text:
                    keyword_coverage = compute_keyword_coverage(
                        tailored_text, job.description
                    )
                    if ats_checks is not None:
                        ats_checks["keyword_coverage"] = keyword_coverage
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "tailoring_keyword_coverage_failed",
                    job_id=job_id,
                    error=str(exc),
                )

        cover_letter_path_str = latest.cover_letter_path
        if cover_letter_path_str:
            cl_path = Path(cover_letter_path_str)
            if cl_path.exists():
                try:
                    cover_letter_preview = docx_to_html(cl_path)
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "cover_letter_preview_failed",
                        job_id=job_id,
                        path=str(cl_path),
                        error=str(exc),
                    )

    ctx = {
        "job": job,
        "records": records,
        "latest_record": latest,
        "preview_html": preview_html,
        "diff_html": diff_html,
        "validation_warnings": validation_warnings,
        "ats_checks": ats_checks,
        "keyword_coverage": keyword_coverage,
        "cover_letter_preview": cover_letter_preview,
        "cache_savings_dollars": cache_savings_dollars,
    }
    return templates.TemplateResponse(
        request, "partials/tailoring_detail.html.j2", ctx
    )


# ---------------------------------------------------------------------------
# Version preview (HTMX)
# ---------------------------------------------------------------------------


@router.get("/{job_id}/preview/{version}", response_class=HTMLResponse)
async def tailoring_preview(
    request: Request,
    job_id: int,
    version: int,
    session: AsyncSession = Depends(get_session),
):
    """Return the HTML preview partial for a single version.

    Used by HTMX when the user swaps between versions in the detail
    view; it avoids re-rendering the full page while still benefiting
    from the same mammoth conversion used server-side.
    """
    records = await get_tailoring_records_for_job(session, job_id)
    record = _find_record(records, version)
    if record is None or not record.tailored_resume_path:
        raise HTTPException(status_code=404, detail="Tailored resume not found")

    path = Path(record.tailored_resume_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Tailored resume file missing")

    try:
        html_out = docx_to_html(path)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "tailoring_preview_version_failed",
            job_id=job_id,
            version=version,
            error=str(exc),
        )
        raise HTTPException(status_code=500, detail="Preview render failed") from exc

    ctx = {"preview_html": html_out, "title": f"Version v{version}"}
    return templates.TemplateResponse(
        request, "partials/resume_preview.html.j2", ctx
    )


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------


_DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@router.get("/{job_id}/download/{version}")
async def download_tailored_resume(job_id: int, version: int):
    """Stream the versioned tailored DOCX as an attachment."""
    path = resume_artifact_path(job_id, version)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Tailored resume not found")
    return FileResponse(
        path=str(path),
        media_type=_DOCX_MEDIA_TYPE,
        filename=f"tailored_resume_v{version}.docx",
    )


@router.get("/{job_id}/cover-letter/{version}")
async def download_cover_letter(job_id: int, version: int):
    """Stream the versioned cover-letter DOCX as an attachment."""
    path = cover_letter_artifact_path(job_id, version)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Cover letter not found")
    return FileResponse(
        path=str(path),
        media_type=_DOCX_MEDIA_TYPE,
        filename=f"cover_letter_v{version}.docx",
    )


__all__ = ["router"]
