"""Sources settings section: add, validate, toggle, and remove ATS sources.

Users add company sources by pasting a URL or slug (e.g. "stripe" or
"https://boards.greenhouse.io/stripe"). The router validates immediately
against the real ATS API and only persists valid entries. Each source
has an enable/disable toggle and can be removed.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.discovery.fetchers import detect_source, validate_source
from app.discovery.models import Source
from app.discovery.service import (
    create_source,
    delete_source,
    get_all_sources,
    toggle_source,
)
from app.web.deps import get_session

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/settings/sources")

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


async def _render_sources(
    request: Request,
    session,
    error: str | None = None,
    flash: tuple[str, str] | None = None,
) -> HTMLResponse:
    """Load all sources and render the sources section partial."""
    sources = await get_all_sources(session)
    ctx: dict = {
        "sources": sources,
        "active_section": "sources",
    }
    if error:
        ctx["error"] = error
    if flash:
        ctx["flash"] = flash
    return templates.TemplateResponse(
        request, "partials/settings_sources.html.j2", ctx
    )


# ── GET: render sources section ─────────────────────────────────────

@router.get("", response_class=HTMLResponse)
async def get_sources(
    request: Request,
    session=Depends(get_session),
):
    """Render the sources settings section."""
    return await _render_sources(request, session)


# ── POST: add a new source ──────────────────────────────────────────

@router.post("", response_class=HTMLResponse)
async def add_source(
    request: Request,
    slug_or_url: str = Form(...),
    session=Depends(get_session),
):
    """Add a new ATS source after validating against the real API.

    1. detect_source() parses slug and ATS type from the input
    2. validate_source() hits the real ATS API to confirm the board exists
    3. Only if valid: persist via create_source()
    """
    slug_or_url = slug_or_url.strip()
    if not slug_or_url:
        return await _render_sources(
            request, session, error="Please enter a company slug or URL."
        )

    # Step 1: detect source type and slug from input
    slug, source_type = detect_source(slug_or_url)

    # Step 2: validate against real API
    if source_type == "unknown":
        # Probe all three ATS types, use first success
        valid = False
        for probe_type in ("greenhouse", "lever", "ashby"):
            is_valid, _ = await validate_source(slug, probe_type)
            if is_valid:
                source_type = probe_type
                valid = True
                break
        if not valid:
            log.info("source_validation_failed", slug=slug, reason="no ATS matched")
            return await _render_sources(
                request,
                session,
                error=f"Could not find '{slug}' on Greenhouse, Lever, or Ashby. Check the slug and try again.",
            )
    else:
        is_valid, error_msg = await validate_source(slug, source_type)
        if not is_valid:
            log.info(
                "source_validation_failed",
                slug=slug,
                source_type=source_type,
                error=error_msg,
            )
            return await _render_sources(
                request,
                session,
                error=error_msg or f"Could not validate '{slug}' on {source_type}.",
            )

    # Step 3: persist the validated source
    display_name = slug
    await create_source(session, slug, source_type, display_name)
    log.info("source_added", slug=slug, source_type=source_type)

    return await _render_sources(
        request,
        session,
        flash=("success", f"Added {slug} ({source_type})."),
    )


# ── POST: toggle enable/disable ─────────────────────────────────────

@router.post("/{source_id}/toggle", response_class=HTMLResponse)
async def toggle_source_route(
    source_id: int,
    request: Request,
    session=Depends(get_session),
):
    """Toggle a source between enabled and disabled.

    The HTMX checkbox sends the form when toggled. We read the raw form
    to determine the checked state (checkbox absent = unchecked = disable).
    """
    form = await request.form()
    enabled = form.get("enabled", "").lower() in ("true", "on", "1")
    await toggle_source(session, source_id, enabled)
    log.info("source_toggled", source_id=source_id, enabled=enabled)
    # Return empty response -- HTMX switch toggle, no DOM update needed
    return HTMLResponse(content="", status_code=200, headers={"HX-Reswap": "none"})


# ── DELETE: remove a source ──────────────────────────────────────────

@router.delete("/{source_id}", response_class=HTMLResponse)
async def delete_source_route(
    source_id: int,
    request: Request,
    session=Depends(get_session),
):
    """Remove a source permanently."""
    await delete_source(session, source_id)
    log.info("source_deleted", source_id=source_id)
    # Return empty response -- hx-swap="outerHTML" removes the row
    return HTMLResponse(content="", status_code=200)


__all__ = ["router"]
