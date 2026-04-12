"""Runs list + run detail pages.

CONTEXT.md keeps every Run row in the DB forever but only shows the 50 most
recent in the UI, with an HTMX "show more" affordance that appends the next
50 rows to the existing table. The infinite-scroll pattern is vanilla HTMX:
the first request returns the full page, each subsequent ``?offset=N``
request returns only the extra ``<tr>`` rows, which HTMX appends via
``hx-swap="beforeend"``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.models import Run
from app.runs.service import list_recent_runs
from app.web.deps import get_session

router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).parent.parent / "templates")
)


@router.get("/runs", response_class=HTMLResponse)
async def runs_list(
    request: Request,
    offset: int = 0,
    session=Depends(get_session),
):
    """Return the full runs page (offset==0) or a rows-only partial.

    The partial path is used by the HTMX "show more" affordance: it swaps
    ``beforeend`` into the tbody, so the server must emit only ``<tr>``
    elements for ``offset > 0`` — no ``<table>`` wrapper.
    """
    runs = await list_recent_runs(session, limit=50, offset=offset)
    next_offset = offset + 50 if len(runs) == 50 else None
    template = "partials/runs_rows.html.j2" if offset > 0 else "runs_list.html.j2"
    return templates.TemplateResponse(
        request,
        template,
        {
            "runs": runs,
            "next_offset": next_offset,
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(
    run_id: int,
    request: Request,
    session=Depends(get_session),
):
    """Render one Run row in full: timestamps, status, counts JSON, reason."""
    import json

    result = await session.execute(select(Run).where(Run.id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    counts_json = json.dumps(run.counts or {}, indent=2, sort_keys=True)
    return templates.TemplateResponse(
        request,
        "run_detail.html.j2",
        {"run": run, "counts_json": counts_json},
    )


__all__ = ["router"]
